#!/usr/bin/env bash
# Check for unaddressed automated review comments on a PR (GH-743 F2).
#
# Gates on ALL top-level review surfaces, not just keyword-matching
# issue comments:
#   1. issue comments  (repos/:o/:r/issues/:n/comments)
#   2. review bodies    (repos/:o/:r/pulls/:n/reviews)
#
# A comment/review is flagged when it is from an automated reviewer
# AND carries a blocking signal:
#   - automated reviewer := user.type == "Bot", OR a known review-bot
#     login, OR an embedded HTML marker (third-party LLM reviewers post
#     under generic CI accounts and self-identify only via an HTML
#     comment marker — the case the old login-only filter missed).
#   - blocking signal := a REQUIRED/CRITICAL/BLOCKING keyword OR an
#     HTML marker (bots tag actionable comments with a tracking marker).
#
# Usage: check-top-level-comments.sh <owner> <repo> <pr_number>
# Outputs a JSON array of findings (empty array = pass); each finding
# carries a "source" field ("comment" | "review").
set -euo pipefail

OWNER="$1"
REPO="$2"
PR_NUMBER="$3"

BOT_LOGIN='claude|github-actions|coderabbit|sourcery|openai|codex|copilot'
BLOCKING='REQUIRED|CRITICAL|BLOCKING|\\*\\*\\[BLOCKING\\]\\*\\*|\\*\\*\\[CRITICAL\\]\\*\\*'

# Selection filter shared by both surfaces. $src tags the surface so a
# caller can tell an issue comment from a review body. HTML-marker match
# (<!--) catches review bots posting under generic CI bot accounts.
FILTER="
  def is_bot: (.user.type == \"Bot\")
    or ((.user.login // \"\") | test(\"${BOT_LOGIN}\"));
  def flagged: ((.body // \"\") | test(\"${BLOCKING}\"))
    or ((.body // \"\") | test(\"<!--\"));
  [ .[]
    | select(((.body // \"\") != \"\") and is_bot and flagged)
    | {id, user: .user.login, snippet: ((.body | split(\"\n\")[0])[:80]), source: \$src} ]
"

COMMENTS=$(gh api "repos/${OWNER}/${REPO}/issues/${PR_NUMBER}/comments" \
  | jq --arg src comment "${FILTER}")
REVIEWS=$(gh api "repos/${OWNER}/${REPO}/pulls/${PR_NUMBER}/reviews" \
  | jq --arg src review "${FILTER}")

jq -n --argjson c "${COMMENTS}" --argjson r "${REVIEWS}" '$c + $r'
