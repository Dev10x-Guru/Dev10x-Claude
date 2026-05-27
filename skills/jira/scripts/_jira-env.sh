#!/bin/bash
# Shared JIRA environment for all jira-*.sh scripts.
# Sources credentials from system keyring and builds base URL.
#
# Required: JIRA_TENANT env var (e.g., "mycompany" for mycompany.atlassian.net)

if [ -z "${JIRA_TENANT:-}" ]; then
  echo "Error: JIRA_TENANT env var is required (e.g., 'mycompany' for mycompany.atlassian.net)" >&2
  exit 1
fi

# These are consumed by the scripts that source this file.
# shellcheck disable=SC2034
JIRA_BASE_URL="https://${JIRA_TENANT}.atlassian.net/rest/api/3"
# shellcheck disable=SC2034
JIRA_EMAIL=$(secret-tool lookup service jira key email)
# shellcheck disable=SC2034
JIRA_TOKEN=$(secret-tool lookup service jira key api_token)
