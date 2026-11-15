#!/bin/bash
# Search JIRA issues with a JQL query.
#
# Usage:
#   jira-search.sh "text ~ 'wheel nut'"
#   jira-search.sh "assignee = currentUser() AND updated >= 2026-01-01" 20
#
# Output: pretty-printed JSON (key, summary, status, parent, issuetype, created)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/_jira-env.sh"

JQL="${1:?Usage: jira-search.sh JQL_QUERY [max_results]}"
MAX="${2:-10}"
FIELDS="key,summary,status,issuetype,parent,created"

ENCODED=$(jq -Rr @uri <<< "$JQL")

curl -s \
  -u "${JIRA_EMAIL}:${JIRA_TOKEN}" \
  "${JIRA_BASE_URL}/search/jql?jql=${ENCODED}&maxResults=${MAX}&fields=${FIELDS}" \
  | jq .
