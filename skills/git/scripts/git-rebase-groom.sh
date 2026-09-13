#!/usr/bin/env bash
# Grooming rebase wrapper — uses git-seq-editor.sh as GIT_SEQUENCE_EDITOR.
#
# Usage:
#   git-rebase-groom.sh <seq-file> <base-ref>
#
# Before calling: write rebase todo to <seq-file>

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SEQ_EDITOR="$SCRIPT_DIR/git-seq-editor.sh"

if [[ $# -lt 2 ]]; then
    echo "Usage: git-rebase-groom.sh <seq-file> <base-ref>" >&2
    exit 1
fi

GROOM_SEQ_FILE="$1"
shift
base_ref="$1"
shift

if [[ ! -f "$GROOM_SEQ_FILE" ]]; then
    echo "ERROR: $GROOM_SEQ_FILE not found." >&2
    echo "Use the Write tool to write the rebase todo to $GROOM_SEQ_FILE first." >&2
    exit 1
fi

if [[ ! -x "$SEQ_EDITOR" ]]; then
    echo "ERROR: $SEQ_EDITOR not found or not executable." >&2
    exit 1
fi

# Stale-base guard (GH-1270).
#
# A LOCAL `<base-ref>` hides every merge landed since it was fetched: the
# rebase replays onto the old tip and still reports success. Refuse early
# and name the remote-tracking ref instead.
if [[ "$base_ref" != */* ]] && git rev-parse --quiet --verify "refs/heads/$base_ref" >/dev/null; then
    base_remote="$(git config --get "branch.$base_ref.remote" || echo origin)"
    if ! git fetch --quiet "$base_remote" "$base_ref" 2>/dev/null; then
        echo "WARNING: could not fetch $base_remote/$base_ref — comparing" >&2
        echo "against the last known remote tip, which may itself be stale." >&2
        base_tip="$(git rev-parse --quiet --verify "refs/remotes/$base_remote/$base_ref" || true)"
    else
        base_tip="$(git rev-parse --quiet --verify FETCH_HEAD || true)"
    fi

    if [[ -n "$base_tip" ]] && ! git merge-base --is-ancestor "$base_tip" "$base_ref"; then
        echo "ERROR: refusing to groom — local '$base_ref' is behind" >&2
        echo "'$base_remote/$base_ref' and is missing:" >&2
        git log --oneline "$base_ref..$base_tip" >&2
        echo "" >&2
        echo "Groom against '$base_remote/$base_ref' instead (GH-1270)." >&2
        exit 1
    fi
fi

# Base-moved guard (GH-1103).
#
# `git rebase -i <base>` drops any commit whose patch the base already
# contains — the usual case being one's own PR merged by rebase, so the
# branch's work is in <base> under a different SHA. The todo's `pick`
# then vanishes and a trailing `fixup` lands on whatever commit sits at
# the base tip, fusing the fix into a foreign commit and losing the
# feature commit. Refuse instead: a groom that cannot replay its own
# picks has nothing left to groom.
survivors="$(git rev-list --cherry-pick --right-only --no-merges "$base_ref...HEAD")"

dropped=""
while read -r action sha _rest; do
    case "$action" in
        pick|p|reword|r|edit|e) ;;
        *) continue ;;
    esac
    [[ -n "$sha" ]] || continue
    full_sha="$(git rev-parse --quiet --verify "${sha}^{commit}")" || continue
    if [[ "$survivors" != *"$full_sha"* ]]; then
        dropped+="  $action $sha"$'\n'
    fi
done < "$GROOM_SEQ_FILE"

if [[ -n "$dropped" ]]; then
    echo "ERROR: refusing to groom — $base_ref already contains these commits:" >&2
    printf '%s' "$dropped" >&2
    echo "" >&2
    echo "The rebase would drop them as already-applied and replay any" >&2
    echo "fixup onto a $base_ref commit instead (GH-1103). This usually" >&2
    echo "means the branch's PR was merged by rebase and the branch is" >&2
    echo "now obsolete." >&2
    echo "" >&2
    echo "Start a fresh branch from $base_ref and re-apply the change there." >&2
    exit 1
fi

export GROOM_SEQ_FILE
# rerere replays cached resolutions from a gitdir-shared rr-cache that
# sibling worktrees also write. A groom's conflict resolution must be
# decided from the commits in front of it, never auto-filled from that
# cache — and an agent cannot disable it per-invocation, because the
# `git -c ...` prefix breaks allow-rule matching (GH-1103).
GIT_SEQUENCE_EDITOR="$SEQ_EDITOR" \
GIT_EDITOR="true" \
    git -c rerere.enabled=false rebase -i "$base_ref" "$@" || rc=$?
rc=${rc:-0}

if [[ $rc -eq 0 ]]; then
    exit 0
fi

if [[ -d "$(git rev-parse --git-dir)/rebase-merge" ]]; then
    conflicted="$(git diff --name-only --diff-filter=U | tr '\n' ',')"
    rebase_head="$(git rev-parse --short REBASE_HEAD 2>/dev/null || echo unknown)"
    if [[ -n "${conflicted//,/}" ]]; then
        echo "CONFLICT_DETECTED"
        echo "conflicted_files=$conflicted"
        echo "rebase_head=$rebase_head"
        echo "hint=Resolve conflicts, git add, then git rebase --continue"
        exit 1
    fi
    # Stopped mid-rebase with no unmerged paths — an `edit` stop, or
    # conflicts already staged. Reporting this as a conflict with an
    # empty file list sent callers chasing a conflict git did not see,
    # and the "resolve, then --continue" hint completed the damage
    # (GH-1103).
    echo "REBASE_PAUSED"
    echo "conflicted_files="
    echo "rebase_head=$rebase_head"
    echo "hint=Rebase stopped with no unmerged paths — inspect git status, then git rebase --continue (or --abort)"
    exit 1
fi

exit "$rc"
