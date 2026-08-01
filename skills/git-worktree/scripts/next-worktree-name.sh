#!/usr/bin/env bash
# Calculate the next available worktree path.
#
# Default: ../.worktrees/<project-basename>-NN
# Finds the highest existing number and increments.
#
# Usage: next-worktree-name.sh [base-dir]
#   base-dir: override the worktrees parent (default: ../.worktrees)

set -euo pipefail

# Resolve the MAIN repo root via the git-common-dir, not --show-toplevel
# (GH-960): when invoked from a linked worktree's CWD, --show-toplevel
# returns that worktree's own path, which computes a bogus nested
# "<worktree>/.worktrees" parent instead of the sibling directory next
# to the main checkout. --git-common-dir always resolves to the shared
# .git directory that lives alongside the main repo, regardless of
# which worktree the command runs from.
GIT_COMMON_DIR="$(git rev-parse --git-common-dir)"
case "$GIT_COMMON_DIR" in
    /*) : ;;
    *) GIT_COMMON_DIR="$(pwd)/$GIT_COMMON_DIR" ;;
esac
PROJECT_ROOT="$(cd "$(dirname "$GIT_COMMON_DIR")" && pwd)"
PROJECT_NAME="$(basename "$PROJECT_ROOT")"
BASE_DIR="${1:-$(dirname "$PROJECT_ROOT")/.worktrees}"

mkdir -p "$BASE_DIR"

# Find highest existing number for this project
max=0
for dir in "$BASE_DIR"/"$PROJECT_NAME"-*; do
    [ -d "$dir" ] || continue
    num="${dir##*-}"
    if [[ "$num" =~ ^[0-9]+$ ]] && [ "$num" -gt "$max" ]; then
        max=$num
    fi
done

next=$((max + 1))
echo "$BASE_DIR/$PROJECT_NAME-$next"
