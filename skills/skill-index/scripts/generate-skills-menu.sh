#!/usr/bin/env bash
# Generate ~/.claude/.skills-menu.txt — compact terminal-friendly skill index.
# Sourced from families.yaml and skill definitions with Dev10x: prefix invocations.
set -euo pipefail

SKILLS_MENU="${HOME}/.claude/.skills-menu.txt"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USER_CONFIG_DIR="${HOME}/.claude/skill-index"
BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)/bin"
# shellcheck source=../../../bin/require-tool.sh
source "$BIN_DIR/require-tool.sh"
require_tool yq
require_tool jq

# ── Resolve config files (user-space overrides plugin defaults) ──
# families.yaml: user file replaces plugin default entirely
if [[ -f "${USER_CONFIG_DIR}/families.yaml" ]]; then
    FAMILIES_FILE="${USER_CONFIG_DIR}/families.yaml"
else
    FAMILIES_FILE="${SCRIPT_DIR}/families.yaml"
fi

# hidden.yaml: user file merges with plugin default (additive)
HIDDEN_FILE="${SCRIPT_DIR}/hidden.yaml"
USER_HIDDEN_FILE="${USER_CONFIG_DIR}/hidden.yaml"

# ── Resolve skill source directories ────────────────────────────
LOCAL_DIR="${HOME}/.claude/skills"

resolve_Dev10x_dir() {
    local cache_base="${HOME}/.claude/plugins/cache"
    [[ -d "$cache_base" ]] || return 0

    find "$cache_base" -mindepth 4 -maxdepth 4 -type d -name skills 2>/dev/null \
        | while IFS= read -r skills_dir; do
            [[ -f "$skills_dir/skill-index/SKILL.md" ]] || continue
            version="$(basename "$(dirname "$skills_dir")")"
            printf '%s\t%s\n' "$version" "$skills_dir"
        done \
        | sort -t $'\t' -k1,1V \
        | tail -n1 \
        | cut -f2-
}

DEV10X_DIR="$(resolve_Dev10x_dir)"

# ── Parse SKILL.md frontmatter ──────────────────────────────────
declare -A SKILL_NAME
ALL_KEYS=()

parse_skill() {
    local skill_file="$1"
    local json name inv_name key

    json=$(yq --front-matter=extract -o=json \
        '{"n": .name, "k": (.["invocation-name"] // "")}' \
        "$skill_file" 2>/dev/null) || return

    name=$(jq -r '.n // empty' <<< "$json") || return
    [[ -z "$name" || "$name" == *"{"* || "$name" == "my-skill-name" ]] && return

    inv_name=$(jq -r '.k // empty' <<< "$json")

    key="${inv_name:-$name}"
    key="${key%%#*}"
    key="${key%"${key##*[![:space:]]}"}"

    SKILL_NAME["$key"]="$name"
    ALL_KEYS+=("$key")
}

# Scan local and Dev10x skills
if [[ -d "$LOCAL_DIR" ]]; then
    for sf in "$LOCAL_DIR"/*/SKILL.md; do
        [[ -f "$sf" ]] || continue
        parse_skill "$sf"
    done
fi

if [[ -n "$DEV10X_DIR" && -d "$DEV10X_DIR" ]]; then
    for sf in "$DEV10X_DIR"/*/SKILL.md; do
        [[ -f "$sf" ]] || continue
        parse_skill "$sf"
    done
fi

# ── Load hidden list (merged: plugin defaults + user additions) ─
declare -A HIDDEN
for hf in "$HIDDEN_FILE" "$USER_HIDDEN_FILE"; do
    [[ -f "$hf" ]] || continue
    while IFS= read -r h; do
        [[ -n "$h" ]] && HIDDEN["$h"]=1
    done < <(yq '.hidden[]' "$hf")
done

# ── Filter: remove hidden skills ────────────────────────────────
VISIBLE_KEYS=()
for key in "${ALL_KEYS[@]}"; do
    local_name="${SKILL_NAME[$key]:-}"
    if [[ -n "${HIDDEN[$key]:-}" || -n "${HIDDEN[$local_name]:-}" ]]; then
        continue
    fi
    VISIBLE_KEYS+=("$key")
done

# ── Load display_map ──────────────────────────────────────────────
declare -A DISPLAY_TO_KEY
if yq '.display_map' "$FAMILIES_FILE" | grep -q '^[^n]'; then
    while IFS='=' read -r display_name internal_key; do
        display_name="${display_name## }"
        display_name="${display_name%% }"
        internal_key="${internal_key## }"
        internal_key="${internal_key%% }"
        [[ -n "$display_name" && -n "$internal_key" ]] || continue
        DISPLAY_TO_KEY["$display_name"]="$internal_key"
    done < <(yq '.display_map | to_entries | .[] | .key + "=" + .value' "$FAMILIES_FILE")
fi

# ── Load families ───────────────────────────────────────────────
declare -a FAMILY_LABELS
declare -A FAMILY_SKILLS
family_count=$(yq '.families | length' "$FAMILIES_FILE")

for ((i = 0; i < family_count; i++)); do
    label=$(yq ".families[$i].label" "$FAMILIES_FILE")
    FAMILY_LABELS+=("$label")
    skills_str=$(yq ".families[$i].skills[]" "$FAMILIES_FILE" | tr '\n' '|')
    FAMILY_SKILLS["$label"]="$skills_str"
done

# ── Build visible set ───────────────────────────────────────────
declare -A VISIBLE_SET
for key in "${VISIBLE_KEYS[@]}"; do
    VISIBLE_SET["$key"]=1
done

# ── Match and render ────────────────────────────────────────────
{
    printf '# Dev10x skills\n\n'

    for label in "${FAMILY_LABELS[@]}"; do
        IFS='|' read -ra fam_skills <<< "${FAMILY_SKILLS[$label]}"
        tokens=()
        for display in "${fam_skills[@]}"; do
            [[ -z "$display" ]] && continue
            # Resolve display to key
            key="$display"
            [[ -n "${DISPLAY_TO_KEY[$display]:-}" ]] && key="${DISPLAY_TO_KEY[$display]}"
            [[ -z "${VISIBLE_SET[$key]:-}" ]] && continue
            # Get full invocation name
            invocation="${SKILL_NAME[$key]:-$key}"
            tokens+=("$invocation")
        done
        [[ ${#tokens[@]} -eq 0 ]] && continue
        printf '%s: ' "$label"
        printf '%s  ' "${tokens[@]}"
        printf '\n'
    done
} > "$SKILLS_MENU"

echo "Generated .skills-menu.txt (${#VISIBLE_KEYS[@]} visible skills)"
