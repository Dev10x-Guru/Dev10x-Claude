# Changes Needed: .claude/rules/script-domain-boundaries.md

## Pending Implementation

The following changes have been evaluated as high-quality improvements and are ready to be applied once permissions are approved.

## Change 1: Enhanced Reviewer Checklist

**Location:** Lines 45-51 (Reviewer checklist section)

**Current content:**
```markdown
## Reviewer checklist

- Domain function uses `logging`, returns `Result[T]`, no `sys.exit`,
  no `print()`.
- Script `main()` owns exit codes and printed output.
- A stdout-parsed script emits errors as JSON on stdout, exits
  non-zero.
```

**Replacement:**
```markdown
## Reviewer checklist

- Domain function uses `logging`, returns `Result[T]`, no `sys.exit`,
  no `print()`.
- Helper functions used across 2+ callers: verify no `sys.exit()` calls;
  if a caller needs to exit, the exit should be in the caller, not the
  helper.
- Script `main()` owns exit codes and printed output.
- A stdout-parsed script emits errors as JSON on stdout, exits
  non-zero.
```

## Change 2: New Exceptions Section

**Location:** End of file (after line 51)

**Content to append:**
```markdown

## Exceptions

### Config Loaders at Critical Path

Some config loaders (e.g., `dev10x.skills.permission.config::resolve_config`)
call `sys.exit(1)` on missing configuration. This is acceptable only when:

1. **Single call chain**: The function has exactly one caller path: CLI
   command → domain module → config loader (no intermediate error handling).
2. **Unrecoverable**: Missing config is a fatal error requiring user
   intervention (e.g., creating a required file).
3. **Documented**: The module docstring explains the exit behavior and
   rationale.

Config loaders that are called from multiple sites or contexts must
return `Result[Path]` to allow callers to handle errors gracefully. Do
NOT use exit-calling helpers for general utility functions.
```

## Rationale

These changes enhance the newly-introduced script-domain-boundaries rule based on evidence from PR #382:

- The current checklist missed that helper functions with ≥2 call sites should avoid `sys.exit()` to allow graceful error handling in some callers
- The `resolve_config()` function violates H7 but is acceptable as a documented exception
- Both improvements are expected to prevent future violations in code consolidation PRs
