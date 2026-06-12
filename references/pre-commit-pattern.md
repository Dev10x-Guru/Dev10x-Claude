# Pre-commit Configuration Pattern

When a skill uses linting or code quality checks, delegate to
`.pre-commit-config.yaml` instead of invoking individual linters inline.

## Why Pre-commit

Individual linter invocations in skills create per-invocation approval
friction: each `Bash(ruff check:*)`, `Bash(black --check:*)`, or
`Bash(mypy:*)` call requires user permission approval. Pre-commit
consolidates these under a single allow-rule.

## Pattern

**Check if pre-commit config exists:**

```python
if Path(".pre-commit-config.yaml").is_file():
    # Use pre-commit
    result = subprocess.run(["pre-commit", "run", "--files", file])
else:
    # Emit guidance, skip lint stage
    emit_finding("setup-guidance", 
                 "No .pre-commit-config.yaml — run 'pre-commit install'")
    return
```

## Fallback Behavior

**DO NOT fall back to inline linters** when `.pre-commit-config.yaml`
is missing. Instead:

1. Emit a single setup-guidance finding with install instructions
2. Skip the automated-check stage
3. Allow manual verification as an optional manual step

This prevents per-invocation permission friction and encourages users
to set up pre-commit once rather than repeatedly approving inline
linter calls.

## Skill Integration

Skills that perform code reviews (`review`, `review-fix`, `diag-friction`)
should use this pattern:

```markdown
**Step 3: Run pre-commit checks**

If the repo has `.pre-commit-config.yaml`, run `pre-commit run --files`
to check style and formatting. If missing, emit a guidance finding with
setup instructions and skip this stage.
```

## Example from review Skill

The `review` skill implements this as:

1. Check for `.pre-commit-config.yaml`
2. If exists: `pre-commit run --files <changed-files>`
3. If missing: Emit "No pre-commit config" finding, skip lint stage
4. Parse output for style violations
5. Surface findings as part of review feedback

This prevents friction while standardizing linting behavior across all
skills.
