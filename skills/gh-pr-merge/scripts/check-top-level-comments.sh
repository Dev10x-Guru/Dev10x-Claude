#!/usr/bin/env bash
# Check for unaddressed automated review comments on a PR (GH-743 F2,
# GH-764).
#
# Gates on ALL top-level review surfaces, not just keyword-matching
# issue comments:
#   1. issue comments  (repos/:o/:r/issues/:n/comments)
#   2. review bodies    (repos/:o/:r/pulls/:n/reviews)
#
# The selection logic lives in the sibling `top-level-comments.jq` so
# it can be unit-tested in isolation (a jq string-literal escape/
# predicate bug is invisible to shellcheck — GH-764 F1). See that file
# for the is_bot / blocking / active predicate contract.
#
# Usage: check-top-level-comments.sh <owner> <repo> <pr_number>
# Outputs a JSON array of findings (empty array = pass); each finding
# carries a "source" field ("comment" | "review").
set -euo pipefail

OWNER="$1"
REPO="$2"
PR_NUMBER="$3"

FILTER="$(dirname "$0")/top-level-comments.jq"

COMMENTS=$(gh api "repos/${OWNER}/${REPO}/issues/${PR_NUMBER}/comments" \
  | jq -f "${FILTER}" --arg src comment)
REVIEWS=$(gh api "repos/${OWNER}/${REPO}/pulls/${PR_NUMBER}/reviews" \
  | jq -f "${FILTER}" --arg src review)

jq -n --argjson c "${COMMENTS}" --argjson r "${REVIEWS}" '$c + $r'
