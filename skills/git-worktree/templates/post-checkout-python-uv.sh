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
    #
    # GH-774: -uall lists untracked files INDIVIDUALLY. Without it git
    # collapses a fully-untracked directory to a single `?? path/` entry;
    # for `.claude/Dev10x/` (when a sibling like auto-advance-records.md is
    # untracked-and-unignored) that collapsed entry becomes an
    # `--exclude=Dev10x/` pattern in copy_folder and drops the WHOLE dir —
    # including the durable config.yaml — from the worktree copy.
    DIRTY_LIST=$(mktemp)
    git -C "$ORIGINAL_REPO" status --porcelain -uall 2>/dev/null | \
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
    # GH-774: exclude the ephemeral session.yaml — it carries a stale
    # branch:/tickets: from the source worktree and must be seeded fresh
    # (below). The durable Dev10x/config.yaml IS copied (gitignored, so
    # absent from the dirty list).
    copy_clean ".claude/" worktrees "Dev10x/session.yaml"
    copy_clean ".idea/"

    # Ensure .claude/ exists even if source had nothing to copy
    if [ ! -d .claude ]; then
        mkdir -p .claude
        echo '{}' > .claude/settings.local.json
    fi

    # >>> Dev10x session-seed (GH-705, GH-774) >>>
    # Provision the split config. The .claude/ copy above brings the durable
    # config.yaml (friction_level, active_modes) across from the source
    # worktree but EXCLUDES the ephemeral session.yaml, so seed regenerates a
    # fresh session.yaml here (and provisions a default config.yaml when the
    # source had none). Idempotent — seed leaves any present file untouched.
    # Best-effort: a missing dev10x CLI is non-fatal (work-on Phase 0 seeds
    # later).
    if [ ! -f .claude/Dev10x/session.yaml ] || [ ! -f .claude/Dev10x/config.yaml ]; then
        if command -v dev10x >/dev/null 2>&1; then
            dev10x session seed || true
        elif command -v uvx >/dev/null 2>&1; then
            uvx dev10x session seed || true
        fi
    fi
    # <<< Dev10x session-seed (GH-705, GH-774) <<<

    rm -f "$DIRTY_LIST"

    # ── Post-copy setup ─────────────────────────────────────────────
    command -v uv >/dev/null && uv sync
fi
