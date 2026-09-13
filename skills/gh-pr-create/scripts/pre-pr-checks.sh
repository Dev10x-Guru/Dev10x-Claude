#!/usr/bin/env bash
# Run pre-PR quality checks. Exits on first failure.
# Skip if diff contains only non-Python files.
#
# When the project ships a .pre-commit-config.yaml, defer entirely
# to `pre-commit run` — projects own their own check suite (GH-38).
# Otherwise fall back to the bundled ruff/mypy invocations.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BASE_BRANCH="${1:-}"

if [ -z "$BASE_BRANCH" ]; then
    # shellcheck source=detect-base-branch.sh
    source "$SCRIPT_DIR/detect-base-branch.sh"
fi

# Every use below qualifies the branch as origin/$BASE_BRANCH, so a caller
# passing the already-qualified "origin/develop" produced origin/origin/develop
# and a failure that read as a git problem rather than an argument one
# (GH-1285). Both spellings are accepted.
BASE_BRANCH="${BASE_BRANCH#origin/}"

# Prefer project pre-commit configuration when present (GH-38).
# Walks up to the repo root before checking so the script works
# from any subdirectory.
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
if [ -f "$REPO_ROOT/.pre-commit-config.yaml" ] && command -v pre-commit >/dev/null 2>&1; then
    echo "🔍 Running project pre-commit hooks (from-ref=origin/$BASE_BRANCH)..."
    cd "$REPO_ROOT"
    pre-commit run --from-ref "origin/$BASE_BRANCH" --to-ref HEAD || {
        echo "❌ pre-commit checks failed. Fix issues and re-run."
        exit 1
    }
    echo "✅ Pre-commit checks passed."
    echo "ℹ️  Tests run separately via Skill(Dev10x:py-test) in shipping pipeline."
    exit 0
fi

# Check if any Python files changed
PYTHON_FILES=$(git diff "origin/$BASE_BRANCH..HEAD" --name-only | grep '\.py$' || true)
if [ -z "$PYTHON_FILES" ]; then
    echo "⏭️  No Python files changed — skipping pre-PR checks."
    exit 0
fi

echo "🔍 Running bundled pre-PR checks (no project pre-commit config found)..."

echo "  [1/3] ruff check..."
ruff check . || { echo "❌ Ruff check failed. Fix linting issues."; exit 1; }

echo "  [2/3] ruff format check..."
ruff format --check . || { echo "❌ Formatting check failed. Run: ruff format ."; exit 1; }

echo "  [3/3] MyPy type check..."
# Match the [tool.mypy] mypy_path = "src" config in pyproject.toml.
# Running `mypy .` tripped on hyphenated test directories (e.g.
# tests/skills/gh-pr-monitor) which are not valid package names.
mypy src || { echo "❌ MyPy check failed. Fix type errors."; exit 1; }

echo "✅ All pre-PR static checks passed!"
echo "ℹ️  Tests are run separately via Skill(Dev10x:py-test) in the shipping pipeline."
