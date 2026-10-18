#!/usr/bin/env bash
# Replace the files a Claude CI review takes its instructions from with
# the trusted ref's copies (GH-1625), so a PR cannot rewrite the prompt,
# args, system prompt, settings or rule references its own review runs
# under. One list here keeps every workflow's trust boundary identical.
#
# Usage: stage-trusted.sh <ref> [--keep-pr-head]
#   Run from the checkout root. --keep-pr-head first copies the PR's own
#   versions to .claude-ci/pr-head/, so a review can read a changed
#   trusted file at its new text.
set -euo pipefail

ref="${1:?usage: $0 <ref> [--keep-pr-head]}"
keep_pr_head="${2:-}"
trusted=(.github/claude .github/claude-ci-settings.json references)

rm -rf .claude-ci
if [[ "$keep_pr_head" == "--keep-pr-head" ]]; then
  mkdir -p .claude-ci/pr-head
  tar -c --ignore-failed-read "${trusted[@]}" | tar -x -C .claude-ci/pr-head
fi
rm -rf "${trusted[@]}"
git archive "$ref" "${trusted[@]}" | tar -x
test -f .github/claude/ci-system-prompt.md
