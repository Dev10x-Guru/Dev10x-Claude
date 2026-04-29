#!/usr/bin/env bash
# Run pre-PR quality checks. Exits on first failure.
# Skip if diff contains only non-Python files.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BASE_BRANCH="${1:-}"

if [ -z "$BASE_BRANCH" ]; then
    # shellcheck source=detect-base-branch.sh
    source "$SCRIPT_DIR/detect-base-branch.sh"
fi

# Check if any Python files changed
PYTHON_FILES=$(git diff "origin/$BASE_BRANCH..HEAD" --name-only | grep '\.py$' || true)
if [ -z "$PYTHON_FILES" ]; then
    echo "⏭️  No Python files changed — skipping pre-PR checks."
    exit 0
fi

echo "🔍 Running pre-PR checks..."

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
