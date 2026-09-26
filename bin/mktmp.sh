#!/usr/bin/env bash
# Generate a unique temp path under /tmp/Dev10x/<namespace>/.
#
# Files: returns a path WITHOUT creating the file (use --create to
# pre-create). This avoids the Write-tool overwrite gate firing on
# every call (GH-39). Callers using the Write tool will create the
# file fresh.
# Directories: always created (the directory is the resource).
#
# Usage:
#   mktmp.sh <namespace> <prefix> [.ext]            # path only, no file
#   mktmp.sh --create <namespace> <prefix> [.ext]   # pre-create empty file
#   mktmp.sh -d <namespace> <prefix>                # create a directory
#
# Examples:
#   mktmp.sh git commit-msg .txt         → /tmp/Dev10x/git/commit-msg.txt.XXXXXXXXXXXX
#   mktmp.sh git pr-review .json         → /tmp/Dev10x/git/pr-review.json.XXXXXXXXXXXX
#   mktmp.sh -d git groom                → /tmp/Dev10x/git/groom.XXXXXXXXXXXX/

set -euo pipefail

DIR_MODE=false
CREATE_FILE=false
while [[ "${1:-}" == -* ]]; do
    case "$1" in
        -d) DIR_MODE=true ;;
        --create) CREATE_FILE=true ;;
        *) echo "mktmp.sh: unknown flag: $1" >&2; exit 2 ;;
    esac
    shift
done

NAMESPACE="${1:?Usage: mktmp.sh [-d|--create] <namespace> <prefix> [.ext]}"
PREFIX="${2:?Usage: mktmp.sh [-d|--create] <namespace> <prefix> [.ext]}"
EXT="${3:-}"

BASEDIR="/tmp/Dev10x/$NAMESPACE"
mkdir -p "$BASEDIR"

# GH-1467: GNU mktemp accepts --dry-run/--tmpdir= and substitutes any
# run of X's, but BSD mktemp (macOS) only recognises -d/-p/-u and only
# substitutes a TRAILING run of X's. -d, -p, -u are common to both
# implementations, so the X's move to the end of the template (the
# extension now sits before the random suffix rather than after it).
TEMPLATE="${PREFIX}${EXT}.XXXXXXXXXXXX"

if $DIR_MODE; then
    mktemp -d -p "$BASEDIR" "$TEMPLATE"
elif $CREATE_FILE; then
    mktemp -p "$BASEDIR" "$TEMPLATE"
else
    mktemp -u -p "$BASEDIR" "$TEMPLATE"
fi
