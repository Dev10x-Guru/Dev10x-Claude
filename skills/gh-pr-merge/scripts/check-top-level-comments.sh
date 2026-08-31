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

# Fetch both surfaces BEFORE filtering: each invocation needs the other's
# rows so a "Re:"-keyed reply disposes of its finding across surfaces
# (GH-1002). gh-pr-respond posts review-BODY replies as issue comments
# (GH-907/GH-920), so a surface-local scan left those findings permanently
# unaddressable.
COMMENTS_RAW=$(gh api "repos/${OWNER}/${REPO}/issues/${PR_NUMBER}/comments")
REVIEWS_RAW=$(gh api "repos/${OWNER}/${REPO}/pulls/${PR_NUMBER}/reviews")

# The PR body is a review surface too (GH-1085). When a reviewer's final
# round is a checklist refresh in the body plus an empty-body review, no
# new "Review Summary (Round N)" comment exists — so without the body the
# filter cannot see that round and the PREVIOUS round's remaining issues
# stay live forever. One extra API call buys the round marker.
PR_BODY=$(gh api "repos/${OWNER}/${REPO}/pulls/${PR_NUMBER}" --jq '.body // ""')

COMMENTS=$(printf '%s' "${COMMENTS_RAW}" \
  | jq -f "${FILTER}" --arg src comment --arg pr_body "${PR_BODY}" \
        --argjson extra "${REVIEWS_RAW}")
REVIEWS=$(printf '%s' "${REVIEWS_RAW}" \
  | jq -f "${FILTER}" --arg src review --arg pr_body "${PR_BODY}" \
        --argjson extra "${COMMENTS_RAW}")

jq -n --argjson c "${COMMENTS}" --argjson r "${REVIEWS}" '$c + $r'
