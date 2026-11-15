#!/usr/bin/env bash
# Shared protected branch configuration.
#
# Source this file to get the DEFAULT_PROTECTED_BRANCHES array and
# the is_protected_branch() function.
#
# Default protected branches: main master develop development staging trunk
#
# Override via environment variable:
#   GIT_PROTECTED_BRANCHES="main master staging release/*"
#
# Pattern matching: glob patterns like release/* are supported.

DEFAULT_PROTECTED_BRANCHES=(main master develop development staging trunk)

if [[ -n "${GIT_PROTECTED_BRANCHES:-}" ]]; then
    read -r -a PROTECTED_BRANCHES <<< "$GIT_PROTECTED_BRANCHES"
else
    PROTECTED_BRANCHES=("${DEFAULT_PROTECTED_BRANCHES[@]}")
fi

is_protected_branch() {
    local branch="$1"
    for pattern in "${PROTECTED_BRANCHES[@]}"; do
        # shellcheck disable=SC2254
        case "$branch" in
            $pattern) return 0 ;;
        esac
    done
    return 1
}
