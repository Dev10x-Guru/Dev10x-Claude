# Lessons Learned Implementation - PR #732

## Filtering Summary

**Lessons Learned Analysis:** PR #382 (GH-246 consolidation)

### Items Evaluated

| # | Target | Survival Status | Reason |
|---|--------|---|---|
| 1 | `.claude/agents/reviewer-generic.md` | ❌ SKIP | Budget gate FAILED: 85 lines (50-line budget for internal agents). Adding 6 lines = 91 lines overflow. |
| 2 | `.claude/rules/script-domain-boundaries.md` | ✅ IMPLEMENT | Expands checklist with 3 new specific checks. Budget OK (51 → 63 lines, max 200). |
| 3 | `.claude/rules/script-domain-boundaries.md` | ✅ IMPLEMENT | Documents config-loader exception. Budget OK (63 → 69 lines, max 200). |
| 4 | `src/dev10x/skills/permission/config.py` | ❌ SKIP | File constraint: skills/ forbidden. |
| 5 | `src/dev10x/skills/*/` | ❌ SKIP | File constraint: skills/ forbidden. |

**Threshold:** 2 items survive ≥ minimum 2. **PASS → PROCEED**

## Implementation

### Change 1+2: Enhanced Reviewer Checklist + Config-Loader Exception

**File:** `.claude/rules/script-domain-boundaries.md`
**Lines:** 45-51 (replace with expanded section)

Replace:
```markdown
## Reviewer checklist

- Domain function uses `logging`, returns `Result[T]`, no `sys.exit`,
  no `print()`.
- Script `main()` owns exit codes and printed output.
- A stdout-parsed script emits errors as JSON on stdout, exits
  non-zero.
```

With:
```markdown
## Reviewer checklist

1. **Logging module usage** — Domain function imports `logging` and uses
   `logging.error()` / `logging.warning()`, never `print()` or
   `stderr.write()`.
2. **Result[T] return type** — Domain function return type annotation is
   explicitly `Result[T]`, not bare `dict | None` or void.
3. **No sys.exit() in domain** — Domain function does not call `sys.exit()`
   or `raise SystemExit()`.
4. **Helper-function exit safety** — Helper functions used by ≥2 callers
   must not call `sys.exit()`. If a caller needs to exit, the exit logic
   belongs in the caller, not the helper.
5. **Script entry point ownership** — Script `main()` owns process exit:
   maps domain `Result[T]` to `sys.exit(N)` with stderr messages.
6. **Stdout-parsed script error channel** — When a script's stdout is
   parsed (returns JSON verdict, list, etc.), errors must emit as JSON
   objects on stdout (not stderr), and the script must exit non-zero.

### Exception: Config Loaders at Critical Path

Some config loaders (e.g., `dev10x.skills.permission.config::resolve_config`)
call `sys.exit(1)` on missing configuration. This is acceptable when:

1. The function has a single call chain: CLI entry point → domain module
   → config loader (no multi-caller sharing).
2. Missing config is unrecoverable (user must create the file or it is a
   fatal error).
3. The exception is documented in the module docstring.

Document any config-loader exceptions in the module docstring and
reference this rule (e.g., "Exits H7 convention; see `.claude/rules/script-domain-boundaries.md`").

**Do NOT** use exit-calling helpers for general utility functions shared
across multiple call chains — the exit logic belongs in the caller.
```

## Rationale

**Item 2:** Original checklist is 3 generic bullets. Enhanced version adds 6 specific, actionable items that catch:
- PR #382's sys.exit() violation in resolve_config()
- Return type annotation drift (dict | None instead of Result[T])
- Logging module vs print() confusion
- Helper function exit-calling across multiple sites

These checks are concrete and will prevent future slip-throughs in consolidation PRs.

**Item 3:** Documents the one known exception to H7 (config loaders that exit), with clear criteria for when it's acceptable. Prevents future consolidations from adding similar violations without documented justification.

## Filtered Items

**Item 1:** reviewer-generic.md already over budget (85 lines vs 50 limit). Skipped to avoid bloat. Should be added to alternate agent or plugin-distributed spec.

**Items 4-5:** Require skills/ modifications (forbidden). Marked as follow-up work for separate PR.

## PR Details

- **Branch:** claude/lessons-pr-732
- **Base:** develop
- **Type:** Draft
- **Files changed:** 1 (`.claude/rules/script-domain-boundaries.md`)
- **Additions:** ~36 lines (new checklist items + exception section)
