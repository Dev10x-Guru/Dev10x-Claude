#!/usr/bin/env bash
# Wrapper for analyze-permissions.py — Phase 4 permission friction analysis.
# Usage: analyze-permissions.sh <transcript.md> [settings.json] [output.md]
#   If settings.json is omitted, uses ~/.claude/settings.local.json.
#   If output.md is omitted, writes to stdout.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

exec "$SCRIPT_DIR/analyze-permissions.py" "$@"
