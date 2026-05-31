**When** reviewing code consolidations that combine duplicated helpers under newly documented rules, **I want** clearer guidance on what to verify in the consolidated code, **so** I can catch violations early and prevent regressions in future consolidations.

## Status: PENDING FILE MODIFICATIONS

This draft PR documents the required changes from the PR #382 Lessons Learned analysis. The feature branch is prepared, but the actual rule file modifications require explicit permission approval.

## Changes Required

See `.claude-output/required_changes.md` for the exact modifications needed to `.claude/rules/script-domain-boundaries.md`:
- Add new "Exception: Config Loaders at Critical Path" section
- Replace reviewer checklist with enhanced 6-item numbered list

## Applied Changes

- Evaluated 5 action items through value filter
- Created feature branch: claude/lessons-pr-382
- Documented exact file modifications required
- Prepared detailed PR body with JTBD and filtered-items rationale

## Filtered Items (Skipped)

- **"Add code-consolidation reviewer check to reviewer-generic.md"** — File already at 85 lines; agent specs have ~50-line target. Adding +6 lines would exceed hard budget cap. Deferred to follow-up.
- **"Consider refactoring resolve_config()"** — Target file in excluded directory (skills/). Refactoring valid but outside this PR scope.
- **"Add cross-skill testing for shared helpers"** — Already partially covered by item #10 in reviewer-generic.md. Pattern refinement adds marginal value.

## Next Steps

1. Approve permission to modify `.claude/rules/script-domain-boundaries.md`
2. Apply changes documented in `.claude-output/required_changes.md`
3. git add .claude/rules/script-domain-boundaries.md
4. git commit -m "🤖 GH-246 Strengthen H3/H7 reviewer guidance"
5. Update PR from draft status

Based on: https://github.com/Dev10x-Guru/Dev10x-Claude/pull/382
