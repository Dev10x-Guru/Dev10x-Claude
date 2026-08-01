#!/usr/bin/env bash
# Create a git worktree, optionally from a base ref and/or a different
# repo root.
#
# Usage: create-worktree.sh <worktree-path> <branch-name> [base-ref] [repo-root]
#   worktree-path: absolute path for the new worktree
#   branch-name:   new branch to create (e.g. user/TICKET-123/feature-description)
#   base-ref:      optional; start-point for the new branch (e.g. origin/develop);
#                  defaults to repo-root's current HEAD when omitted
#   repo-root:     optional; defaults to current working directory's git root
#                  useful when running from a different directory, e.g.:
#                  create-worktree.sh /work/myproject/.worktrees/myproject-1 \
#                    user/TICKET-123/feature origin/develop /work/myproject/myproject

set -euo pipefail

USAGE="Usage: create-worktree.sh <worktree-path> <branch-name> [base-ref] [repo-root]"
WORKTREE_PATH="${1:?$USAGE}"
BRANCH_NAME="${2:?$USAGE}"
BASE_REF="${3:-}"
REPO_ROOT="${4:-}"

GIT_ARGS=(worktree add "$WORKTREE_PATH" -b "$BRANCH_NAME")
if [ -n "$BASE_REF" ]; then
    GIT_ARGS+=("$BASE_REF")
fi

if [ -n "$REPO_ROOT" ]; then
    git -C "$REPO_ROOT" "${GIT_ARGS[@]}"
else
    git "${GIT_ARGS[@]}"
fi
