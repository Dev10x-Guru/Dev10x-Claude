#!/usr/bin/env bash
# Post summary + checklist as first PR comment.
# Usage: post-summary-comment.sh <issue_id> <summary_text>
# summary_text should be markdown bullet points (one per line).
set -euo pipefail

ISSUE="$1"
SUMMARY_TEXT="$2"

SUMMARY=$(printf '### Summary\n\n%s\n\n---\n' "$SUMMARY_TEXT")

if [ -f .github/checklist.md ]; then
    CHECKLIST=$(sed -e "s/ISSUE-NO/$ISSUE/" .github/checklist.md)
    COMMENT=$(printf '%s\n%s' "$SUMMARY" "$CHECKLIST")
else
    COMMENT="$SUMMARY"
fi

gh pr comment --body "$COMMENT"
