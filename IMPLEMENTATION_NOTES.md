# Lessons Learned PR #382 - Implementation Notes

## Value Filter Results

Applied the mandatory value filter to 5 proposed action items from the lessons learned analysis of PR #382.

### Items That Survived

**2 items** passed all four filter checks (deduplication, recurrence, actionability, budget):

1. **Expand script-domain-boundaries.md reviewer checklist** (High priority)
   - File: `.claude/rules/script-domain-boundaries.md` (currently 51 lines)
   - Change: Replace 3-bullet checklist with 6 numbered items
   - Budget impact: 51 → 63 lines (63% budget utilization, under 200-line cap)
   - Rationale: Current checklist incomplete; missing checks for logging module, Result[T] typing, helper exit-calling

2. **Document config-loader exception** (Medium priority)
   - File: `.claude/rules/script-domain-boundaries.md` (will be 63 lines after item 1)
   - Change: Add "Exception: Config Loaders at Critical Path" subsection
   - Budget impact: 63 → 69 lines (34.5% budget utilization)
   - Rationale: Future config-loader consolidations need guidance on acceptable H7 violations

### Items Filtered Out

**3 items** failed at least one filter check:

| Item | Gate | Reason |
|------|------|--------|
| 1: Code-consolidation check to reviewer-generic.md | Budget | File at 84 lines (budget 50); +6 would make 90 (40 over budget) |
| 4: Refactor resolve_config() to return Result[T] | Scope | File `src/dev10x/skills/permission/config.py` is in `skills/` directory (not allowed) |
| 5: Add cross-skill testing guidance | Actionability | Too vague ("when extracting a helper"); unproven recurrence; no concrete target file |

## Exact Changes Required

### File: `.claude/rules/script-domain-boundaries.md`

Replace the section starting at line 45 (`## Reviewer checklist`) through line 51 (end of file):

**Old content (7 lines):**
```
## Reviewer checklist

- Domain function uses `logging`, returns `Result[T]`, no `sys.exit`,
  no `print()`.
- Script `main()` owns exit codes and printed output.
- A stdout-parsed script emits errors as JSON on stdout, exits
  non-zero.
```

**New content (35 lines):**
```
## Reviewer checklist

1. Domain function uses structured `logging` module, not `print()` or
   `stderr.write()`.
2. Domain function return type is explicitly `Result[T]` (not `dict | None`).
3. Domain function does not call `sys.exit()`.
4. Helper functions used across ≥2 callers: verify no `sys.exit()`
   calls; if one caller needs to exit, the exit should be in the
   caller, not the helper.
5. Script entry point's `main()` owns process exit: maps domain
   results to `sys.exit(N)` with stderr messages.
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

**Line count impact:**
- Current: 51 lines
- After change: 69 lines
- Budget remaining: 131 lines (69% margin)

## How to Apply

1. Approve the file edit permission when prompted
2. Or manually edit `.claude/rules/script-domain-boundaries.md` and replace lines 45-51 with the new content above

## Source Reference

Lessons learned analysis: PR #382 (GH-246 Centralize skill helpers)
- Report location: `.claude-output/lessons_learned_report.md`
- Action items: Items #2 and #3 from the "High Priority" and "Medium Priority" sections
