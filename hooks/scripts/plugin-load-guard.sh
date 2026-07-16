#!/bin/sh
# Userspace SessionStart guard for the Dev10x plugin-load race (GH-874).
#
# Claude Code can silently skip loading the Dev10x plugin at session
# start (a startup race when concurrent sessions rewrite shared plugin
# state). When that happens no plugin hook fires, so nothing warns the
# user — they discover it only when a skill invocation fails.
#
# This guard is installed into userspace (~/.claude/hooks/) and
# registered as a SessionStart hook in ~/.claude/settings.json, so it
# runs even when plugin discovery skipped the plugin. It checks for the
# per-session marker written by the plugin's SessionStart orchestrator
# (session_load_marker); if the marker is absent it tells the user to
# reload the plugin.
#
# Contract: warn-only, fail-open. It never blocks a session and never
# exits non-zero. It stays silent when the plugin loaded, when the
# plugin is deliberately disabled, or when the marker directory is
# missing entirely.
#
# Env:
#   DEV10X_PLUGIN_LOAD_GUARD_GRACE   grace window in whole seconds to
#                                    wait for the marker (default: 3).
#   DEV10X_PLUGIN_LOAD_GUARD_DIR     marker directory to check
#                                    (default: /tmp/Dev10x/sessions;
#                                    overridable for tests).

set -u

# Read the SessionStart hook JSON payload from stdin.
INPUT=$(cat 2>/dev/null || true)

# Extract session_id without jq — the guard must be self-contained and
# run even when the plugin (and its jq-based helpers) never loaded.
SESSION_ID=$(
    printf '%s' "$INPUT" |
        sed -n 's/.*"session_id"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p'
)

# No session id → nothing to check. Silent.
[ -n "$SESSION_ID" ] || exit 0

# Respect a deliberately-disabled plugin: if the user's settings pin
# the plugin to false, stay silent. Best-effort grep; fail-open.
SETTINGS="${HOME:-}/.claude/settings.json"
if [ -f "$SETTINGS" ] &&
    grep -Eq '"Dev10x@Dev10x-Guru"[[:space:]]*:[[:space:]]*false' "$SETTINGS" 2>/dev/null; then
    exit 0
fi

MARKER_DIR="${DEV10X_PLUGIN_LOAD_GUARD_DIR:-/tmp/Dev10x/sessions}"

# Marker directory absent entirely → the plugin may predate the marker
# feature, or /tmp was cleared. Avoid false alarms. Silent.
[ -d "$MARKER_DIR" ] || exit 0

MARKER="$MARKER_DIR/$SESSION_ID"

# Give the plugin's SessionStart orchestrator a grace window to write
# the marker — hook ordering between plugin and userspace hooks is not
# guaranteed. Poll and exit the moment it appears, so the happy path
# adds no measurable delay; only a genuine load failure waits the full
# window.
GRACE="${DEV10X_PLUGIN_LOAD_GUARD_GRACE:-3}"
i=0
while [ "$i" -lt "$GRACE" ]; do
    [ -e "$MARKER" ] && exit 0
    sleep 1
    i=$((i + 1))
done

# Final check after the grace window.
[ -e "$MARKER" ] && exit 0

# Marker still absent though the marker directory exists → the plugin's
# SessionStart hook never ran this session. Warn (never block).
printf '%s\n' '{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"Dev10x plugin failed to load this session — run /plugin reload. Known Claude Code startup race (GH-874)."}}'
exit 0
