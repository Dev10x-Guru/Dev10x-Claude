#!/usr/bin/env bash
# gh-issue-create.sh — Create a GitHub issue and return JSON.
#
# Usage:
#   gh-issue-create.sh TITLE [--body BODY] [--label LABEL]... [--repo REPO]
#
# If REPO is omitted, detects from current directory.
#
# Output: JSON with number, title, url

set -euo pipefail

TITLE="${1:?Usage: gh-issue-create.sh TITLE [--body BODY] [--label LABEL]... [--repo REPO]}"
shift

BODY=""
REPO=""
MILESTONE=""
LABELS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --body)
            BODY="$2"
            shift 2
            ;;
        --label)
            LABELS+=("$2")
            shift 2
            ;;
        --milestone)
            MILESTONE="$2"
            shift 2
            ;;
        --repo)
            REPO="$2"
            shift 2
            ;;
        *)
            shift
            ;;
    esac
done

if [[ -z "$REPO" ]]; then
    REPO="$(gh repo view --json nameWithOwner -q '.nameWithOwner')"
fi

ARGS=(gh issue create --repo "$REPO" --title "$TITLE")

if [[ -n "$BODY" ]]; then
    ARGS+=(--body "$BODY")
fi

for label in "${LABELS[@]}"; do
    ARGS+=(--label "$label")
done

if [[ -n "$MILESTONE" ]]; then
    ARGS+=(--milestone "$MILESTONE")
fi

URL=$("${ARGS[@]}")
# GH-1492: portable sed — BSD grep (macOS) has no PCRE mode, and this runs
# after the issue already exists, so a failure here misreports success.
NUMBER=$(printf '%s\n' "$URL" | sed -nE 's#.*/issues/([0-9]+)$#\1#p' | tail -n 1)
if [[ ! "$NUMBER" =~ ^[0-9]+$ ]]; then
    echo "gh-issue-create.sh: issue created, but no issue number in gh output: $URL" >&2
    exit 1
fi

gh issue view "$NUMBER" --repo "$REPO" --json number,title,url
