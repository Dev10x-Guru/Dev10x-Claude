# Permission Rule Generalization Patterns

How to transform over-specific allow-rules into reusable, generalized
patterns that prevent later friction.

## Three Failure Modes

| Failure Mode | Example | Impact |
|---|---|---|
| **Over-broad** | `git.*` when `git commit` was needed | Grants unneeded permissions; reviewers reject |
| **Over-narrow** | `git config user.*` only, missing `git commit` | Incomplete; fails at runtime |
| **Too-literal** | Exact file path instead of glob pattern | Breaks when repo path or file structure changes |

## Generalization Process

When a skill suggests an allow-rule for a specific operation (e.g.,
`git commit` for a particular user), apply these transformations:

1. **Remove hardcoded paths** — Replace `/home/user/project` with glob
   patterns or `{CLAUDE_PLUGIN_ROOT}` markers
2. **Expand to related operations** — If `git commit` is needed, consider
   whether `git rebase`, `git push` should also be allowed
3. **Document scope** — Add a comment explaining why the pattern size
   is necessary (e.g., "git:* covers commit, rebase, push for atomic
   refactoring")
4. **Test against related commands** — Verify the rule allows intended
   calls and blocks unrelated ones (e.g., `git rm` if not needed)

## Examples

### Example 1: Git Permission Generalization

**Over-narrow (fails at runtime):**
```
Bash(git commit:*)
```
Missing: `git push`, `git rebase` needed for multi-commit workflows.

**Generalized (working):**
```
Bash(git:--commit|--push|--rebase)
```

### Example 2: Python Linter Generalization

**Over-broad (rejected by reviewers):**
```
Bash(ruff:*)
```
Grants all ruff subcommands; need only `ruff check`.

**Generalized (accepted):**
```
Bash(ruff check:*)
```

## Integration with Skills

The `dev10x.skills.permission.generalize.generalize_rule_shape()` module
implements this pattern. Use it when a skill generates targeted allow-rules
(e.g., `diag-friction` suggests a rule based on one user's command):

```python
from dev10x.skills.permission.generalize import generalize_rule_shape

targeted = "Bash(git commit:*)"
generalized = generalize_rule_shape(targeted)
# Result: "Bash(git:commit|push)" or similar, depending on context
```

Integrate the output into skill workflows to surface both the specific
rule and the generalized shape.
