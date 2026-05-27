#!/bin/bash
# Update a JIRA issue using a JSON payload file.
#
# Usage:
#   jira-update.sh ISSUE-KEY /path/to/payload.json
#
# The payload file must contain valid JIRA REST API v3 JSON.
# Example payload for updating description:
#   {"fields":{"description":{"version":1,"type":"doc","content":[...]}}}
#
# Output: HTTP status code (204 = success)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/_jira-env.sh"

TICKET_KEY="${1:?Usage: jira-update.sh ISSUE-KEY PAYLOAD_FILE}"
PAYLOAD_FILE="${2:?Usage: jira-update.sh ISSUE-KEY PAYLOAD_FILE}"

if [ ! -f "$PAYLOAD_FILE" ]; then
  echo "Error: Payload file not found: $PAYLOAD_FILE" >&2
  exit 1
fi

curl -s -w "\n%{http_code}" -X PUT \
  -u "${JIRA_EMAIL}:${JIRA_TOKEN}" \
  -H "Content-Type: application/json" \
  -d @"$PAYLOAD_FILE" \
  "${JIRA_BASE_URL}/issue/${TICKET_KEY}"
