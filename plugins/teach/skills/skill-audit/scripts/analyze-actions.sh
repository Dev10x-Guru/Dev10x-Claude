#!/usr/bin/env bash
# Wrapper for analyze-actions.py — Phase 1 action inventory.
# Usage: analyze-actions.sh <transcript.md> [output.md]
#   If output.md is omitted, writes to stdout.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

exec "$SCRIPT_DIR/analyze-actions.py" "$@"
