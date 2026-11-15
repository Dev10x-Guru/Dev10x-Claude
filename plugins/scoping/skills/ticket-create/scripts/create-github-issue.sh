#!/usr/bin/env bash
set -euo pipefail

# Create a GitHub issue from a file where line 1 is the title
# and the rest (after a blank line) is the body.
#
# Usage: create-github-issue.sh <body-file> <repo> [label]
#
# The file format mirrors git commit -F:
#   Line 1: Title
#   Line 2: (blank)
#   Line 3+: Body (markdown)
#
# Outputs the created issue URL on success.

FILE="${1:?Usage: create-github-issue.sh <file> <repo> [label]}"
REPO="${2:?Usage: create-github-issue.sh <file> <repo> [label]}"
LABEL="${3:-}"

if [[ ! -f "$FILE" ]]; then
    echo "Error: File not found: $FILE" >&2
    exit 1
fi

TITLE=$(head -1 "$FILE")
if [[ -z "$TITLE" ]]; then
    echo "Error: First line of $FILE is empty — expected title" >&2
    exit 1
fi

BODY_ONLY=$(/tmp/Dev10x/bin/mktmp.sh gh-issue body-only .md)
tail -n +3 "$FILE" > "$BODY_ONLY"

LABEL_ARGS=""
if [[ -n "$LABEL" ]]; then
    LABEL_ARGS="--label $LABEL"
fi

# shellcheck disable=SC2086
gh issue create --repo "$REPO" --title "$TITLE" --body-file "$BODY_ONLY" $LABEL_ARGS
