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

# Detect force-push flags (--force-with-lease is intentionally allowed)
force=0
for arg in "${PUSH_ARGS[@]}"; do
    if [[ "$arg" == "--force" || "$arg" == "-f" ]]; then
        force=1
    fi
done

# Resolve the target branch and remote from the parsed PUSH_ARGS.
# Defaults match `git push` behavior: remote=origin, branch=HEAD.
target_branch=""
remote="origin"
for arg in "${PUSH_ARGS[@]}"; do
    if [[ "$arg" != -* ]]; then
        if [[ "$remote" == "origin" && -z "$target_branch" ]]; then
            # First positional is remote, second is refspec — but a single
            # positional is the remote when no refspec is given.
            remote="$arg"
        else
            target_branch="${arg##*:}"
        fi
    fi
done

if [[ -z "$target_branch" ]]; then
    target_branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
fi

if [[ $force -eq 1 ]] && is_protected_branch "$target_branch"; then
    # JSON blocked result on stdout (success exit code so callers can parse
    # the structured payload), plus a human-readable warning on stderr.
    echo "BLOCKED: --force push to protected branch '$target_branch' is not allowed." >&2
    echo "Use --force-with-lease on a feature branch instead." >&2
    printf '{"pushed":false,"ref":"%s","remote":"%s","blocked_reason":"protected_branch_force_push"}\n' \
        "$target_branch" "$remote"
    exit 2
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
