#!/usr/bin/env bash
# Wrapper for extract-session.py — runs extraction.
# Usage: extract-session.sh <jsonl-path> [output.md]
#   If output.md is omitted, writes to stdout.
#   Caller should create a unique output path via bin/mktmp.sh first.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

exec "$SCRIPT_DIR/extract-session.py" "$@"
