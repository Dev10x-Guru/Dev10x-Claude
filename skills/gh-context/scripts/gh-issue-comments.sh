#!/usr/bin/env bash
# gh-issue-comments.sh — List comments on a GitHub issue.
#
# Usage:
#   gh-issue-comments.sh NUMBER [REPO]
#
# Output: JSON object {"comments": [...]} with author, body, createdAt

set -euo pipefail

NUMBER="${1:?Usage: gh-issue-comments.sh NUMBER [REPO]}"
REPO="${2:-$(gh repo view --json nameWithOwner -q '.nameWithOwner')}"

gh issue view "$NUMBER" --repo "$REPO" --json comments
