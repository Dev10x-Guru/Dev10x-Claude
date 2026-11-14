#!/usr/bin/env bash
# Shared helpers for the skill-index generators (ADR-0034 Stage A3, GH-1552).
#
# families.yaml is split into fragments keyed by future plugin:
# families.yaml holds the core part and families.d/<plugin>.yaml the
# rest. Fragments merge core first, then in the order
# src/dev10x/core/plugins.yaml lists the plugins — the same order
# dev10x.core.config.fragments uses — with lists appended and mappings
# merged key by key.
#
# Source this file; it defines functions only.

# plugin_order <plugin_map>
#   Print plugin names, core first, then the plugin map's order.
plugin_order() {
    local plugin_map="$1"
    echo core
    yq '.plugins | keys | .[]' "$plugin_map" | grep -vx core
}

# families_sources <script_dir> <plugin_map>
#   Print families.yaml, then each families.d/<plugin>.yaml in merge order.
#   Fails on a fragment named after no plugin.
families_sources() {
    local script_dir="$1" plugin_map="$2"
    local fragment_dir="${script_dir}/families.d"
    echo "${script_dir}/families.yaml"
    [[ -d "$fragment_dir" ]] || return 0

    local known plugin fragment name
    known="$(plugin_order "$plugin_map")"
    for fragment in "$fragment_dir"/*.yaml; do
        [[ -f "$fragment" ]] || continue
        name="$(basename "$fragment" .yaml)"
        if ! grep -qx "$name" <<< "$known"; then
            echo >&2 "ERROR: $fragment must be named after a plugin in $plugin_map"
            return 1
        fi
    done
    while IFS= read -r plugin; do
        fragment="${fragment_dir}/${plugin}.yaml"
        [[ -f "$fragment" ]] && echo "$fragment"
    done <<< "$known"
    return 0
}

# merge_families <output> <source>...
#   Write the merged families document to <output>.
merge_families() {
    local output="$1"
    shift
    # shellcheck disable=SC2016  # $item is a yq variable, not a shell one
    yq eval-all '. as $item ireduce ({}; . *+ $item)' "$@" > "$output"
}

# is_core_root <dir>
#   Succeed when <dir> is a dev10x core root: it holds the plugin map and
#   the bin/ helpers the generators source.
is_core_root() {
    local dir="$1"
    [[ -f "$dir/src/dev10x/core/plugins.yaml" && -f "$dir/bin/require-tool.sh" ]]
}

# core_root <plugin_root>
#   Print core's root wherever this skill's plugin sits (GH-1568), trying
#   in order: a pre-split core install (<plugin_root> itself), a checkout or
#   marketplace clone (<repo>/plugins/teach), and an installed satellite
#   whose core sits beside it at <cache>/<publisher>/dev10x/<newest ver>.
#   Fails when none of them is a core root.
core_root() {
    local plugin_root="$1"
    local outer newest
    outer="$(dirname "$(dirname "$plugin_root")")"
    if is_core_root "$plugin_root"; then
        echo "$plugin_root"
        return 0
    fi
    if is_core_root "$outer"; then
        echo "$outer"
        return 0
    fi
    [[ -d "$outer/dev10x" ]] || return 1
    newest="$(printf '%s\n' "$outer"/dev10x/*/ | sort -V | tail -n1)"
    newest="${newest%/}"
    is_core_root "$newest" || return 1
    echo "$newest"
}

# plugin_skill_dirs <dev10x_skills_dir>
#   Print every plugin root's skills directory: the dev10x plugin's own,
#   then any plugins/<name>/skills shipped beside it (Stage B layout).
plugin_skill_dirs() {
    local dev10x_dir="$1"
    [[ -n "$dev10x_dir" && -d "$dev10x_dir" ]] || return 0
    echo "$dev10x_dir"
    local root extra
    root="$(dirname "$dev10x_dir")"
    for extra in "$root"/plugins/*/skills; do
        [[ -d "$extra" ]] && echo "$extra"
    done
    return 0
}
