#!/usr/bin/env bash
# Detect UV installation, available package managers, and audit Python scripts
# for legacy shebangs. Structured key=value output for machine parsing.
#
# Exit codes:
#   0 — UV installed, no legacy scripts found
#   1 — UV not installed
#   2 — UV installed but legacy scripts need migration
set -euo pipefail

# ── UV Status ───────────────────────────────────────────────────
echo "=== UV_STATUS ==="

if command -v uv &>/dev/null; then
    UV_PATH="$(command -v uv)"
    UV_VERSION="$(uv --version 2>/dev/null | head -1)"
    echo "uv_installed=true"
    echo "uv_path=$UV_PATH"
    echo "uv_version=$UV_VERSION"
else
    echo "uv_installed=false"
    echo "uv_path="
    echo "uv_version="
fi

# ── Package Managers ────────────────────────────────────────────
echo ""
echo "=== PACKAGE_MANAGERS ==="

for mgr in brew apt pipx dnf curl wget; do
    if command -v "$mgr" &>/dev/null; then
        echo "${mgr}=available"
    else
        echo "${mgr}=missing"
    fi
done

# ── Script Audit ────────────────────────────────────────────────
echo ""
echo "=== SCRIPT_AUDIT ==="

SKILLS_DIR="${HOME}/.claude/skills"
TOOLS_DIR="${HOME}/.claude/tools"
WRONG_SHEBANG_COUNT=0
NOT_EXECUTABLE_COUNT=0
TOTAL_PY=0

scan_directory() {
    local dir="$1"
    if [[ ! -d "$dir" ]]; then
        return
    fi
    while IFS= read -r -d '' pyfile; do
        TOTAL_PY=$((TOTAL_PY + 1))
        local relpath="${pyfile#"$HOME"/.claude/}"
        local shebang
        shebang="$(head -1 "$pyfile" 2>/dev/null || true)"

        local issues=""

        if [[ "$shebang" == "#!/usr/bin/env python3"* ]] || \
           [[ "$shebang" == "#!/usr/bin/python3"* ]] || \
           [[ "$shebang" == "#!/usr/bin/env python"* ]] && \
           [[ "$shebang" != *"uv run"* ]]; then
            issues="WRONG_SHEBANG"
            WRONG_SHEBANG_COUNT=$((WRONG_SHEBANG_COUNT + 1))
        fi

        if [[ ! -x "$pyfile" ]]; then
            if [[ -n "$issues" ]]; then
                issues="${issues},NOT_EXECUTABLE"
            else
                issues="NOT_EXECUTABLE"
            fi
            NOT_EXECUTABLE_COUNT=$((NOT_EXECUTABLE_COUNT + 1))
        fi

        if [[ -n "$issues" ]]; then
            echo "file=$relpath issues=$issues shebang=$shebang"
        fi
    done < <(find "$dir" -name '*.py' -type f -print0 2>/dev/null)
}

scan_directory "$SKILLS_DIR"
scan_directory "$TOOLS_DIR"

echo ""
echo "total_py_files=$TOTAL_PY"
echo "wrong_shebang_count=$WRONG_SHEBANG_COUNT"
echo "not_executable_count=$NOT_EXECUTABLE_COUNT"

# ── Exit Code ───────────────────────────────────────────────────
if ! command -v uv &>/dev/null; then
    exit 1
fi

if [[ $WRONG_SHEBANG_COUNT -gt 0 ]]; then
    exit 2
fi

exit 0
