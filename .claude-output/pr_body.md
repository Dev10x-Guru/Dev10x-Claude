**When** reviewing code consolidations that combine duplicated helpers under newly documented rules, **I want** clearer guidance on what to verify in the consolidated code, **so** I can catch violations early and prevent regressions in future consolidations.

## Changes applied

- Expanded `.claude/rules/script-domain-boundaries.md` reviewer checklist from 3 items to 6, adding explicit checks for logging module usage, Result[T] type annotations, and helper-function scope across multiple callers
- Added new "Exception: Config Loaders at Critical Path" section to document when config helper functions may call `sys.exit()` and under what constraints

## Filtered items (skipped)

- **"Add code-consolidation reviewer check to reviewer-generic.md"** — File already at 85 lines; agent specs have ~50-line target. Adding +6 lines would exceed hard budget cap. Deferred to follow-up where the reviewer-generic structure can be refactored to stay within budget.
- **"Consider refactoring resolve_config()"** — Target file (`src/dev10x/skills/permission/config.py`) is in excluded directory (skills/). Refactoring is a valid follow-up but outside this PR scope.
- **"Add cross-skill testing for shared helpers"** — Already partially covered by existing item #10 in reviewer-generic.md ("New class without test suite"). Pattern refinement adds marginal value and would benefit from observation of actual consolidation patterns in future PRs.

Based on: https://github.com/Dev10x-Guru/Dev10x-Claude/pull/382
