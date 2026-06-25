#!/usr/bin/env bash
# gh-pr-get.sh — Fetch GitHub PR details as JSON (GH-267).
#
# Usage:
#   gh-pr-get.sh NUMBER [REPO]
#
# If REPO is omitted, detects from current directory.
#
# Output: JSON with number, title, body, state, baseRefName, headRefName,
# mergedAt, closedAt, labels, milestone, assignees, author, url, isDraft,
# mergeable, reviewDecision, reviewRequests.
# Note: ``merged`` is not a valid gh pr view field (GH-329); use mergedAt.
# The isDraft/mergeable/reviewDecision/reviewRequests fields (GH-668) make
# pr_get a drop-in for the hook-blocked ``gh pr view --json ...`` checks in
# Dev10x:gh-pr-merge (Checks 3/4/7) and Dev10x:verify-acc-dod.

set -euo pipefail

NUMBER="${1:?Usage: gh-pr-get.sh NUMBER [REPO]}"
REPO="${2:-$(gh repo view --json nameWithOwner -q '.nameWithOwner')}"

gh pr view "$NUMBER" --repo "$REPO" \
    --json number,title,body,state,baseRefName,headRefName,mergedAt,closedAt,labels,milestone,assignees,author,url,isDraft,mergeable,reviewDecision,reviewRequests
