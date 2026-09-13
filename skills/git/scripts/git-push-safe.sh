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
#
# `--force-with-lease` is tracked separately as `lease`, not folded into
# `force`: it stays ALLOWED on every branch, and only feeds the
# base-ancestry gate below (GH-1270).
force=0
lease=0
remote="origin"
target_branches=()
source_refs=()
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
            --force-with-lease|--force-with-lease=*|--force-if-includes)
                lease=1
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
    # Source half of src:dst — what was actually pushed, and therefore
    # what the reported sha must describe. Bare `branch` is its own
    # source; a delete refspec (`:dst`) has none (GH-1220).
    src="${arg%%:*}"
    src="${src#+}"
    src="${src#refs/heads/}"
    source_refs+=("$src")
done

if [[ ${#target_branches[@]} -eq 0 ]]; then
    # GH-1285: `--abbrev-ref` answers "HEAD" on a detached HEAD and the
    # fallback answered "" when it failed outright, so every payload could
    # carry a `ref` that names nothing.
    head_ref=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
    if [[ -z "$head_ref" || "$head_ref" == "HEAD" ]]; then
        detached_sha=$(git rev-parse --short HEAD 2>/dev/null || echo "")
        if [[ -z "$detached_sha" ]]; then
            echo "BLOCKED: cannot resolve HEAD — no branch and no commit." >&2
            echo "Name the refspec explicitly, e.g. push_safe(args=[\"-u\",\"origin\",\"<branch>\"])." >&2
            printf '{"pushed":false,"ref":"","remote":"%s","blocked_reason":"unresolvable_head"}\n' \
                "$remote"
            exit 2
        fi
        echo "BLOCKED: HEAD is detached at $detached_sha — refusing to guess a target branch." >&2
        echo "Check out a branch, or name the refspec explicitly." >&2
        printf '{"pushed":false,"ref":"%s","remote":"%s","blocked_reason":"detached_head"}\n' \
            "$detached_sha" "$remote"
        exit 2
    fi
    target_branches=("$head_ref")
    source_refs=("HEAD")
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

# Base-ancestry gate for a leased force-push to a protected branch (GH-1270).
#
# A lease only compares the remote against the LOCAL remote-tracking ref,
# so a stale one leases against its own copy and drops every merge landed
# since. Bare `--force` never reaches here — the block above refused it —
# so this gate covers the spelling allowed everywhere else.
if [[ $lease -eq 1 ]]; then
    for index in "${!target_branches[@]}"; do
        branch="${target_branches[$index]}"
        is_protected_branch "$branch" || continue
        # A delete refspec (`:dst`) pushes no commit, so there is no
        # source ref to compare the remote tip against.
        src="${source_refs[$index]}"
        [[ -n "$src" ]] || continue

        if ! git fetch --quiet "$remote" "$branch" 2>/dev/null; then
            # A branch absent from the remote has nothing to lose;
            # anything else means the check could not run, and an
            # unverifiable force-push is what this gate exists to stop.
            # --exit-code separates the two (2 = no matching refs, 128 =
            # unreachable); empty stdout does not.
            ls_remote_rc=0
            git ls-remote --exit-code --heads "$remote" "$branch" >/dev/null 2>&1 ||
                ls_remote_rc=$?
            if [[ $ls_remote_rc -eq 2 ]]; then
                continue
            fi
            echo "BLOCKED: cannot verify '$remote/$branch' before a forced push." >&2
            echo "Fetch failed, so the commits this push would drop are unknown." >&2
            printf '{"pushed":false,"ref":"%s","remote":"%s","blocked_reason":"base_fetch_failed"}\n' \
                "$branch" "$remote"
            exit 2
        fi

        remote_tip=$(git rev-parse --quiet --verify FETCH_HEAD) || continue
        if ! git merge-base --is-ancestor "$remote_tip" "$src"; then
            echo "BLOCKED: '$src' does not contain the current tip of '$remote/$branch'." >&2
            echo "Forcing this push would drop these commits:" >&2
            git log --oneline "$src..$remote_tip" >&2
            echo "" >&2
            echo "Rebase onto '$remote/$branch' first, then push again." >&2
            printf '{"pushed":false,"ref":"%s","remote":"%s","blocked_reason":"base_behind_remote"}\n' \
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

# Report the ref that was PUSHED, not whatever HEAD happens to be here
# (GH-1220). Sibling worktrees share one object store and one set of
# refs, so `git push origin <branch>` succeeds from any of them — while
# `rev-parse HEAD` answers for the checkout the process happens to be
# standing in. After an EnterWorktree the MCP daemon's inherited CWD is
# a DIFFERENT worktree, so the push landed correctly and the payload
# described another branch's commit. Resolving the source refspec makes
# the answer independent of where the script ran.
source_ref="${source_refs[0]}"
if [[ -n "$source_ref" ]]; then
    sha=$(git rev-parse --short "$source_ref" 2>/dev/null || echo "")
    upstream_ref="${source_ref}@{u}"
    [[ "$source_ref" == "HEAD" ]] && upstream_ref="@{u}"
    tracking=$(git rev-parse --abbrev-ref --symbolic-full-name "$upstream_ref" 2>/dev/null || echo "")
else
    # A delete refspec (`git push origin :old-branch`) pushes no commit.
    sha=""
    tracking=""
fi

printf '{"pushed":true,"ref":"%s","remote":"%s","sha":"%s","tracking":"%s","ci_run_url":null}\n' \
    "$target_branch" "$remote" "$sha" "$tracking"
