# CI Failure Patterns and Fixes

This reference documents common CI failure patterns and how to fix them.

## Pre-commit Hook Failures

### Ruff / Black / isort

**Pattern:**
```
ruff....................................................................Failed
- src/app/service.py:45:80: E501 line too long (85 > 79 characters)
```

**Fix:**
- Run `ruff format .` and `ruff check --fix .` to auto-fix
- For line length issues, break long lines or use implicit string concatenation

### mypy

**Pattern:**
```
mypy....................................................................Failed
src/app/service.py:10: error: Argument 1 has incompatible type "str"; expected "int"
```

**Fix:**
- Add proper type annotations
- Fix type mismatches
- Use `# type: ignore[error-code]` only as last resort with explanation

### Flake8

**Pattern:**
```
Flake8..................................................................Failed
src/app/service.py:15:1: F401 'unused_import' imported but unused
```

**Fix:**
- Remove unused imports
- Use `# noqa: F401` only if import is needed for re-export

### gitlint

**Pattern:**
```
gitlint.................................................................Failed
1: T1 Title exceeds max length (75>72)
```

**Fix:**
- Shorten commit title to ≤72 characters
- Amend commit: `git commit --amend`

## pytest Failures

### Test Failures

**Pattern:**
```
FAILED src/tests/test_service.py::TestClass::test_method
AssertionError: assert 100 == 200
```

**Fix:**
- Read the test to understand what's being tested
- Check if the fix broke expected behavior
- Update test if expectations changed (rare)
- Fix the code if test is correct

### Import Errors

**Pattern:**
```
ImportError: cannot import name 'SomeClass' from 'module'
```

**Fix:**
- Check if file was renamed/moved
- Update import statements
- Ensure `__init__.py` exports are correct

### Database Errors

**Pattern:**
```
django.db.utils.IntegrityError: duplicate key value violates unique constraint
```

**Fix:**
- Check if test creates duplicate data
- Use unique values in test data
- Clean up test data in teardown

## Docker Build Failures

**Pattern:**
```
ERROR: failed to solve: process "/bin/sh -c pip install -r requirements.txt" did not complete successfully
```

**Fix:**
- Check if new dependencies were added
- Ensure requirements file is valid
- Check for dependency conflicts

## Merge Conflicts

**Pattern:**
```
This branch has conflicts that must be resolved
```
or `gh pr view` reports `mergeable: CONFLICTING`.

**Fix:**
- Fetch latest base: `git fetch origin {base_branch}`
- Rebase: `git rebase origin/{base_branch}`
- Resolve conflicts manually if auto-rebase fails
- Force-push: `git push --force-with-lease origin {branch}`

## Git History Linting Failures

### Fixup Commits Blocking Merge

**Pattern:**
```
git-history-linting / Block fixup commit merge ............ Failed
```

The `git-history-linting` CI check blocks merging when the branch
contains `fixup!` commits. These commits are created during review
comment fixes and must be squashed into their target commits before
merge.

**Detection:**
```bash
${CLAUDE_PLUGIN_ROOT}/skills/gh-pr-monitor/scripts/detect-fixup-commits.sh \
  --pr {pr_number} --repo {repo}
```

**Fix:**
1. Get the base branch from the PR
2. Delegate squash + force-push to `Skill(Dev10x:git-groom)` — it
   runs the autosquash rebase and pushes through `Skill(Dev10x:git)`,
   which enforces protected-branch checks. Do NOT call
   `git autosquash-{base}` or `git push --force-with-lease` directly
   from this skill (that bypasses the wrapper guardrails — see
   Skill Routing Enforcement in `skills/work-on/instructions.md`).
3. Wait 60 seconds for GitHub to register new check suites
4. Resume the Phase 1 CI monitoring loop

**Note:** `Dev10x:git-groom` invokes the `git autosquash-{base}`
alias under the hood — a non-interactive rebase with `--autosquash`
that matches `fixup!` commit prefixes to their target commits and
squashes them automatically. After the force-push, all previous CI
results are invalidated — the agent must re-monitor from scratch.

## Coverage Failures

**Pattern:**
```
FAILED: Coverage is 98.5%, required 100%
```

**Fix:**
- Add tests for uncovered lines
- Check coverage report for which lines need testing
- Review which branches need test cases
