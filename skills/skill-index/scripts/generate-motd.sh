#!/usr/bin/env bash
# Generate ~/.claude/SKILLS.md — family-grouped, adaptive-density skill index.
# Sources: local skills, installed Dev10x plugin, official plugins.
# Pass --force to regenerate even when cache is fresh.
set -euo pipefail

SKILLS_MD="${HOME}/.claude/SKILLS.md"
OLD_MOTD="${HOME}/.claude/.skills-motd.txt"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USER_CONFIG_DIR="${HOME}/.claude/skill-index"
BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)/bin"
# shellcheck source=../../../bin/require-tool.sh
source "$BIN_DIR/require-tool.sh"
require_tool yq
require_tool jq
LINE_WIDTH=55
LINE_BUDGET=45

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

OFFICIAL_BASE="${HOME}/.claude/plugins/cache/claude-plugins-official"

# ── Cache check ─────────────────────────────────────────────────
if [[ "${1:-}" != "--force" && -f "$SKILLS_MD" ]]; then
    stale=0
    for src_dir in "$LOCAL_DIR" "$DEV10X_DIR"; do
        [[ -z "$src_dir" || ! -d "$src_dir" ]] && continue
        found=$(find "$src_dir" -maxdepth 2 -name 'SKILL.md' -newer "$SKILLS_MD" 2>/dev/null | head -1)
        [[ -n "$found" ]] && { stale=1; break; }
    done
    if [[ -d "$OFFICIAL_BASE" ]]; then
        found=$(find "$OFFICIAL_BASE" -name 'SKILL.md' -newer "$SKILLS_MD" 2>/dev/null | head -1)
        [[ -n "$found" ]] && stale=1
    fi
    for cfg in "$FAMILIES_FILE" "$HIDDEN_FILE" "$USER_HIDDEN_FILE"; do
        [[ -f "$cfg" && "$cfg" -nt "$SKILLS_MD" ]] && { stale=1; break; }
    done
    [[ $stale -eq 0 ]] && exit 0
fi

# ── Parse SKILL.md frontmatter ──────────────────────────────────
# Reads: name, description, user-invocable, invocation-name
# Sets associative arrays: SKILL_NAME, SKILL_DESC, SKILL_INV, SKILL_INVOCABLE
declare -A SKILL_NAME SKILL_DESC SKILL_INVOCABLE
ALL_KEYS=()

