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
