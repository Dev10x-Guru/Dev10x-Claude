#!/bin/bash
# Fetch a JIRA issue by key.
#
# Usage:
#   jira-get.sh ISSUE-KEY
#   jira-get.sh ISSUE-KEY summary,status,parent,subtasks,issuelinks
#
# Output: pretty-printed JSON

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/_jira-env.sh"

KEY="${1:?Usage: jira-get.sh ISSUE-KEY [fields]}"
FIELDS="${2:-summary,status,issuetype,parent,subtasks,issuelinks}"

curl -s \
  -u "${JIRA_EMAIL}:${JIRA_TOKEN}" \
  "${JIRA_BASE_URL}/issue/${KEY}?fields=${FIELDS}" \
  | jq .
