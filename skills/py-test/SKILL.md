---
name: Dev10x:py-test
description: >
  Run pytest with coverage enforcement. Verifies test suite passes
  with 100% coverage for new code. Reports pass/fail status and
  coverage percentage with full output only on failures.
  TRIGGER when: code changes need test verification before committing,
  explicitly asked to run tests, or creating a pull request.
  DO NOT TRIGGER when: no Python code changed, or running non-pytest
  test frameworks.
user-invocable: true
invocation-name: Dev10x:py-test
allowed-tools:
  - mcp__plugin_Dev10x_cli__run_tests
  - Bash(pytest:*)
  - Bash(uv:*)
---

# Python Test Verifier

## Overview

Run the test suite and verify all tests pass with 100% coverage
for new code. Reports concise summaries — detailed output only on
failures.

## When to Use

- Code changes need test verification before committing
- Before creating a pull request
- Explicitly asked to run tests or check coverage
- After implementing fixes to verify they work

## Workflow

### Step 1: Run Tests

**Preferred — MCP tool** (works in every session, including
worktrees where `pytest` is not on PATH and the Bash hook blocks
every direct invocation form, GH-238):

```
mcp__plugin_Dev10x_cli__run_tests()
```

Pass extra pytest args via the `args` parameter, e.g.
`args=["src/dev10x/runner/"]` or `args=["-k", "name"]`. The tool
returns a structured payload: `returncode`, `summary`, `passed`,
`failed`, `skipped`, `coverage_percent`, `failed_tests`,
`missing_coverage`, `stdout`, `stderr`. The subprocess is
launched from the MCP server so the PreToolUse hook does not
apply.

**Fallback — Bash** (only when the MCP server is unavailable):

```bash
pytest --cov --cov-report=term-missing
```

Inside a worktree (`.git` is a file, not a directory), prefix
with `uv run`:

```bash
uv run pytest --cov --cov-report=term-missing
```

### Step 2: Parse Results

Extract:
- Total tests run
- Tests passed/failed
- Coverage percentage
- Uncovered lines (if any)

### Step 3: Report Summary

**If all tests pass:**
```
Tests: 150 passed
Coverage: 100%
```

**If tests fail:**
```
Tests: 148 passed, 2 failed

Failed tests:
1. test_calculate_total - AssertionError: expected 100, got 99
2. test_validate_input - ValueError: invalid input

Coverage: 98% (missing: src/service.py:45-48)
```

## Coverage Enforcement

If coverage is below 100% for files changed in the current branch,
the branch introduced the regression. Report the failure and fix
the gap — do not ask the user whether to proceed with coverage
below 100%.

## Important Notes

- Always run tests before committing
- Ensure 100% coverage for new code
- Fix failing tests before creating PR
- Use `-v` flag for verbose output when debugging
