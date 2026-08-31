#!/usr/bin/env bash
# Create a PR with two-pass body generation.
# Usage: create-pr.sh <title> <job_story> <issue_id> \
#            [<fixes_url>] [<base_branch>] [<closes_csv>] [<draft>] \
#            [<head_repo>] [<body>] [<head>]
#   closes_csv: comma-separated issue numbers to add as Closes #N lines (GH-186)
#   draft: "true" (default) or "false" — pass "false" in solo-maintainer mode (GH-184)
#   head_repo: fork owner for a cross-fork PR (GH-473). When set, the head
#     branch is pushed to that owner's remote and the PR opens with
#     --head <head_repo>:<branch> against the upstream base.
#   body: full PR body, used verbatim (GH-1073). When set, the two-pass
#     job-story + commit-list assembly is skipped entirely so the created
#     PR carries exactly what the caller supplied.
#   head: branch to open the PR from (GH-1073). Defaults to the checkout's
#     current HEAD; pass it explicitly to act for another checkout.
# Outputs the PR number on success.
set -euo pipefail

TITLE="$1"
JOB_STORY="$2"
ISSUE="$3"
FIXES_URL="${4:-}"
BASE_BRANCH="${5:-}"
CLOSES_CSV="${6:-}"
DRAFT="${7:-true}"
HEAD_REPO="${8:-}"
BODY_OVERRIDE="${9:-}"
HEAD_BRANCH="${10:-}"

FIXES_LINE=""
if [ -n "$FIXES_URL" ]; then
    # Blank line before the trailer so `Fixes:` renders as its own
    # paragraph and stays the literal last line (GH-945).
    FIXES_LINE=$(printf '\n\nFixes: %s\n' "$FIXES_URL")
fi

CLOSES_BLOCK=""
if [ -n "$CLOSES_CSV" ]; then
    CLOSES_LINES=""
    IFS=',' read -ra _CLOSES_ARR <<< "$CLOSES_CSV"
    for n in "${_CLOSES_ARR[@]}"; do
        n_trim="${n// /}"
        [ -z "$n_trim" ] && continue
        CLOSES_LINES+=$(printf 'Closes #%s\n' "$n_trim")
        CLOSES_LINES+=$'\n'
    done
    if [ -n "$CLOSES_LINES" ]; then
        CLOSES_BLOCK=$(printf '\n%s' "$CLOSES_LINES")
    fi
fi

BRANCH_NAME="${HEAD_BRANCH:-$(git symbolic-ref --short HEAD)}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Detect base branch if not provided
if [ -z "$BASE_BRANCH" ]; then
    # shellcheck source=detect-base-branch.sh
    source "$SCRIPT_DIR/detect-base-branch.sh"
fi

# Load checklist template (substitute issue ID placeholder). The block
# carries its own leading separator so an absent template leaves no bare
# `---` behind — the trailer must end at the Fixes line (GH-945).
CHECKLIST_BLOCK=""
if [ -f .github/checklist.md ]; then
    CHECKLIST=$(sed "s/ISSUE-NO/$ISSUE/" .github/checklist.md)
    if [ -n "$CHECKLIST" ]; then
        CHECKLIST_BLOCK=$(printf '\n---\n\n%s\n' "$CHECKLIST")
    fi
fi

# Push branch. For a cross-fork PR (GH-473), push the head to the fork
# owner's remote (matched by URL owner, then a `fork` remote, then origin)
# rather than to the upstream base remote.
PUSH_REMOTE=origin
if [ -n "$HEAD_REPO" ]; then
    MATCHED_REMOTE=$(git remote -v | awk -v o="$HEAD_REPO/" '$2 ~ o {print $1; exit}')
    if [ -n "$MATCHED_REMOTE" ]; then
        PUSH_REMOTE="$MATCHED_REMOTE"
    elif git remote get-url fork >/dev/null 2>&1; then
        PUSH_REMOTE=fork
    fi
fi
git push --set-upstream "$PUSH_REMOTE" "$BRANCH_NAME"

# First pass: create PR with plain commit list + checklist. A caller-supplied
# body (GH-1073) replaces the assembled template outright — the caller owns
# the whole body, so nothing is appended to it and the second pass is skipped.
if [ -n "$BODY_OVERRIDE" ]; then
    BODY="$BODY_OVERRIDE"
else
    COMMITS=$(git log "origin/$BASE_BRANCH..$BRANCH_NAME" --reverse --format="- %s")
    BODY=$(printf '%s\n\n---\n\n%s%s%s%s' \
        "$JOB_STORY" "$COMMITS" "$CLOSES_BLOCK" "$CHECKLIST_BLOCK" "$FIXES_LINE")
fi

CREATE_ARGS=(--base "$BASE_BRANCH" --title "$TITLE" --body "$BODY")
if [ -n "$HEAD_REPO" ]; then
    CREATE_ARGS+=(--head "$HEAD_REPO:$BRANCH_NAME")
elif [ -n "$HEAD_BRANCH" ]; then
    CREATE_ARGS+=(--head "$BRANCH_NAME")
fi
if [ "$DRAFT" = "true" ]; then
    CREATE_ARGS=(--draft "${CREATE_ARGS[@]}")
fi
# Read the PR number off the URL `gh pr create` prints rather than a
# follow-up `gh pr view` (GH-1073): with an explicit head= the current
# checkout's HEAD is not the PR's branch, so `gh pr view` would resolve
# a different PR — or none.
CREATE_OUTPUT=$(gh pr create "${CREATE_ARGS[@]}")
printf '%s\n' "$CREATE_OUTPUT"
PR_NUMBER=$(printf '%s' "$CREATE_OUTPUT" | grep -oE '/pull/[0-9]+' | grep -oE '[0-9]+$' | tail -1)
if [ -z "$PR_NUMBER" ]; then
    echo "Could not read a PR number from: $CREATE_OUTPUT" >&2
    exit 1
fi

# Second pass: update body with linked commits. Skipped for a
# caller-supplied body, which is used exactly as given (GH-1073).
if [ -z "$BODY_OVERRIDE" ]; then
    LINKED_COMMITS=$("$SCRIPT_DIR/generate-commit-list.sh" "$PR_NUMBER" "$BASE_BRANCH")
    FINAL_BODY=$(printf '%s\n\n---\n\n%s%s%s%s' \
        "$JOB_STORY" "$LINKED_COMMITS" "$CLOSES_BLOCK" "$CHECKLIST_BLOCK" "$FIXES_LINE")

    # Use REST API instead of `gh pr edit` to avoid GraphQL Projects-classic
    # deprecation warnings causing exit 1 even when the body update succeeds.
    # See GH-41 for context (session c83f5182).
    REPO_NWO=$(gh repo view --json nameWithOwner -q .nameWithOwner)
    BODY_FILE=$(mktemp)
    trap 'rm -f "$BODY_FILE"' EXIT
    printf '%s' "$FINAL_BODY" > "$BODY_FILE"
    gh api -X PATCH "repos/$REPO_NWO/pulls/$PR_NUMBER" -F "body=@$BODY_FILE" \
        --jq '.number' > /dev/null
fi

echo "$PR_NUMBER"
