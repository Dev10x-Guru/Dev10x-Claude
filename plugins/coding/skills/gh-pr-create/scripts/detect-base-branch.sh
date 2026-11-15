#!/usr/bin/env bash
# Detect the correct base branch for PRs in the current repository.
#
# Logic:
#   1. If origin/develop or origin/development exists → that is the base
#   2. Otherwise → fall back to main/master/trunk (whichever exists)
#
# Usage:
#   source detect-base-branch.sh                    # auto-detect
#   source detect-base-branch.sh --base main         # explicit override
#   source detect-base-branch.sh --base main --force  # override + skip warning
#
# When the repo HAS a development branch but an explicit --base targets
# something else, the script warns and exits 1 (potential mistake).
# Pass --force to suppress the warning and proceed anyway.
#
# Exports: BASE_BRANCH, DEV_BRANCH (empty if no dev branch found)
set -euo pipefail

FORCE=false
EXPLICIT_BASE=""
while [ $# -gt 0 ]; do
    case "$1" in
        --force) FORCE=true; shift ;;
        --base)  EXPLICIT_BASE="$2"; shift 2 ;;
        *)       shift ;;
    esac
done

DEV_BRANCH=""
if git rev-parse --verify origin/develop &>/dev/null; then
    DEV_BRANCH="develop"
elif git rev-parse --verify origin/development &>/dev/null; then
    DEV_BRANCH="development"
fi

if [ -n "$EXPLICIT_BASE" ]; then
    if ! git rev-parse --verify "origin/$EXPLICIT_BASE" &>/dev/null; then
        echo "❌ Explicit base 'origin/$EXPLICIT_BASE' does not exist." >&2
        exit 1
    fi
    if [ -n "$DEV_BRANCH" ] && [ "$EXPLICIT_BASE" != "$DEV_BRANCH" ]; then
        if [ "$FORCE" = true ]; then
            echo "⚠️  Overriding base to '$EXPLICIT_BASE' (repo has '$DEV_BRANCH' branch)." >&2
        else
            echo "❌ This repo has a '$DEV_BRANCH' branch — targeting '$EXPLICIT_BASE' is likely a mistake." >&2
            echo "   Use --force to override if this is intentional." >&2
            exit 1
        fi
    fi
    BASE_BRANCH="$EXPLICIT_BASE"
elif [ -n "$DEV_BRANCH" ]; then
    BASE_BRANCH="$DEV_BRANCH"
else
    BASE_BRANCH=""
    for candidate in main master trunk; do
        if git rev-parse --verify "origin/$candidate" &>/dev/null; then
            BASE_BRANCH="$candidate"
            break
        fi
    done
fi

if [ -z "$BASE_BRANCH" ]; then
    echo "❌ Cannot detect base branch — no develop, main, master, or trunk found on origin." >&2
    exit 1
fi

export BASE_BRANCH
export DEV_BRANCH

# When executed as a standalone script (not sourced), print key=value output
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    echo "BASE_BRANCH=$BASE_BRANCH"
    echo "DEV_BRANCH=$DEV_BRANCH"
fi
