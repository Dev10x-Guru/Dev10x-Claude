#!/bin/sh
# post-checkout hook for git worktree setup (Python/uv projects)
#
# Goals:
# - Bootstrap a new worktree with config and secrets from the source repo
# - Skip files with uncommitted changes (modified/staged/untracked) to
#   avoid carrying over work-in-progress that creates confusion
# - Gitignored files (.env, settings.local.json) ARE still copied —
#   they are local config, not WIP
# - Install dependencies so the worktree is ready to use
#
# How it works:
# 1. Build a list of dirty files via `git status --porcelain` (once)
# 2. copy_clean <path> [excludes] auto-detects file vs directory and
#    delegates to copy_file or copy_folder, both of which skip dirty files
# 3. Add new entries to the "FILES TO COPY" section — one line each
#
# The all-zeros SHA1 ($1) identifies a new worktree creation event.
# Regular branch checkouts pass real SHA1s and skip this block.

if [ "$1" = "0000000000000000000000000000000000000000" ]; then
    echo "New worktree detected. Running setup..."
    pwd
    ORIGINAL_REPO="/work/<org>/<project-name>"

    # ── Dirty-file exclusion ────────────────────────────────────────
    # Build the full list of dirty files once for the entire repo.
    # git status --porcelain output: 2-char status + space + path
    # sed strips the 3-char prefix, leaving bare repo-relative paths.
    # Gitignored files do NOT appear, so they pass through to copy.
    DIRTY_LIST=$(mktemp)
    git -C "$ORIGINAL_REPO" status --porcelain 2>/dev/null | \
        sed 's/^...//' > "$DIRTY_LIST"

    # copy_file <path>
    # Copies a single file from ORIGINAL_REPO, skipping if it has
    # uncommitted changes. Creates parent directories as needed.
    copy_file() {
        src="$1"
        full="$ORIGINAL_REPO/$src"
        [ -f "$full" ] && ! grep -qFx "$src" "$DIRTY_LIST" && {
            mkdir -p "$(dirname "$src")"
            cp "$full" "$src" 2>/dev/null
        }
    }

    # copy_folder <path> [extra-rsync-excludes...]
    # Rsync a directory from ORIGINAL_REPO, excluding files with
    # uncommitted changes. Extra --exclude patterns (e.g. "worktrees")
    # can be passed as additional arguments.
    copy_folder() {
        src="$1"; shift
        full="$ORIGINAL_REPO/$src"
        [ -d "$full" ] || return 0
        dir_excl=$(mktemp)
        grep "^${src}" "$DIRTY_LIST" | sed "s|^${src}||" > "$dir_excl"
        extra=""
        for pattern in "$@"; do extra="$extra --exclude=$pattern"; done
        eval rsync -a --exclude-from="$dir_excl" "$extra" \
            "\"$full/\"" "\"${src}/\"" 2>/dev/null
        rm -f "$dir_excl"
    }

    # copy_clean <path> [extra-rsync-excludes...]
    # Auto-detects file vs directory and delegates accordingly.
    copy_clean() {
        src="$1"
        full="$ORIGINAL_REPO/$src"
        if [ -d "$full" ]; then
            copy_folder "$@"
        else
            copy_file "$src"
        fi
    }

    # ── FILES TO COPY (add new entries here) ────────────────────────
    copy_clean ".env"
    copy_clean ".env.supabase"
    copy_clean "development.secrets.env"
    copy_clean ".claude/" worktrees          # exclude worktrees subdir
    copy_clean ".idea/"

    # Ensure .claude/ exists even if source had nothing to copy
    if [ ! -d .claude ]; then
        mkdir -p .claude
        echo '{}' > .claude/settings.local.json
    fi

    # >>> Dev10x session-seed (GH-705) >>>
    # session.yaml is gitignored, so `git worktree add` never brings it
    # across. The .claude/ copy above carries it when the source worktree
    # has one; seed a default when it does not, so work-on / verify-acc-dod
    # have a config from the first session in this worktree. Best-effort —
    # a missing dev10x CLI is non-fatal (work-on Phase 0 seeds later).
    if [ ! -f .claude/Dev10x/session.yaml ]; then
        if command -v dev10x >/dev/null 2>&1; then
            dev10x session seed || true
        elif command -v uvx >/dev/null 2>&1; then
            uvx dev10x session seed || true
        fi
    fi
    # <<< Dev10x session-seed (GH-705) <<<

    rm -f "$DIRTY_LIST"

    # ── Post-copy setup ─────────────────────────────────────────────
    command -v uv >/dev/null && uv sync
fi
