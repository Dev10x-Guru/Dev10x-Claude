#!/usr/bin/env bash
# Generate a linked commit list for a PR body.
# Usage: generate-commit-list.sh <pr_number> [<base_branch>]
# If pr_number is "PLACEHOLDER", generates unlinked list.
set -euo pipefail

PR_NUMBER="${1:-PLACEHOLDER}"
BASE_BRANCH="${2:-}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ -z "$BASE_BRANCH" ]; then
    # shellcheck source=detect-base-branch.sh
    source "$SCRIPT_DIR/detect-base-branch.sh"
fi

REPO_URL=$(gh repo view --json url -q .url)

git log "origin/$BASE_BRANCH..HEAD" --reverse --format="%H %s" | while read -r hash msg; do
    short=$(echo "$hash" | cut -c1-8)
    echo "[\`${short}\`](${REPO_URL}/pull/${PR_NUMBER}/commits/${hash}) ${msg}"
done
