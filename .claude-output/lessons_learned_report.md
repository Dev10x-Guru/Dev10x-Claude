# Lessons Learned Analysis: PR #382
## GH-246 Centralize skill helpers behind importable modules

**Analysis Date:** 2026-05-31
**PR:** [#382](https://github.com/Dev10x-Guru/Dev10x-Claude/pull/382)
**Status:** Merged ✓
**Files Changed:** 22 | **Additions:** 634 | **Deletions:** 550

---

## Executive Summary

PR #382 successfully consolidated duplicated skill helpers into importable modules and ratified the architectural pattern via ADR-0010. The PR was well-structured with clear incremental commits and comprehensive documentation. However, the review process identified an opportunity: **newly consolidated code that introduces new rules should be validated against those rules**. One instance of `resolve_config()` calling `sys.exit()` from an in-process domain module contradicts the newly documented script-domain-boundaries convention, though this appears to be an edge case rather than a pervasive issue.

---

## Statistics

| Metric | Value |
|--------|-------|
| Total files changed | 22 |
| New files created | 7 |
| Files deleted | 2 |
| Pure documentation/ADR | 2 |
| Code consolidations | 5 |
| Test files added | 3 |
| Total additions | 634 |
| Total deletions | 550 |
| Review comments | 1 (fixup squash request) |
| Review rounds | 1 |
| Approval status | Merged |

---

## PR Scope & Intent

**JTBD:** When a skill needs JTBD parsing, PR classification, or config loading, developers want to import one shared implementation instead of maintaining copy-pasted duplicates, so they can fix behavior once and have every skill—and the MCP boundary—pick it up.

**Findings addressed:**
- F5: Duplicated `extract_jtbd` and `md_to_slack_bold` across 3 skills → consolidated into `src/dev10x/skills/common/jtbd.py`
- G2: Unimportable classifier logic in `collect_prs.py` → extracted to `src/dev10x/skills/release/classifier.py`
- H12: Copy-pasted config loading in 3 permission skills → consolidated into `src/dev10x/skills/permission/config.py`
- H3/H7: Undocumented conventions for output and error handling → ratified in `.claude/rules/script-domain-boundaries.md`
- I4: Dead code (`batch_find_prs`) with zero production callers → removed

---

## Feedback Analysis

### Single Review Comment
The sole Claude bot review comment requested a fixup commit squash:

**Comment:** `57c78b0` should be squashed into `7115737` before merge.
**Acceptance:** Merged as-is (fixup was likely resolved in final commit).
**Assessment:** Minor housekeeping; does not indicate review gaps.

### Review Coverage
- **Code review agents invoked:** Rules maintenance agent (INDEX.md update, new rule file, ADR)
- **Coverage:** No inline code review feedback beyond the fixup comment
- **Implication:** Changes were either auto-approved or the review process did not flag issues

---

## Identified Improvements

### 1. **Validate Newly Consolidated Code Against New Rules**
**Target:** `.claude/agents/reviewer-generic.md`
**Current line count:** 85 lines
**Concept exists:** No (partially related to #10, but not explicit for consolidations)
**Recurrence evidence:** This is the first major consolidation under the new script-domain-boundaries rule; pattern applicable to future refactors.

**Finding:**
The PR introduced `.claude/rules/script-domain-boundaries.md` which documents two conventions:
- **H3 (Output):** In-process domain functions use `logging`, never `print()`.
- **H7 (Error):** In-process domain functions return `Result[T]`, never call `sys.exit()`.

However, the newly created `src/dev10x/skills/permission/config.py::resolve_config()` violates H7:

```python
def resolve_config(candidates: list[Path], create_path: Path | None = None) -> Path:
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    # ...
    print(message, file=sys.stderr)
    sys.exit(1)  # ❌ Violates H7: should return Result[T]
```

The function is called from other domain modules (`update_paths.py`, `clean_project_files.py`, `merge_worktree_permissions.py`), which have no way to handle the error gracefully—they simply exit. Tests explicitly verify this behavior via `pytest.raises(SystemExit)`.

**Recommendation:**
When a PR consolidates duplicated code under newly documented rules, the reviewer should verify that the consolidated module follows those rules. Add a checklist item to reviewer-generic.md:

```
10b. **Code consolidation under new rules** — When a PR adds new rule
     documentation (e.g., `.claude/rules/*.md`) AND consolidates code
     under those rules, verify the consolidated code follows the new
     conventions. Check for violations like: domain functions calling
     `sys.exit`, using `print()`, or returning void instead of
     `Result[T]`. Flag as WARNING if any consolidation violates the
     rule it was consolidated under.
```

**Already covered:** Item #10 (new class without test suite) and Item #9b (documentation alignment).

---

### 2. **Enhanced Script-Domain-Boundaries Reviewer Checklist**
**Target:** `.claude/rules/script-domain-boundaries.md`
**Current line count:** 51 lines
**Concept exists:** Yes (reviewed checklist at lines 45-51)
**Recurrence evidence:** This is the first rule-file for H3/H7 conventions; checker patterns will appear in future skills and CLI commands.

**Finding:**
The reviewer checklist in script-domain-boundaries.md is terse (3 items) and doesn't explicitly cover edge cases or cross-caller scenarios:

```markdown
## Reviewer checklist

- Domain function uses `logging`, returns `Result[T]`, no `sys.exit`,
  no `print()`.
- Script `main()` owns exit codes and printed output.
- A stdout-parsed script emits errors as JSON on stdout, exits
  non-zero.
```

Missing checks:
1. **Helper functions that exit** — helpers called from multiple domain modules should not call `sys.exit` if any caller might want to handle errors gracefully.
2. **Logging module usage** — verify `import logging` and use of `logging.error()` / `logging.warning()`, not bare `stderr.write()` or `print(..., file=sys.stderr)`.
3. **Result[T] typing** — verify return type annotations explicitly include `Result[T]` (e.g., `-> Result[dict[str, Any]]`), not bare `-> dict | None`.

**Recommendation:**
Expand the reviewer checklist to 5-6 items:

```markdown
## Reviewer checklist

1. Domain function uses structured `logging` module, not `print()`
   or `stderr.write()`.
2. Domain function return type is explicitly `Result[T]` (not `dict | None`).
3. Domain function does not call `sys.exit()`.
4. Helper functions used across ≥2 callers: verify no `sys.exit()`
   calls; if one caller needs to exit, the exit should be in the
   caller, not the helper.
5. Script entry point's `main()` owns process exit: maps domain
   results to `sys.exit(N)` with stderr messages.
6. Stdout-parsed script emits errors as JSON on stdout (not stderr),
   exits non-zero.
```

**Already covered:** Item #5-6 are the current checklist; Items #1-4 are enhanced/new.

---

### 3. **Documentation Pointer in script-domain-boundaries.md for Config Loader Exception**
**Target:** `.claude/rules/script-domain-boundaries.md`
**Current line count:** 51 lines
**Concept exists:** Partial (single-channel rule section addresses JSON stdout; doesn't address helper-function exception)
**Recurrence evidence:** Config helpers (`resolve_config`, permission setup) are a common pattern; exception applies to this one instance but may generalize.

**Finding:**
The PR consolidated config loading into `config.py::resolve_config()`, which calls `sys.exit(1)` on error. This is an exception to H7 (domain functions should not exit) that was not documented. Future reviewers will not know whether this is:
- An acceptable exception for critical-path config validation, or
- A temporary workaround pending refactor to `Result[T]`, or
- A violation that slipped through review.

**Recommendation:**
Add an "Exceptions" section to the rule or document in the source code:

```markdown
### Exception: Config Loaders at Critical Path

Some config loaders (e.g., `dev10x.skills.permission.config::resolve_config`)
call `sys.exit(1)` on missing configuration. This is acceptable when:
1. The function has exactly one call chain: CLI command → domain module
   → config loader.
2. Missing config is unrecoverable (user must create the file).
3. The call is documented in the module docstring.

Document any config-loader exceptions in the module docstring and
reference this rule. Do NOT use exit-calling helpers for general
utility functions shared across multiple call chains.
```

Alternatively, refactor `resolve_config()` to return `Result[Path]` and have callers handle the exit. (This would be a follow-up ticket.)

**Already covered:** Partially by the "Single-channel rule for parsed scripts" section; does not address domain helpers.

---

## Cross-File Consistency Checks

### INDEX.md Table Entry
✓ **Added correctly:** `.claude/rules/script-domain-boundaries.md` listed in the PATH rules table with scope annotation.
✓ **No orphan rules:** All new rule file references have valid `.md` files.

### ADR-0010 vs. Implementation Alignment
✓ **ADR documents the decision:** Three alternative approaches evaluated; ADR-0010 ratifies the thin-shim pattern.
✓ **Implementation follows ADR:** `jtbd.py`, `classifier.py`, `config.py` are all importable domain modules.
⚠️ **One exception undocumented:** `config.py::resolve_config()` violates ADR-0010 Decision item 5 (H7 convention) without explicit exception note.

### Rule File Sizing
| File | Lines | Budget | Utilization |
|------|-------|--------|-------------|
| `script-domain-boundaries.md` | 51 | 200 | 25.5% ✓ |
| ADR-0010 | 248 | *ADR only* | Reasonable |
| INDEX.md entry | +1 | *N/A* | ✓ |

---

## Action Items

### High Priority

**1. Add code-consolidation reviewer check to reviewer-generic.md**
- **File:** `.claude/agents/reviewer-generic.md`
- **Current lines:** 85
- **Action:** Add item 10b after item 10 (new class without test suite)
- **Content:** When PR consolidates code under new rules, verify consolidated code follows those rules
- **Blocker:** Yes; prevents H7 violations in future consolidations
- **Estimated size increase:** +6 lines (within budget)

**2. Expand script-domain-boundaries.md reviewer checklist**
- **File:** `.claude/rules/script-domain-boundaries.md`
- **Current lines:** 51
- **Action:** Replace the 3-item checklist with 5-6 items addressing logging, Result[T] typing, helper exit-calling, and parsed-script error handling
- **Rationale:** Current checklist is incomplete; catches only obvious violations
- **Estimated size increase:** +12 lines (stays within 200-line budget)

### Medium Priority

**3. Document config-loader exception in script-domain-boundaries.md**
- **File:** `.claude/rules/script-domain-boundaries.md`
- **Action:** Add "Exceptions" subsection or update module docstring in `permission/config.py`
- **Content:** When config loaders are acceptable; call site requirements
- **Rationale:** Future consolidations need guidance on acceptable violations
- **Estimated size increase:** +6 lines (total 57 lines, still well under budget)

**4. Consider refactoring `resolve_config()` to return Result[T]**
- **File:** `src/dev10x/skills/permission/config.py`
- **Follow-up ticket:** GH-XXX
- **Rationale:** Aligns with ADR-0010 H7 convention; allows callers to handle errors
- **Note:** Requires updating 3 call sites and test expectations
- **Priority:** Medium (low-impact refactor; can defer to follow-up milestone)

### Low Priority

**5. Add cross-skill testing for shared helpers**
- **Scope:** Future PRs consolidating helpers
- **Recommendation:** When extracting a helper used by ≥2 consumers, add a test that invokes the helper through each consumer's public API (not just directly)
- **Rationale:** Catches integration regressions that unit tests miss
- **Note:** Item #10 in reviewer-generic.md already flags missing tests; this is a pattern refinement for shared-helper PRs

---

## Positive Observations

✓ **Atomic commits per finding:** Each consolidation (F5, G2, H12) was its own commit, making review granular.
✓ **Comprehensive documentation:** ADR-0010 explains context, alternatives, and rationale—not just the decision.
✓ **Test coverage:** New modules include unit tests (test_jtbd.py, test_classifier.py, test_config.py).
✓ **Backward compatibility:** Existing call sites updated to use new consolidated modules; no dangling imports.
✓ **Documentation consistency:** PR body clearly maps findings (F5, G2, H12, I4) to commits and ticket numbers.

---

## Relationship to Prior Findings

- **GH-979 (CWD Discipline):** No violations; permission config modules use `Path`, not bare `os.getcwd()`.
- **GH-246 scope (this PR):** All major findings (F5, G2, H12, H3/H7) addressed; G4/I3/I4 (batch_find_prs) documented as deferred pending API redesign.
- **Skill naming convention:** Not applicable; this PR touches domain modules and ADRs, not skills.

---

## Summary for Next Session

When reviewing future consolidations under new rules:
1. Verify consolidated code follows the new rules (not just documented in a rule file).
2. Expand reviewer checklists when edge cases emerge (e.g., helper-function exit calls).
3. Document acceptable exceptions in the rule file or source code.
4. Plan follow-up refactors to bring violating code into compliance.

**Key insight:** Rules without enforcement checks become aspirational rather than binding. Adding consolidation checks to the generic reviewer agent will prevent future slip-throughs.
