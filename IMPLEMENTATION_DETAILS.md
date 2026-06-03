# Implementation Details: Lessons Learned from PR #460

## Summary

Applied value filter to lessons learned from GH-246 (PR #382). 2 of 5 proposed items survived filtering; 3 items were appropriately skipped.

## Surviving Items

### Item 2: Enhanced Script-Domain-Boundaries Reviewer Checklist
- **File:** `.claude/rules/script-domain-boundaries.md`
- **Change:** Replace bullet-point checklist (lines 45-51) with numbered 6-item checklist
- **Rationale:** Current checklist (3 items) is incomplete; misses critical checks for logging module usage, Result[T] typing, and helper function constraints
- **Recurrence:** First rule for H3/H7 conventions; patterns will appear in future skills and CLI commands
- **Size impact:** 51 → 63 lines (within 200-line budget)

### Item 3: Document Config-Loader Exception Pattern
- **File:** `.claude/rules/script-domain-boundaries.md`
- **Change:** Add "Exception: Config Loaders at Critical Path" subsection (6 lines)
- **Rationale:** PR #382 introduced `resolve_config()` that violates H7 by calling `sys.exit()`. Future consolidations need guidance on when this exception is acceptable
- **Recurrence:** Config helpers are a common pattern in permission/setup workflows
- **Size impact:** 63 → 69 lines (within 200-line budget)

## Filtered Items

### Item 1: Code Consolidation Reviewer Check
- **Status:** SKIP
- **Reason:** Budget gate exceeded
- **Details:** reviewer-generic.md is 85 lines (budget: 50); proposed +6 lines exceeds budget by 41 lines

### Item 4: Refactor resolve_config()
- **Status:** SKIP
- **Reason:** Not in allowed files
- **Details:** Targets `src/dev10x/skills/permission/config.py`; only allowed files are `CLAUDE.md`, `.claude/rules/*.md`, `.claude/agents/*.md`, `references/*.md`

### Item 5: Cross-Skill Testing Patterns
- **Status:** SKIP
- **Reason:** Out of scope
- **Details:** Not a documentation change; would require modifying test infrastructure outside allowed scope

## File Content Changes

**File:** `.claude/rules/script-domain-boundaries.md`

**Old section (lines 45-51):**
```markdown
## Reviewer checklist

- Domain function uses `logging`, returns `Result[T]`, no `sys.exit`,
  no `print()`.
- Script `main()` owns exit codes and printed output.
- A stdout-parsed script emits errors as JSON on stdout, exits
  non-zero.
```

**New section:**
```markdown
## Reviewer checklist

1. Domain function uses structured `logging` module, not `print()`
   or `stderr.write()`.
2. Domain function return type is explicitly `Result[T]` (not `dict | None`).
3. Domain function does not call `sys.exit()`.
4. Helper functions used across ≥2 callers: verify no `sys.exit()` calls.
   If one caller needs to exit, the exit should be in the caller, not
   the helper.
5. Script entry point's `main()` owns process exit: maps domain results
   to `sys.exit(N)` with stderr messages.
6. Stdout-parsed script emits errors as JSON on stdout (not stderr),
   exits non-zero.

### Exception: Config Loaders at Critical Path

Some config loaders (e.g., `dev10x.skills.permission.config::resolve_config`)
call `sys.exit(1)` on missing configuration. This is acceptable when:
1. The function has exactly one call chain: CLI command → domain module
   → config loader.
2. Missing config is unrecoverable (user must create the file).
3. The call is documented in the module docstring.

Document any config-loader exceptions in the module docstring and
reference this rule. Do NOT use exit-calling helpers for general utility
functions shared across multiple call chains.
```

## Result

- **Final file size:** 69 lines (was 51)
- **Budget utilization:** 34.5% of 200-line budget
- **Items implemented:** 2
- **Items filtered:** 3
