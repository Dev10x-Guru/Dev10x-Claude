#!/usr/bin/env bash
# Sets up git aliases that keep Bash command prefixes stable for Claude
# Code permission matching, eliminating unnecessary approval prompts:
#   - branch-comparison aliases that wrap $(git merge-base ...) subshells
#   - `nopager` / `nocolor`, the sanctioned non-paging / non-color reads
#     (replace the `git -c core.pager=cat` / `git -c color.ui=never` prefix-shift
#     shapes blocked by DX007 / GH-488 S19)

set -euo pipefail

ALIASES=(
    "nopager:git --no-pager"
    "nocolor:git -c color.ui=never"
    "develop-log:git log --oneline \$(git merge-base develop HEAD)..HEAD"
    "develop-diff:git diff \$(git merge-base develop HEAD)..HEAD"
    "develop-rebase:git rebase -i --autosquash \$(git merge-base develop HEAD)"
    "development-log:git log --oneline \$(git merge-base development HEAD)..HEAD"
    "development-diff:git diff \$(git merge-base development HEAD)..HEAD"
    "development-rebase:git rebase -i --autosquash \$(git merge-base development HEAD)"
    "trunk-log:git log --oneline \$(git merge-base trunk HEAD)..HEAD"
    "trunk-diff:git diff \$(git merge-base trunk HEAD)..HEAD"
    "trunk-rebase:git rebase -i --autosquash \$(git merge-base trunk HEAD)"
    "main-log:git log --oneline \$(git merge-base main HEAD)..HEAD"
    "main-diff:git diff \$(git merge-base main HEAD)..HEAD"
    "main-rebase:git rebase -i --autosquash \$(git merge-base main HEAD)"
    "master-log:git log --oneline \$(git merge-base master HEAD)..HEAD"
    "master-diff:git diff \$(git merge-base master HEAD)..HEAD"
    "master-rebase:git rebase -i --autosquash \$(git merge-base master HEAD)"
    "autosquash-develop:env GIT_SEQUENCE_EDITOR=true git rebase -i --autosquash \$(git merge-base origin/develop HEAD)"
    "autosquash-development:env GIT_SEQUENCE_EDITOR=true git rebase -i --autosquash \$(git merge-base origin/development HEAD)"
    "autosquash-trunk:env GIT_SEQUENCE_EDITOR=true git rebase -i --autosquash \$(git merge-base origin/trunk HEAD)"
    "autosquash-main:env GIT_SEQUENCE_EDITOR=true git rebase -i --autosquash \$(git merge-base origin/main HEAD)"
    "autosquash-master:env GIT_SEQUENCE_EDITOR=true git rebase -i --autosquash \$(git merge-base origin/master HEAD)"
)

for entry in "${ALIASES[@]}"; do
    name="${entry%%:*}"
    value="${entry#*:}"

    existing=$(git config --global --get "alias.${name}" 2>/dev/null || true)
    if [[ -n "$existing" ]]; then
        echo "  ✓ git ${name} (already configured)"
    else
        git config --global "alias.${name}" "!${value}"
        echo "  + git ${name} (configured)"
    fi
done
