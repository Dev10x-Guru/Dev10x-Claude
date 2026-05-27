#!/bin/bash
# List all available JIRA issue link types.
#
# Usage:
#   jira-link-types.sh
#
# Output: one line per type: ID  Name  |  inward / outward

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/_jira-env.sh"

curl -s \
  -u "${JIRA_EMAIL}:${JIRA_TOKEN}" \
  "${JIRA_BASE_URL}/issueLinkType" \
  | jq -r '.issueLinkTypes[] | "\(.id | tostring | (" " * (6 - length)) + .)  \(.name)  | \(.inward // "") / \(.outward // "")"'
