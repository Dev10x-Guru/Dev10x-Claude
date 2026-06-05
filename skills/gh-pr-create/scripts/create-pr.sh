#!/usr/bin/env bash
# Create a PR with two-pass body generation.
# Usage: create-pr.sh <title> <job_story> <issue_id> \
#            [<fixes_url>] [<base_branch>] [<closes_csv>] [<draft>] [<head_repo>]
#   closes_csv: comma-separated issue numbers to add as Closes #N lines (GH-186)
#   draft: "true" (default) or "false" — pass "false" in solo-maintainer mode (GH-184)
#   head_repo: fork owner for a cross-fork PR (GH-473). When set, the head
#     branch is pushed to that owner's remote and the PR opens with
#     --head <head_repo>:<branch> against the upstream base.
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

FIXES_LINE=""
if [ -n "$FIXES_URL" ]; then
    FIXES_LINE=$(printf '\nFixes: %s\n' "$FIXES_URL")
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

BRANCH_NAME=$(git symbolic-ref --short HEAD)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Detect base branch if not provided
if [ -z "$BASE_BRANCH" ]; then
    # shellcheck source=detect-base-branch.sh
    source "$SCRIPT_DIR/detect-base-branch.sh"
fi

# Load checklist template (substitute issue ID placeholder)
CHECKLIST=""
if [ -f .github/checklist.md ]; then
    CHECKLIST=$(sed "s/ISSUE-NO/$ISSUE/" .github/checklist.md)
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

# First pass: create PR with plain commit list + checklist
COMMITS=$(git log "origin/$BASE_BRANCH..HEAD" --reverse --format="- %s")
BODY=$(printf '%s\n\n---\n\n%s%s%s\n\n---\n\n%s' \
    "$JOB_STORY" "$COMMITS" "$CLOSES_BLOCK" "$FIXES_LINE" "$CHECKLIST")

CREATE_ARGS=(--base "$BASE_BRANCH" --title "$TITLE" --body "$BODY")
if [ -n "$HEAD_REPO" ]; then
    CREATE_ARGS+=(--head "$HEAD_REPO:$BRANCH_NAME")
fi
if [ "$DRAFT" = "true" ]; then
    CREATE_ARGS=(--draft "${CREATE_ARGS[@]}")
fi
gh pr create "${CREATE_ARGS[@]}"

# Get PR number
PR_NUMBER=$(gh pr view --json number -q .number)

# Second pass: update body with linked commits
LINKED_COMMITS=$("$SCRIPT_DIR/generate-commit-list.sh" "$PR_NUMBER" "$BASE_BRANCH")
FINAL_BODY=$(printf '%s\n\n---\n\n%s%s%s\n\n---\n\n%s' \
    "$JOB_STORY" "$LINKED_COMMITS" "$CLOSES_BLOCK" "$FIXES_LINE" "$CHECKLIST")

# Use REST API instead of `gh pr edit` to avoid GraphQL Projects-classic
# deprecation warnings causing exit 1 even when the body update succeeds.
# See GH-41 for context (session c83f5182).
REPO_NWO=$(gh repo view --json nameWithOwner -q .nameWithOwner)
BODY_FILE=$(mktemp)
trap 'rm -f "$BODY_FILE"' EXIT
printf '%s' "$FINAL_BODY" > "$BODY_FILE"
gh api -X PATCH "repos/$REPO_NWO/pulls/$PR_NUMBER" -F "body=@$BODY_FILE" \
    --jq '.number' > /dev/null

echo "$PR_NUMBER"
