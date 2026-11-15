#!/usr/bin/env bash
# Configure a SessionEnd hook in a worktree's .claude/settings.local.json
# that prompts the user to remove the worktree when the session ends.
#
# Usage: setup-session-end-hook.sh <worktree-path>

set -euo pipefail

# shellcheck source=../../../bin/require-tool.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)/bin/require-tool.sh"
require_tool jq

WORKTREE_PATH="${1:?Usage: setup-session-end-hook.sh <worktree-path>}"
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLEANUP_SCRIPT="$SKILL_DIR/scripts/session-end-cleanup.sh"
SETTINGS_FILE="$WORKTREE_PATH/.claude/settings.local.json"

mkdir -p "$WORKTREE_PATH/.claude"

HOOK_COMMAND="$CLEANUP_SCRIPT $WORKTREE_PATH"
HOOK_ENTRY=$(jq -n --arg cmd "$HOOK_COMMAND" '{
  matcher: "",
  hooks: [{type: "command", command: $cmd, timeout: 30000}]
}')

if [ -f "$SETTINGS_FILE" ]; then
    # Check if already configured
    if jq -e '.hooks.SessionEnd[]?.hooks[]? | select(.command | contains("session-end-cleanup.sh"))' "$SETTINGS_FILE" > /dev/null 2>&1; then
        echo "SessionEnd hook already configured."
        exit 0
    fi

    # Merge into existing settings
    jq --argjson entry "$HOOK_ENTRY" '.hooks.SessionEnd = ((.hooks.SessionEnd // []) + [$entry])' "$SETTINGS_FILE" > "${SETTINGS_FILE}.tmp"
    mv "${SETTINGS_FILE}.tmp" "$SETTINGS_FILE"
    echo "SessionEnd hook added to $SETTINGS_FILE"
else
    # Create new settings.local.json
    jq -n --argjson entry "$HOOK_ENTRY" '{hooks: {SessionEnd: [$entry]}}' > "$SETTINGS_FILE"
    echo "Created $SETTINGS_FILE with SessionEnd cleanup hook."
fi
