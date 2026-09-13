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
)

BASES=(develop development trunk main master)

# Every merge-base resolves against origin/<base>, never the local ref
# (GH-1281). A local `develop` last pulled hours ago moves the merge-base
# backwards, so the -log and -diff aliases reported every commit merged
# since as part of this branch — one session reviewed 36 files where 18
# had changed.
#
# The four shapes are declared once and expanded per base rather than
# written out twenty times, because writing them out twenty times is the
# mechanism that produced GH-1281: `autosquash-*` was authored separately,
# stayed correctly qualified, and the two families diverged with nothing
# asserting they agreed. Generated, they cannot disagree.
for base in "${BASES[@]}"; do
    merge_base="\$(git merge-base origin/${base} HEAD)"
    ALIASES+=(
        "${base}-log:git log --oneline ${merge_base}..HEAD"
        "${base}-diff:git diff ${merge_base}..HEAD"
        "${base}-rebase:git rebase -i --autosquash ${merge_base}"
        "autosquash-${base}:env GIT_SEQUENCE_EDITOR=true git rebase -i --autosquash ${merge_base}"
    )
done

for entry in "${ALIASES[@]}"; do
    name="${entry%%:*}"
    value="${entry#*:}"

    # What an earlier version of this script wrote for the same alias: the
    # current definition with the remote qualification removed. Without this,
    # the already-configured branch below would skip every machine that ever
    # ran the pre-GH-1281 script and the fix would reach only new installs.
    superseded="${value//merge-base origin\//merge-base }"

    existing=$(git config --global --get "alias.${name}" 2>/dev/null || true)
    if [[ -z "$existing" ]]; then
        git config --global "alias.${name}" "!${value}"
        echo "  + git ${name} (configured)"
    elif [[ "$existing" == "!${value}" ]]; then
        echo "  ✓ git ${name} (already configured)"
    elif [[ "$existing" == "!${superseded}" ]]; then
        git config --global "alias.${name}" "!${value}"
        echo "  ↻ git ${name} (updated — now resolves against origin)"
    else
        # Anything else is the user's own definition. Say so rather than
        # overwriting it or reporting it as configured.
        echo "  ! git ${name} (customized — left unchanged)"
    fi
done