parse_skill() {
    local skill_file="$1"
    local json name desc invocable inv_name key

    json=$(yq --front-matter=extract -o=json \
        '{"n": .name, "d": .description, "i": (.["user-invocable"] // false), "k": (.["invocation-name"] // "")}' \
        "$skill_file" 2>/dev/null) || return

    name=$(jq -r '.n // empty' <<< "$json") || return
    [[ -z "$name" || "$name" == *"{"* || "$name" == "my-skill-name" ]] && return

    desc=$(jq -r '.d // "" | gsub("\n"; " ") | ltrimstr(" ") | rtrimstr(" ")' <<< "$json")
    [[ ${#desc} -gt 60 ]] && desc="${desc:0:57}..."

    invocable=$(jq -r 'if .i == true then "true" else "false" end' <<< "$json")
    inv_name=$(jq -r '.k // empty' <<< "$json")

    key="${inv_name:-$name}"
    key="${key%%#*}"
    key="${key%"${key##*[![:space:]]}"}"

    SKILL_NAME["$key"]="$name"
    SKILL_DESC["$key"]="$desc"
    SKILL_INVOCABLE["$key"]="$invocable"
    ALL_KEYS+=("$key")
}

# Scan local skills (override priority)
if [[ -d "$LOCAL_DIR" ]]; then
    for sf in "$LOCAL_DIR"/*/SKILL.md; do
        [[ -f "$sf" ]] || continue
        parse_skill "$sf"
    done
fi

# Scan Dev10x plugin skills (local overrides)
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

# ── Filter: remove hidden skills, build visible list ────────────
VISIBLE_KEYS=()
hidden_count=0
invocable_count=0

for key in "${ALL_KEYS[@]}"; do
    local_name="${SKILL_NAME[$key]:-}"
    if [[ -n "${HIDDEN[$key]:-}" || -n "${HIDDEN[$local_name]:-}" ]]; then
        hidden_count=$((hidden_count + 1))
        continue
    fi
    VISIBLE_KEYS+=("$key")
    if [[ "${SKILL_INVOCABLE[$key]:-false}" == "true" ]]; then
        invocable_count=$((invocable_count + 1))
    fi
done

# ── Load display_map ──────────────────────────────────────────────
# Maps display-name → internal invocation-name key
declare -A DISPLAY_TO_KEY KEY_TO_DISPLAY
if yq '.display_map' "$FAMILIES_FILE" | grep -q '^[^n]'; then
    while IFS='=' read -r display_name internal_key; do
        display_name="${display_name## }"
        display_name="${display_name%% }"
        internal_key="${internal_key## }"
        internal_key="${internal_key%% }"
        [[ -n "$display_name" && -n "$internal_key" ]] || continue
        DISPLAY_TO_KEY["$display_name"]="$internal_key"
        KEY_TO_DISPLAY["$internal_key"]="$display_name"
    done < <(yq '.display_map | to_entries | .[] | .key + "=" + .value' "$FAMILIES_FILE")
fi

# ── Load families ───────────────────────────────────────────────
declare -a FAMILY_LABELS FAMILY_DESCS
declare -A FAMILY_SKILLS
family_count=$(yq '.families | length' "$FAMILIES_FILE")

for ((i = 0; i < family_count; i++)); do
    label=$(yq ".families[$i].label" "$FAMILIES_FILE")
    desc=$(yq ".families[$i].description" "$FAMILIES_FILE")
    FAMILY_LABELS+=("$label")
    FAMILY_DESCS+=("$desc")
    skills_str=$(yq ".families[$i].skills[]" "$FAMILIES_FILE" | tr '\n' '|')
    FAMILY_SKILLS["$label"]="$skills_str"
done

# ── Match visible skills to families ────────────────────────────
# Build a lookup set of visible keys for fast membership test
declare -A VISIBLE_SET
for key in "${VISIBLE_KEYS[@]}"; do
    VISIBLE_SET["$key"]=1
done

# Track which visible skills get assigned to a family
declare -A ASSIGNED

# resolve_key: given a display name from families.yaml, find the
# matching internal key. Try: 1) direct match, 2) display_map lookup.
resolve_key() {
    local display="$1"
    if [[ -n "${VISIBLE_SET[$display]:-}" ]]; then
        echo "$display"
        return
    fi
    local mapped="${DISPLAY_TO_KEY[$display]:-}"
    if [[ -n "$mapped" && -n "${VISIBLE_SET[$mapped]:-}" ]]; then
        echo "$mapped"
        return
    fi
}

# For each family, resolve display names to keys, keep display name
# for rendering. Store as "display=key" pairs separated by |.
# Uses = separator because display names contain colons.
declare -A FAMILY_MATCHED
for label in "${FAMILY_LABELS[@]}"; do
    IFS='|' read -ra fam_skills <<< "${FAMILY_SKILLS[$label]}"
    matched=()
    for display in "${fam_skills[@]}"; do
        [[ -z "$display" ]] && continue
        key=$(resolve_key "$display")
        [[ -z "$key" ]] && continue
        matched+=("${display}=${key}")
        ASSIGNED["$key"]=1
    done
    FAMILY_MATCHED["$label"]=$(IFS='|'; echo "${matched[*]}")
done

# Collect unassigned visible skills for "Other" family
OTHER_SKILLS=()
for key in "${VISIBLE_KEYS[@]}"; do
    if [[ -z "${ASSIGNED[$key]:-}" ]]; then
        OTHER_SKILLS+=("$key")
    fi
done

# ── Pick density mode ───────────────────────────────────────────
visible_total=${#VISIBLE_KEYS[@]}
if [[ $visible_total -le 40 ]]; then
    DENSITY="spacious"
elif [[ $visible_total -le 70 ]]; then
    DENSITY="compact"
else
    DENSITY="packed"
fi

# ── Scan superpowers ────────────────────────────────────────────
SUPERPOWERS_SKILLS=()
SP_DIR=""
if [[ -d "${OFFICIAL_BASE}/superpowers" ]]; then
    sp_ver=$(find "${OFFICIAL_BASE}/superpowers" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort -V | tail -1)
    SP_DIR="${OFFICIAL_BASE}/superpowers/${sp_ver}/skills"
    if [[ -d "$SP_DIR" ]]; then
        for sf in "$SP_DIR"/*/SKILL.md; do
            [[ -f "$sf" ]] || continue
            sp_name=""
            in_fm=0
            while IFS= read -r line; do
                [[ "$line" == "---" ]] && { in_fm=$((in_fm + 1)); [[ $in_fm -ge 2 ]] && break; continue; }
                [[ $in_fm -lt 1 ]] && continue
                case "$line" in
                    name:*) sp_name="${line#name:}"; sp_name="${sp_name# }"; sp_name="${sp_name#\"}"; sp_name="${sp_name%\"}" ;;
                esac
            done < "$sf"
            [[ -n "$sp_name" ]] && SUPERPOWERS_SKILLS+=("$sp_name")
        done
    fi
fi

# ── Scan other official plugins ─────────────────────────────────
SKIP_PLUGINS="superpowers learning-output-style explanatory-output-style"
declare -A PLUGIN_COUNTS
PLUGIN_NAMES=()
other_plugin_skill_total=0

if [[ -d "$OFFICIAL_BASE" ]]; then
    for pdir in "$OFFICIAL_BASE"/*/; do
        [[ -d "$pdir" ]] || continue
        pname=$(basename "$pdir")

        skip=0
        for sp in $SKIP_PLUGINS; do
            [[ "$pname" == "$sp" ]] && { skip=1; break; }
        done
        [[ $skip -eq 1 ]] && continue

        pver=$(find "$pdir" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort -V | tail -1)
        skills_path="$pdir/$pver/skills"
        [[ -d "$skills_path" ]] || continue
        pcount=$(find "$skills_path" -maxdepth 2 -name 'SKILL.md' | wc -l)
        [[ $pcount -eq 0 ]] && continue

        PLUGIN_COUNTS["$pname"]=$pcount
        PLUGIN_NAMES+=("$pname")
        other_plugin_skill_total=$((other_plugin_skill_total + pcount))
    done
fi

# ── Helper: right-pad with ─ to LINE_WIDTH ──────────────────────
header_line() {
    local left="$1" right="$2"
    local pad_char="─"
    local left_len=${#left}
    local right_len=${#right}
    local fill=$((LINE_WIDTH - left_len - right_len))
    [[ $fill -lt 2 ]] && fill=2
    local padding=""
    for ((p = 0; p < fill; p++)); do
        padding="${padding}${pad_char}"
    done
    printf '%s%s%s\n' "$left" "$padding" "$right"
}

# ── Helper: print tokens inline, wrapping at MAX_LINE chars ─────
MAX_LINE=290
print_wrapped() {
    local indent="$1"
    shift
    local line="$indent"
    for token in "$@"; do
        local candidate="${line}${token}  "
        if [[ ${#candidate} -gt $MAX_LINE && "$line" != "$indent" ]]; then
            printf '%s\n' "$line"
            line="${indent}${token}  "
        else
            line="${line}${token}  "
        fi
    done
    [[ "$line" != "$indent" ]] && printf '%s\n' "$line"
}

# ── Render SKILLS.md ────────────────────────────────────────────
{
    # Header
    header_line "─ Dev10x ─" "  ${invocable_count} invocable, ${hidden_count} internal"

    # Helper: for "Other" skills, map key to display name if available
    display_name_for() {
        local key="$1"
        local mapped="${KEY_TO_DISPLAY[$key]:-}"
        [[ -n "$mapped" ]] && echo "$mapped" || echo "$key"
    }

    if [[ "$DENSITY" == "spacious" ]]; then
        # Spacious: family header + one skill per line with description
        for ((i = 0; i < ${#FAMILY_LABELS[@]}; i++)); do
            label="${FAMILY_LABELS[$i]}"
            desc="${FAMILY_DESCS[$i]}"
            family_str="${FAMILY_MATCHED[$label]}"
            [[ -z "$family_str" ]] && continue

            printf '\n%s — %s\n' "$label" "$desc"
            IFS='|' read -ra pairs <<< "$family_str"
            for pair in "${pairs[@]}"; do
                [[ -z "$pair" ]] && continue
                key="${pair#*=}"
                invocation="${SKILL_NAME[$key]:-$key}"
                printf '  /%-22s %s\n' "$invocation" "${SKILL_DESC[$key]:-}"
            done
        done

        if [[ ${#OTHER_SKILLS[@]} -gt 0 ]]; then
            printf '\nOther\n'
            for sk in "${OTHER_SKILLS[@]}"; do
                invocation="${SKILL_NAME[$sk]:-$sk}"
                printf '  /%-22s %s\n' "$invocation" "${SKILL_DESC[$sk]:-}"
            done
        fi

    elif [[ "$DENSITY" == "compact" ]]; then
        # Compact: one line per family, skills inline
        max_label=0
        for label in "${FAMILY_LABELS[@]}"; do
            [[ ${#label} -gt $max_label ]] && max_label=${#label}
        done
        label_width=$((max_label + 1))
        indent_str=$(printf "%-${label_width}s" "")

        for ((i = 0; i < ${#FAMILY_LABELS[@]}; i++)); do
            label="${FAMILY_LABELS[$i]}"
            family_str="${FAMILY_MATCHED[$label]}"
            [[ -z "$family_str" ]] && continue

            IFS='|' read -ra pairs <<< "$family_str"
            tokens=()
            for pair in "${pairs[@]}"; do
                [[ -z "$pair" ]] && continue
                key="${pair#*=}"
                invocation="${SKILL_NAME[$key]:-$key}"
                tokens+=("/${invocation}")
            done

            line=$(printf "%-${label_width}s" "$label")
            for token in "${tokens[@]}"; do
                candidate="${line}  ${token}"
                if [[ ${#candidate} -gt $MAX_LINE && "$line" != "$(printf "%-${label_width}s" "$label")" ]]; then
                    printf '%s\n' "$line"
                    line="${indent_str}  ${token}"
                else
                    line="${line}  ${token}"
                fi
            done
            printf '%s\n' "$line"
        done

        if [[ ${#OTHER_SKILLS[@]} -gt 0 ]]; then
            tokens=()
            for sk in "${OTHER_SKILLS[@]}"; do
                invocation="${SKILL_NAME[$sk]:-$sk}"
                tokens+=("/${invocation}")
            done
            line=$(printf "%-${label_width}s" "Other")
            for token in "${tokens[@]}"; do
                candidate="${line}  ${token}"
                if [[ ${#candidate} -gt $MAX_LINE && "$line" != "$(printf "%-${label_width}s" "Other")" ]]; then
                    printf '%s\n' "$line"
                    line="${indent_str}  ${token}"
                else
                    line="${line}  ${token}"
                fi
            done
            printf '%s\n' "$line"
        fi

    else
        # Packed: inline skills only, no descriptions
        max_label=0
        for label in "${FAMILY_LABELS[@]}"; do
            [[ ${#label} -gt $max_label ]] && max_label=${#label}
        done
        label_width=$((max_label + 1))
        indent_str=$(printf "%-${label_width}s" "")

        for ((i = 0; i < ${#FAMILY_LABELS[@]}; i++)); do
            label="${FAMILY_LABELS[$i]}"
            family_str="${FAMILY_MATCHED[$label]}"
            [[ -z "$family_str" ]] && continue

            IFS='|' read -ra pairs <<< "$family_str"
            tokens=()
            for pair in "${pairs[@]}"; do
                [[ -z "$pair" ]] && continue
                key="${pair#*=}"
                invocation="${SKILL_NAME[$key]:-$key}"
                tokens+=("/${invocation}")
            done

            line=$(printf "%-${label_width}s" "$label")
            for token in "${tokens[@]}"; do
                candidate="${line} ${token}"
                if [[ ${#candidate} -gt $MAX_LINE && "$line" != "$(printf "%-${label_width}s" "$label")" ]]; then
                    printf '%s\n' "$line"
                    line="${indent_str} ${token}"
                else
                    line="${line} ${token}"
                fi
            done
            printf '%s\n' "$line"
        done

        if [[ ${#OTHER_SKILLS[@]} -gt 0 ]]; then
            tokens=()
            for sk in "${OTHER_SKILLS[@]}"; do
                invocation="${SKILL_NAME[$sk]:-$sk}"
                tokens+=("/${invocation}")
            done
            line=$(printf "%-${label_width}s" "Other")
            for token in "${tokens[@]}"; do
                candidate="${line} ${token}"
                if [[ ${#candidate} -gt $MAX_LINE && "$line" != "$(printf "%-${label_width}s" "Other")" ]]; then
                    printf '%s\n' "$line"
                    line="${indent_str} ${token}"
                else
                    line="${line} ${token}"
                fi
            done
            printf '%s\n' "$line"
        fi
    fi

    # Superpowers section
    if [[ ${#SUPERPOWERS_SKILLS[@]} -gt 0 ]]; then
        printf '\n'
        header_line "─ superpowers ─" "  ${#SUPERPOWERS_SKILLS[@]} skills"
        print_wrapped "  " "${SUPERPOWERS_SKILLS[@]}"
    fi

    # Other plugins section
    if [[ ${#PLUGIN_NAMES[@]} -gt 0 ]]; then
        printf '\n'
        header_line "─ other plugins ─" "  ${#PLUGIN_NAMES[@]} plugins, ${other_plugin_skill_total} skills"
        pl_tokens=()
        for pn in "${PLUGIN_NAMES[@]}"; do
            pl_tokens+=("${pn} (${PLUGIN_COUNTS[$pn]})")
        done
        print_wrapped "  " "${pl_tokens[@]}"
    fi

} > "$SKILLS_MD"

# ── Line budget check ───────────────────────────────────────────
line_count=$(wc -l < "$SKILLS_MD")
if [[ $line_count -gt $LINE_BUDGET ]]; then
    echo >&2 "WARNING: SKILLS.md is ${line_count} lines (budget: ${LINE_BUDGET})"
fi

# ── Clean up old MOTD file ──────────────────────────────────────
[[ -f "$OLD_MOTD" ]] && rm -f "$OLD_MOTD"

echo "Generated SKILLS.md (${visible_total} visible, ${invocable_count} invocable, ${hidden_count} internal, density: ${DENSITY})"
