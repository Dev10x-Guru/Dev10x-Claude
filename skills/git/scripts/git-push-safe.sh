#!/usr/bin/env bash
# Safe git push wrapper — blocks force push to protected branches.
#
# Usage: git-push-safe.sh [flags] [remote] [refspec]
#   Do NOT include "push" — the script runs `git push` itself.
#
# Default protected branches: main master develop development staging trunk
# Override: GIT_PROTECTED_BRANCHES="main master staging" git-push-safe.sh -u origin branch
# Per-call: git-push-safe.sh --protected staging --protected release/* -u origin branch

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Parse --protected flags before sourcing shared config
CUSTOM_PROTECTED=()
PUSH_ARGS=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --protected)
            CUSTOM_PROTECTED+=("$2")
            shift 2
            ;;
        *)
            PUSH_ARGS+=("$1")
            shift
            ;;
    esac
done

if [[ ${#CUSTOM_PROTECTED[@]} -gt 0 ]]; then
    GIT_PROTECTED_BRANCHES="${CUSTOM_PROTECTED[*]}"
    export GIT_PROTECTED_BRANCHES
fi

# shellcheck source=protected-branches.sh
source "$SCRIPT_DIR/protected-branches.sh"

# Resolve force-ness, the remote, and every target branch in ONE pass over
# PUSH_ARGS, so flags and positionals are classified against the same view
# of the argument list (GH-1049).
#
# Force spellings recognised:
#   --force / -f            long options match exactly, so the deliberately
#                           allowed --force-with-lease never matches on a
#                           substring
#   -uf / -fu / -vuf        single-dash tokens are decomposed letter-by-letter
#                           because POSIX bundling spells a force push without
#                           a lone -f (GH-1047)
#   origin +evil:main       a leading + on a refspec IS the force marker, and
#                           carries no force flag at all (GH-1049 gap 3)
#
# Positionals are counted rather than inferred from `remote`'s value: the old
# loop treated the second positional as the refspec only while `remote` still
# held its initial "origin", so pushing to a remote actually NAMED origin
# re-entered the first branch and overwrote `remote` with the branch. The
# target then fell back to HEAD, and a force push to `main` was never seen as
# targeting main at all (GH-1049 gap 1).
#
# A value-taking flag's value is skipped, otherwise it lands in the positional
# stream and shifts every index after it (GH-1049 gap 2). Optional-value flags
# (--force-with-lease) are absent by design — they are commonly spelled bare
# and consuming the next token would swallow the remote.
force=0
remote="origin"
target_branches=()
positional_index=0
skip_value=0
for arg in "${PUSH_ARGS[@]}"; do
    if [[ $skip_value -eq 1 ]]; then
        skip_value=0
        continue
    fi
    if [[ "$arg" == -* ]]; then
        case "$arg" in
            --force|-f)
                force=1
                ;;
            -o|--push-option|--receive-pack|--exec|--repo)
                skip_value=1
                ;;
            *)
                if [[ "$arg" =~ ^-[A-Za-z]+$ && "$arg" == *f* ]]; then
                    force=1
                fi
                ;;
        esac
        continue
    fi
    positional_index=$((positional_index + 1))
    if [[ $positional_index -eq 1 ]]; then
        remote="$arg"
        continue
    fi
    [[ "$arg" == +* ]] && force=1
    # Destination half of src:dst, minus the + force marker and minus a
    # refs/heads/ qualification — PROTECTED_BRANCHES holds short names, so a
    # fully-qualified ref compared as unprotected (GH-1049 gap 4).
    ref="${arg##*:}"
    ref="${ref#+}"
    ref="${ref#refs/heads/}"
    target_branches+=("$ref")
done

if [[ ${#target_branches[@]} -eq 0 ]]; then
    target_branches=("$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")")
fi

# The ref reported in every JSON payload: the first target, matching the
# single-refspec shape callers already parse.
target_branch="${target_branches[0]}"

# EVERY target is checked, not just the first — a push may carry several
# refspecs, and inspecting one let `origin feature +evil:develop` through.
if [[ $force -eq 1 ]]; then
    for branch in "${target_branches[@]}"; do
        if is_protected_branch "$branch"; then
            # JSON blocked result on stdout (success exit code so callers can
            # parse the structured payload), plus a human-readable warning on
            # stderr.
            echo "BLOCKED: --force push to protected branch '$branch' is not allowed." >&2
            echo "Use --force-with-lease on a feature branch instead." >&2
            printf '{"pushed":false,"ref":"%s","remote":"%s","blocked_reason":"protected_branch_force_push"}\n' \
                "$branch" "$remote"
            exit 2
        fi
    done
fi

# Run the push; capture stderr so we can re-emit it after the JSON payload.
push_stderr=$(mktemp)
trap 'rm -f "$push_stderr"' EXIT
if ! git push "${PUSH_ARGS[@]}" 2>"$push_stderr"; then
    rc=$?
    cat "$push_stderr" >&2
    printf '{"pushed":false,"ref":"%s","remote":"%s","blocked_reason":"push_failed"}\n' \
        "$target_branch" "$remote"
    exit "$rc"
fi
cat "$push_stderr" >&2

sha=$(git rev-parse --short HEAD 2>/dev/null || echo "")
tracking=$(git rev-parse --abbrev-ref --symbolic-full-name "@{u}" 2>/dev/null || echo "")

printf '{"pushed":true,"ref":"%s","remote":"%s","sha":"%s","tracking":"%s","ci_run_url":null}\n' \
    "$target_branch" "$remote" "$sha" "$tracking"
