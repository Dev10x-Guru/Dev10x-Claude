#!/usr/bin/env bash
set -euo pipefail

# Detect fixup! commits in a PR branch that block merging.
#
# Usage:
#   detect-fixup-commits.sh --pr <number> --repo <owner/repo>
#   detect-fixup-commits.sh --base <branch>
#
# Exits 0 if fixup commits found (prints them), 1 if none found.

PR_NUMBER=""
REPO=""
BASE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --pr) PR_NUMBER="$2"; shift 2 ;;
        --repo) REPO="$2"; shift 2 ;;
        --base) BASE="$2"; shift 2 ;;
        *) echo "Unknown argument: $1" >&2; exit 2 ;;
    esac
done

if [[ -z "$BASE" ]]; then
    if [[ -z "$PR_NUMBER" || -z "$REPO" ]]; then
        echo "Usage: detect-fixup-commits.sh --pr <number> --repo <owner/repo>" >&2
        echo "       detect-fixup-commits.sh --base <branch>" >&2
        exit 2
    fi
    BASE=$(gh pr view "$PR_NUMBER" --repo "$REPO" --json baseRefName -q '.baseRefName')
fi

FIXUPS=$(git log --oneline "origin/${BASE}..HEAD" | grep '^.\{8\} fixup!' || true)

if [[ -n "$FIXUPS" ]]; then
    echo "$FIXUPS"
    exit 0
else
    exit 1
fi
