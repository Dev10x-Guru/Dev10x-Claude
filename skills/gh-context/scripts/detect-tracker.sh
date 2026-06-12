#!/usr/bin/env bash
# detect-tracker.sh — Detect issue tracker type from a ticket ID.
#
# Uses branch prefix heuristics and GitHub autolink references to
# determine whether a ticket belongs to GitHub Issues, Linear, or JIRA.
#
# Usage:
#   detect-tracker.sh TICKET_ID
#
# Output: KEY=VALUE lines:
#   TRACKER=github|linear|jira|unknown
#   TICKET_ID=GH-15
#   TICKET_NUMBER=15
#   FIXES_URL=https://github.com/your-org/your-repo/issues/15

set -euo pipefail

# shellcheck source=../../../bin/require-tool.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)/bin/require-tool.sh"
require_tool jq

TICKET_ID="${1:?Usage: detect-tracker.sh TICKET_ID}"

# Extract prefix and number from TICKET_ID
PREFIX=$(echo "$TICKET_ID" | grep -oE '^[A-Za-z]+-' | tr -d '-')
NUMBER=$(echo "$TICKET_ID" | grep -oE '[0-9]+$')

# --- Heuristic 1: GH- prefix → GitHub Issues ---
if [[ "$PREFIX" == "GH" ]]; then
    REPO=$(gh repo view --json nameWithOwner -q '.nameWithOwner' 2>/dev/null || echo "")
    if [[ -n "$REPO" ]]; then
        FIXES_URL="https://github.com/${REPO}/issues/${NUMBER}"
    else
        FIXES_URL=""
    fi
    printf 'TRACKER=github\nTICKET_ID=%s\nTICKET_NUMBER=%s\nFIXES_URL=%s\n' \
        "$TICKET_ID" "$NUMBER" "$FIXES_URL"
    exit 0
fi

# --- Heuristic 2: Check autolink references ---
REPO=$(gh repo view --json nameWithOwner -q '.nameWithOwner' 2>/dev/null || echo "")
if [[ -n "$REPO" ]]; then
    AUTOLINKS=$(gh api "repos/${REPO}/autolinks" 2>/dev/null || echo "[]")

    # Find matching autolink by key_prefix
    MATCH=$(echo "$AUTOLINKS" | jq -r \
        --arg prefix "${PREFIX}-" \
        '.[] | select(.key_prefix == $prefix) | .url_template' \
    )

    if [[ -n "$MATCH" ]]; then
        # Replace <num> placeholder with actual number
        FIXES_URL="${MATCH//<num>/${NUMBER}}"

        if echo "$MATCH" | grep -q "linear.app"; then
            printf 'TRACKER=linear\nTICKET_ID=%s\nTICKET_NUMBER=%s\nFIXES_URL=%s\n' \
                "$TICKET_ID" "$NUMBER" "$FIXES_URL"
            exit 0
        elif echo "$MATCH" | grep -q "atlassian.net"; then
            printf 'TRACKER=jira\nTICKET_ID=%s\nTICKET_NUMBER=%s\nFIXES_URL=%s\n' \
                "$TICKET_ID" "$NUMBER" "$FIXES_URL"
            exit 0
        fi
    fi
fi

# --- Heuristic 3: Query Linear API for team prefix validation ---
# Use validated prefix + number to build the identifier safely
SAFE_ID="${PREFIX}-${NUMBER}"
if command -v curl >/dev/null 2>&1 && [[ -n "${LINEAR_API_KEY:-}" ]] && [[ -n "$PREFIX" ]] && [[ -n "$NUMBER" ]]; then
    LINEAR_RESPONSE=$(curl -s -X POST https://api.linear.app/graphql \
        -H "Content-Type: application/json" \
        -H "Authorization: $LINEAR_API_KEY" \
        -d "{\"query\": \"{ issue(identifier: \\\"${SAFE_ID}\\\") { team { key } } organization { urlKey } }\"}" \
        2>/dev/null)

    LINEAR_TEAM=$(echo "$LINEAR_RESPONSE" | jq -r '.data.issue.team.key // empty' 2>/dev/null)

    if [[ -n "$LINEAR_TEAM" ]]; then
        LINEAR_ORG=$(echo "$LINEAR_RESPONSE" | jq -r '.data.organization.urlKey // empty' 2>/dev/null)
        if [[ -n "$LINEAR_ORG" ]]; then
            FIXES_URL="https://linear.app/${LINEAR_ORG}/issue/${SAFE_ID}"
        else
            FIXES_URL=""
        fi
        printf 'TRACKER=linear\nTICKET_ID=%s\nTICKET_NUMBER=%s\nFIXES_URL=%s\n' \
            "$TICKET_ID" "$NUMBER" "$FIXES_URL"
        exit 0
    fi
fi

# --- Fallback: unknown ---
printf 'TRACKER=unknown\nTICKET_ID=%s\nTICKET_NUMBER=%s\nFIXES_URL=\n' \
    "$TICKET_ID" "$NUMBER"
exit 0
