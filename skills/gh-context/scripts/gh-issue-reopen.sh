#!/usr/bin/env bash
# gh-issue-reopen.sh — Reopen a closed GitHub issue (GH-268).
#
# Usage:
#   gh-issue-reopen.sh NUMBER [REPO]
#
# Output: JSON {number, state, url}.

set -euo pipefail

NUMBER="${1:?Usage: gh-issue-reopen.sh NUMBER [REPO]}"
REPO="${2:-$(gh repo view --json nameWithOwner -q '.nameWithOwner')}"

gh issue reopen "$NUMBER" --repo "$REPO" >/dev/null

URL=$(gh issue view "$NUMBER" --repo "$REPO" --json url -q '.url')
printf '{"number": %s, "state": "open", "url": "%s"}\n' "$NUMBER" "$URL"
