# Implementation Guide: Lessons Learned PR #644

This document specifies the exact changes from the lessons learned analysis
that survived the Value Filter and need to be applied to the codebase.

## Overview

**Analysis:** PR #382 (GH-246 consolidate skill helpers)
**Report Date:** 2026-05-31
**Items Surviving Filter:** 2 of 5 proposed changes

---

## Change 1: Expand Reviewer Checklist in script-domain-boundaries.md

**File:** `.claude/rules/script-domain-boundaries.md`

**Current state:** Lines 45-51 contain a 3-item bullet-point checklist.

**Replace the checklist with:**

```markdown
## Reviewer checklist

1. Domain function uses structured `logging` module, not `print()`
   or `stderr.write()`.
2. Domain function return type is explicitly `Result[T]` (not
   `dict | None`).
3. Domain function does not call `sys.exit()`.
4. Helper functions used across ≥2 callers: verify no `sys.exit()`
   calls. If one caller needs to exit, the exit belongs in the
   caller, not the helper.
5. Script entry point's `main()` owns process exit: maps domain
   results to `sys.exit(N)` with stderr messages.
6. Stdout-parsed script emits errors as JSON on stdout (not stderr),
   exits non-zero.
```

**Rationale:** Current checklist is incomplete. The PR that consolidated
config, JTBD, and classifier helpers violated H7 (sys.exit in domain
functions) without being caught. Expanded checklist catches:
- Missing type annotations on Result[T]
- Helper functions that exit when called from multiple sites
- Logging module vs. stderr edge cases

**Validation:** New checklist will catch the `resolve_config()` violation
that slipped through review.

---

## Change 2: Add Config Loader Exception Section

**File:** `.claude/rules/script-domain-boundaries.md`

**Location:** Insert after the "Single-channel rule for parsed scripts"
section (after line 43), before "## Reviewer checklist".

**Insert this new subsection:**

```markdown
### Exception: Config Loaders at Critical Path

Some config helpers (e.g., `dev10x.skills.permission.config::resolve_config`)
call `sys.exit(1)` on missing configuration. This is acceptable when:

1. The function has exactly one call chain: CLI command → domain
   module → config loader.
2. Missing config is unrecoverable (user must create the file).
3. The call is documented in the module docstring.

Document any config-loader exceptions in the module docstring and
reference this rule. Do NOT use exit-calling helpers for general
utility functions shared across multiple call chains.
```

**Rationale:** PR #382 consolidated config loading into a function that
calls `sys.exit()`, violating H7. This exception clarifies when such
violations are acceptable and guards against overgeneralizing the
pattern to utility functions.

**Future enforcement:** When `resolve_config()` is refactored to return
`Result[Path]` (see GH-XXX follow-up), this exception should be removed
or narrowed to document the historical state.

---

## Items Filtered Out (with reasons)

### Item 1: Code-consolidation check in reviewer-generic.md
- **Status:** SKIPPED (budget gate)
- **Reason:** Target file (.claude/agents/reviewer-generic.md) is already
  85 lines, exceeding the 50-line agent spec budget. Adding 6 more lines
  would worsen overflow.
- **Future option:** Consider extracting reviewer-generic into multiple
  focused agents to stay within budget.

### Item 4: Cross-skill testing pattern recommendation
- **Status:** SKIPPED (not concrete)
- **Reason:** This is a recommendation for future PRs, not a concrete
  rule/doc change within scope.
- **Action:** Document as separate improvement ticket for test-writing
  patterns.

### Item 5: Refactor resolve_config() to return Result[T]
- **Status:** SKIPPED (outside allowed files)
- **Reason:** Target is `src/dev10x/skills/permission/config.py`, which
  is not in the allowed modification list (CLAUDE.md, .claude/rules/,
  .claude/agents/, references/).
- **Action:** This is correctly deferred as a separate follow-up ticket
  (GH-XXX) requiring skill code changes.

---

## Verification Checklist

After applying Changes 1 and 2:

- [ ] `.claude/rules/script-domain-boundaries.md` now has 6-item numbered
  checklist (was 3 bullets)
- [ ] "Exception: Config Loaders" subsection added between "Single-channel
  rule" and "Reviewer checklist"
- [ ] Total line count: ~69 lines (was 51), still under 200-line budget
- [ ] ADR-0010 reference still intact at top of file
- [ ] No formatting changes to existing sections (only additions)

---

## Related Work

- **PR #382:** Original consolidation PR that triggered this analysis
- **ADR-0010:** Ratifies script-domain-boundaries convention
- **GH-246 H3/H7:** The conventions this rule documents
- **Follow-up ticket needed:** Refactor `resolve_config()` to return Result[T]
