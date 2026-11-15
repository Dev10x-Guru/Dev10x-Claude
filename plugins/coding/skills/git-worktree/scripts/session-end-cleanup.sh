#!/usr/bin/env bash
# SessionEnd hook script — prompts user to remove worktree.
# Called automatically when a Claude Code session ends in a worktree.
#
# Usage: session-end-cleanup.sh <worktree-path>
#
# Output goes to AI system context (SessionEnd hook behavior).
# The AI should relay the prompt to the user.

set -euo pipefail

WORKTREE_PATH="${1:?Usage: session-end-cleanup.sh <worktree-path>}"

if [ ! -d "$WORKTREE_PATH" ]; then
    echo "Worktree already removed: $WORKTREE_PATH"
    exit 0
fi

# Check if worktree has uncommitted changes
cd "$WORKTREE_PATH"
if git diff --quiet && git diff --cached --quiet; then
    DIRTY=""
else
    DIRTY=" (has uncommitted changes)"
fi

# Check for unpushed commits
BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "detached")
UPSTREAM=$(git rev-parse --abbrev-ref "@{upstream}" 2>/dev/null || echo "")
if [ -n "$UPSTREAM" ]; then
    UNPUSHED=$(git rev-list "$UPSTREAM"..HEAD --count 2>/dev/null || echo "0")
    if [ "$UNPUSHED" -gt 0 ]; then
        DIRTY="$DIRTY ($UNPUSHED unpushed commits)"
    fi
else
    UNPUSHED=$(git rev-list HEAD --count 2>/dev/null || echo "0")
    DIRTY="$DIRTY (no upstream, $UNPUSHED local commits)"
fi

echo "WORKTREE_CLEANUP_PROMPT"
echo "path: $WORKTREE_PATH"
echo "branch: $BRANCH"
echo "status:$DIRTY"
echo ""
echo "Ask the user: This session used worktree at $WORKTREE_PATH (branch: $BRANCH)${DIRTY}."
echo "Would they like to remove it? If dirty or unpushed, warn before removing."
echo "To remove: git worktree remove $WORKTREE_PATH"
echo "To force:  git worktree remove --force $WORKTREE_PATH"
