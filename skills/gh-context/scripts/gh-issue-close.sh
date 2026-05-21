#!/usr/bin/env bash
# gh-issue-close.sh — Close a GitHub issue (GH-268).
#
# Usage:
#   gh-issue-close.sh NUMBER [REPO] [REASON] [COMMENT_FILE]
#
# REASON: "completed" or "not_planned" (defaults to "completed")
# COMMENT_FILE: optional path to file containing a final closing comment.
#
# Output: JSON {number, state, url}.

set -euo pipefail

NUMBER="${1:?Usage: gh-issue-close.sh NUMBER [REPO] [REASON] [COMMENT_FILE]}"
REPO="${2:-$(gh repo view --json nameWithOwner -q '.nameWithOwner')}"
REASON="${3:-completed}"
COMMENT_FILE="${4:-}"

args=("issue" "close" "$NUMBER" "--repo" "$REPO" "--reason" "$REASON")
if [[ -n "$COMMENT_FILE" ]]; then
    args+=("--comment" "$(cat "$COMMENT_FILE")")
fi

gh "${args[@]}" >/dev/null

URL=$(gh issue view "$NUMBER" --repo "$REPO" --json url -q '.url')
printf '{"number": %s, "state": "closed", "url": "%s"}\n' "$NUMBER" "$URL"
