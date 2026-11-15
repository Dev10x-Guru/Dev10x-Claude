#!/usr/bin/env bash
#
# Start interactive rebase to split a commit
#
# Usage: start-split-rebase.sh COMMIT_HASH [BASE_BRANCH]
#
# COMMIT_HASH: The commit to split
# BASE_BRANCH: The base branch (default: develop)
#
# This script marks the specified commit for editing in an interactive rebase,
# then resets it to unstage all changes, allowing you to create multiple
# atomic commits from the original monolithic commit.

set -euo pipefail

# Check arguments
if [ $# -lt 1 ]; then
    echo "Usage: $0 COMMIT_HASH [BASE_BRANCH]"
    echo ""
    echo "COMMIT_HASH: The commit to split"
    echo "BASE_BRANCH: The base branch (default: develop)"
    exit 1
fi

COMMIT_HASH="$1"
BASE_BRANCH="${2:-develop}"

echo "Starting interactive rebase to split commit: $COMMIT_HASH"
echo "Base branch: $BASE_BRANCH"
echo ""

# Start interactive rebase, marking commit for editing
GIT_SEQUENCE_EDITOR="sed -i 's/^pick $COMMIT_HASH/edit $COMMIT_HASH/'" git rebase -i "$BASE_BRANCH"

# Reset the commit to unstage all changes
echo ""
echo "Resetting commit to unstage all changes..."
git reset HEAD~1

echo ""
echo "✓ Ready to split commit!"
echo ""
echo "Next steps:"
echo "1. Stage files for the first commit: git add <files>"
echo "2. Create first commit: git commit --no-verify -m '...'"
echo "3. Repeat for each logical change"
echo "4. Continue rebase: git rebase --continue"
