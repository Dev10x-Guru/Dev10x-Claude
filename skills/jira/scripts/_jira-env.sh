#!/bin/bash
# Shared JIRA environment for all jira-*.sh scripts.
# Sources credentials from system keyring and builds base URL.
#
# Tenant resolution (GH-311): prefer a leading `--tenant <name>` flag so
# the tenant binds as a command argument that the allow-rule prefix still
# matches. Falls back to the JIRA_TENANT env var when the flag is absent.
# Sourced with no args, so `$1`/`shift` operate on the caller's positional
# parameters — every jira-*.sh script gains the flag without changes.
if [ "${1:-}" = "--tenant" ]; then
  JIRA_TENANT="${2:?--tenant requires a tenant name}"
  shift 2
fi

if [ -z "${JIRA_TENANT:-}" ]; then
  echo "Error: pass --tenant <name> or set JIRA_TENANT (e.g., 'mycompany' for mycompany.atlassian.net)" >&2
  exit 1
fi

# These are consumed by the scripts that source this file.
# shellcheck disable=SC2034
JIRA_BASE_URL="https://${JIRA_TENANT}.atlassian.net/rest/api/3"
# shellcheck disable=SC2034
JIRA_EMAIL=$(secret-tool lookup service jira key email)
# shellcheck disable=SC2034
JIRA_TOKEN=$(secret-tool lookup service jira key api_token)
