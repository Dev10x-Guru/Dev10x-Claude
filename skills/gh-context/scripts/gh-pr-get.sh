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
# mergeable, reviewDecision, reviewRequests, autoMergeRequest, reviews,
# headRefOid.
# Note: ``merged`` is not a valid gh pr view field (GH-329); use mergedAt.
# The isDraft/mergeable/reviewDecision/reviewRequests fields (GH-668) make
# pr_get a drop-in for the hook-blocked ``gh pr view --json ...`` checks in
# Dev10x:gh-pr-merge (Checks 3/4/7) and Dev10x:verify-acc-dod.
# autoMergeRequest (GH-848 F4) is null unless auto-merge is armed; the merge
# gate reads it to detect a PR that will self-merge on green before its
# pre-merge checks run.
# reviews + headRefOid (GH-917) let the review-request skills tell a human
# approval on the current HEAD from a stale or bot one without dropping to
# the hook-blocked raw ``gh pr view``.
#
# Field-set resilience (GH-931 finding 4): the field list grows as newer gh
# releases expose more of the GraphQL schema, so an older gh build rejects the
# whole call with `Unknown JSON field: "..."`. Because raw ``gh pr view`` is
# hook-blocked in favour of this wrapper, that left no working path at all —
# the block message, the replacement, and the skip-flag warning together
# pointed nowhere. Instead of failing, drop the field gh names in its own
# error and retry, so an old gh yields a payload missing only the fields it
# cannot serve. A consumer treats an absent optional key the same as a null
# one (e.g. absent autoMergeRequest == auto-merge not armed).

set -euo pipefail

NUMBER="${1:?Usage: gh-pr-get.sh NUMBER [REPO]}"
REPO="${2:-$(gh repo view --json nameWithOwner -q '.nameWithOwner')}"

FIELDS=number,title,body,state,baseRefName,headRefName,mergedAt,closedAt,labels,milestone,assignees,author,url,isDraft,mergeable,reviewDecision,reviewRequests,autoMergeRequest,reviews,headRefOid

# One retry per droppable field, bounded so a persistent non-field error
# (auth, network, unknown PR) surfaces instead of looping. The bound must
# exceed the number of fields a genuinely old gh can reject — seven of the
# fields above post-date the GH-267 baseline (isDraft, mergeable,
# reviewDecision, reviewRequests, autoMergeRequest, reviews, headRefOid) —
# or the retry budget runs out before converging on the very builds this
# loop exists to serve. The loop always terminates: each retry removes one
# field, and an empty field list breaks out below.
MAX_ATTEMPTS=12

STDERR_FILE=$(mktemp -t gh-pr-get-stderr.XXXXXX)
trap 'rm -f "$STDERR_FILE"' EXIT

for _ in $(seq 1 "$MAX_ATTEMPTS"); do
    if PAYLOAD=$(gh pr view "$NUMBER" --repo "$REPO" --json "$FIELDS" 2>"$STDERR_FILE"); then
        printf '%s\n' "$PAYLOAD"
        exit 0
    fi

    UNKNOWN_FIELD=$(grep -oP 'Unknown JSON field: "\K[^"]+' "$STDERR_FILE" | head -1 || true)
    if [[ -z "$UNKNOWN_FIELD" ]]; then
        break
    fi

    # `grep -vxF` exits non-zero when it filters out every line, and with
    # `pipefail` that status would fail the assignment and abort under
    # `set -e` — before the empty-check below could break out. Swallow it so
    # the documented "empty field list breaks out" invariant actually holds.
    FIELDS=$(
        printf '%s' "$FIELDS" | tr ',' '\n' |
            { grep -vxF "$UNKNOWN_FIELD" || true; } | paste -sd, -
    )
    if [[ -z "$FIELDS" ]]; then
        break
    fi

    echo "gh-pr-get.sh: this gh build rejects '${UNKNOWN_FIELD}' — retrying without it." >&2
done

cat "$STDERR_FILE" >&2
exit 1
