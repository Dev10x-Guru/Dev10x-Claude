#!/bin/bash
# Add a comment to a JIRA issue.
#
# Usage:
#   jira-comment.sh ISSUE-KEY /path/to/body.md
#
# The body file contains the comment body as plain text or JIRA wiki markup.
# This script uses the v2 REST API endpoint which accepts wiki markup directly
# (v3 requires ADF JSON, which is impractical for ad-hoc commenting).
#
# Output: HTTP status code and the created comment ID

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/_jira-env.sh"

TICKET_KEY="${1:?Usage: jira-comment.sh ISSUE-KEY BODY_FILE}"
BODY_FILE="${2:?Usage: jira-comment.sh ISSUE-KEY BODY_FILE}"

if [ ! -f "$BODY_FILE" ]; then
  echo "Error: Body file not found: $BODY_FILE" >&2
  exit 1
fi

# v2 endpoint accepts a plain wiki-markup string for `body`. Use jq -Rs to
# read the body file and JSON-encode it as a string value.
PAYLOAD=$(jq -Rs '{body: .}' "$BODY_FILE")

# v2 URL (the _jira-env.sh base URL points at v3 — substitute).
V2_BASE_URL="${JIRA_BASE_URL%/3}/2"

curl -s -w "\nHTTP_STATUS:%{http_code}\n" -X POST \
  -u "${JIRA_EMAIL}:${JIRA_TOKEN}" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD" \
  "${V2_BASE_URL}/issue/${TICKET_KEY}/comment" \
  | jq '. | {id: .id, self: .self, status: ((.errorMessages // .errors) // "ok")}' 2>/dev/null || cat
