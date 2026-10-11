#!/usr/bin/env bash
# Classify a pull request's changed files into the CI legs that must run
# (GH-1298).
#
# The path lists started as the workflow-level `paths:` filters that
# `pytest-hooks.yml`, `pytest-servers.yml` and `pytest-coverage-floors.yml`
# carried before they were folded into `ci-gate.yml`. Moving the filter
# from the event to the job is what lets a filtered-out leg report
# `skipped` instead of not reporting at all.
#
# The hook and server legs no longer enumerate `src/` packages (GH-1595).
# Every `hooks/scripts/*.py` entry point and every `servers/*.py` server
# imports `dev10x`, and that import closure reaches nearly the whole
# package. A hand-kept glob fell behind the ADR-0034 Stage A moves and
# silently skipped both suites on PRs that changed code they import, so
# any change under `src/dev10x/` now selects both.
# `tests/test_classify_ci_changes.py` pins this against the real closure.
set -euo pipefail

emit() {
    printf '%s=%s\n' "$1" "$2" >>"${GITHUB_OUTPUT}"
    printf '%s=%s\n' "$1" "$2"
}

run_everything() {
    emit hooks true
    emit servers true
    emit floors true
    exit 0
}

if [ "${GITHUB_EVENT_NAME:-}" != "pull_request" ]; then
    # A push has no pull-request diff base to classify against, and
    # develop is the branch these floors protect.
    run_everything
fi

if ! git cat-file -e "${BASE_SHA}^{commit}" 2>/dev/null ||
    ! git cat-file -e "${HEAD_SHA}^{commit}" 2>/dev/null; then
    echo "cannot resolve ${BASE_SHA}...${HEAD_SHA}; running every leg"
    run_everything
fi

changed=$(git diff --name-only "${BASE_SHA}...${HEAD_SHA}")
printf 'changed files:\n%s\n' "${changed}"

matches() {
    printf '%s\n' "${changed}" | grep -Eq "$1"
}

# A change to the gate's own wiring re-runs every leg it decides.
self='^\.github/workflows/ci-gate\.yml$|^\.github/scripts/(classify-ci-changes|ci-gate-verdict)\.sh$'

# Any package module: the hook and server import closures cover it.
src='^src/dev10x/'

if matches "^hooks/|^tests/hooks/|${src}|^pyproject\.toml\$|${self}"; then
    emit hooks true
else
    emit hooks false
fi

servers='^servers/'
servers+="|${src}"
servers+='|^tests/(mcp|audit|db|git|github|monitor|permission|plan|release|skill_index|utilities)/'
servers+='|^tests/test_subprocess_utils\.py$'
servers+='|^pyproject\.toml$'

if matches "${servers}|${self}"; then
    emit servers true
else
    emit servers false
fi

if matches "^src/dev10x/|^tests/|^pyproject\.toml\$|${self}"; then
    emit floors true
else
    emit floors false
fi
