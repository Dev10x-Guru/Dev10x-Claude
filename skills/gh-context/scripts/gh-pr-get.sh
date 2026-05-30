#!/usr/bin/env bash
# gh-pr-get.sh — Fetch GitHub PR details as JSON (GH-267).
#
# Usage:
#   gh-pr-get.sh NUMBER [REPO]
#
# If REPO is omitted, detects from current directory.
#
# Output: JSON with number, title, body, state, baseRefName, headRefName,
# merged, mergedAt, closedAt, labels, milestone, assignees, author, url.

set -euo pipefail

NUMBER="${1:?Usage: gh-pr-get.sh NUMBER [REPO]}"
REPO="${2:-$(gh repo view --json nameWithOwner -q '.nameWithOwner')}"

gh pr view "$NUMBER" --repo "$REPO" \
    --json number,title,body,state,baseRefName,headRefName,mergedAt,closedAt,labels,milestone,assignees,author,url
