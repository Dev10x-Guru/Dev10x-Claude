#!/bin/sh
# post-checkout hook for git worktree setup (Node.js without Husky)
#
# Write to: .git/hooks/post-checkout
# Make executable: chmod +x .git/hooks/post-checkout
#
# See post-checkout-python-uv.sh for full documentation of the
# dirty-file exclusion mechanism and copy_clean/copy_file/copy_folder helpers.

if [ "$1" = "0000000000000000000000000000000000000000" ]; then
    echo "New worktree detected. Running setup..."
    pwd
    ORIGINAL_REPO="/work/<org>/<project-name>"

    # ── Dirty-file exclusion ────────────────────────────────────────
    DIRTY_LIST=$(mktemp)
    git -C "$ORIGINAL_REPO" status --porcelain 2>/dev/null | \
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
        eval rsync -a --exclude-from="$dir_excl" $extra \
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
    copy_clean ".claude/" worktrees

    if [ ! -d .claude ]; then
        mkdir -p .claude
        echo '{}' > .claude/settings.local.json
    fi

    rm -f "$DIRTY_LIST"

    # ── Post-copy setup ─────────────────────────────────────────────
    if command -v yarn >/dev/null; then
        if [ -f .yarnrc.yml ]; then
            yarn install --immutable
        else
            yarn install --frozen-lockfile
        fi
    elif command -v npm >/dev/null; then
        npm ci
    fi
fi
