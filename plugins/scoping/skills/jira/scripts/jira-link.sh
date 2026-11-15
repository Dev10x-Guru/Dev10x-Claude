#!/bin/bash
# Create a link between two JIRA issues.
#
# Usage:
#   jira-link.sh PROJ-100 "1-Relates" PROJ-200
#   jira-link.sh PROJ-100 "Blocks" PROJ-200
#
# Common link type names:
#   "1-Relates"   — relates to / relates to
#   "Blocks"      — is blocked by / blocks
#   "Duplicate"   — is duplicated by / duplicates
#   "Cloners"     — is cloned by / clones
#
# The INWARD issue is the one described by the inward text (e.g. "is blocked by").
# The OUTWARD issue is the one described by the outward text (e.g. "blocks").
# Example: jira-link.sh PROJ-100 "Blocks" PROJ-200
#   means PROJ-100 blocks PROJ-200 (PROJ-200 is blocked by PROJ-100)
#
# Output: HTTP status code (201 = success)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/_jira-env.sh"

INWARD="${1:?Usage: jira-link.sh INWARD_KEY LINK_TYPE OUTWARD_KEY}"
TYPE="${2:?Usage: jira-link.sh INWARD_KEY LINK_TYPE OUTWARD_KEY}"
OUTWARD="${3:?Usage: jira-link.sh INWARD_KEY LINK_TYPE OUTWARD_KEY}"

HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
  -X POST \
  -u "${JIRA_EMAIL}:${JIRA_TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"type\":{\"name\":\"${TYPE}\"},\"inwardIssue\":{\"key\":\"${INWARD}\"},\"outwardIssue\":{\"key\":\"${OUTWARD}\"}}" \
  "${JIRA_BASE_URL}/issueLink")

echo "HTTP ${HTTP_STATUS} — ${INWARD} [${TYPE}] ${OUTWARD}"
