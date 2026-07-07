#!/bin/sh
# post-checkout hook for git worktree setup (Node.js + Husky projects)
#
# Write to: .husky/post-checkout (tracked, survives yarn install)
# Do NOT write to .git/hooks/ — Husky overwrites it on every install.
#
# See post-checkout-python-uv.sh for full documentation of the
# dirty-file exclusion mechanism and copy_clean/copy_file/copy_folder helpers.

if [ "$1" = "0000000000000000000000000000000000000000" ]; then
    echo "New worktree detected. Running setup..."
    pwd
    ORIGINAL_REPO="/work/<org>/<project-name>"

    # ── Dirty-file exclusion ────────────────────────────────────────
    # GH-774: -uall lists untracked files individually so an untracked
    # sibling under .claude/Dev10x/ cannot collapse the dir into a single
    # `--exclude=Dev10x/` that drops the durable config.yaml from the copy.
    DIRTY_LIST=$(mktemp)
    git -C "$ORIGINAL_REPO" status --porcelain -uall 2>/dev/null | \
        sed 's/^...//' > "$DIRTY_LIST"

    copy_file() {
        src="$1"
        full="$ORIGINAL_REPO/$src"
        [ -f "$full" ] && ! grep -qFx "$src" "$DIRTY_LIST" && {
            mkdir -p "$(dirname "$src")"
            cp "$full" "$src" 2>/dev/null
        }
    }

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
    # GH-774: exclude ephemeral session.yaml (stale branch/tickets); it is
    # seeded fresh below. Durable Dev10x/config.yaml IS copied.
    copy_clean ".claude/" worktrees "Dev10x/session.yaml"

    if [ ! -d .claude ]; then
        mkdir -p .claude
        echo '{}' > .claude/settings.local.json
    fi

    # >>> Dev10x session-seed (GH-705, GH-774) >>>
    # The .claude/ copy brings the durable config.yaml across but EXCLUDES
    # the ephemeral session.yaml; seed regenerates a fresh session.yaml here
    # (and a default config.yaml when the source had none). Idempotent.
    # Best-effort — a missing dev10x CLI is non-fatal (work-on Phase 0 seeds).
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
    if command -v yarn >/dev/null; then
        if [ -f .yarnrc.yml ]; then
            yarn install --immutable
        else
            yarn install --frozen-lockfile
        fi
    fi
fi
