# Worktree-Root Anchoring Audit (GH-376)

## Failure Modes

Three distinct failure modes exist when working across multiple git
worktrees:

1. **Workspace scope** — `additionalDirectories` lists individual leaf
   worktree paths (e.g. `/work/tt/.worktrees/tt-pos-7`) instead of the
   project-level `.worktrees` parent (`/work/tt/tt-pos`). Every new
   worktree re-prompts on first read because the leaf directory is not
   registered. Anchoring the **parent** covers all sibling and future
   worktrees without re-prompting per leaf.

2. **Skill-script scope** — allow rules of the form
   `Bash(.claude/skills/<name>/scripts/<name>.py:*)` use a bare-relative
   path that resolves against the active CWD. In a worktree the CWD is
   the worktree root, so the rule silently targets that worktree's skill
   directory rather than the installed plugin. These rules must be
   rewritten to absolute plugin-cache paths or replaced with
   `Skill(<name>)` invocations.

3. **Per-leaf skill-consent scope** — Claude Code scopes "don't ask again"
   Skill() approvals to the narrowest enclosing directory (the leaf
   worktree). There is no project-root scope in the current UI. Document
   this gap per GH-312; do NOT flag it as a rule-fixable finding.

## Detection Steps

1. Scan `additionalDirectories` in each settings file. For each entry
   that ends in `/.worktrees/<leaf>` (i.e. is a leaf, not the parent),
   flag it as WORKTREE_LEAF_ANCHORING.
2. Scan `permissions.allow` for rules matching
   `Bash(.claude/skills/.*/scripts/.*:*)`. Flag each as
   RELATIVE_SKILL_SCRIPT.
3. Note any projects with a `.worktrees/` directory whose parent is NOT
   in `additionalDirectories` at all — flag as MISSING_WORKTREES_PARENT.

## Automated Fix

Run `uvx dev10x permission doctor anchor-worktree-roots --dry-run` to
preview, then without `--dry-run` to apply. The command:
- Discovers all `.worktrees` parents beneath configured roots
- Anchors each parent in `additionalDirectories` across all settings files
- Reports relative skill-script rules for manual rewrite

## Severity Table

| Pattern | Severity | Rationale |
|---------|----------|-----------|
| MISSING_WORKTREES_PARENT | HIGH | Every new worktree re-prompts until anchored |
| WORKTREE_LEAF_ANCHORING | MEDIUM | Partial fix, does not cover future worktrees |
| RELATIVE_SKILL_SCRIPT | MEDIUM | Silently wrong path per worktree |
| Per-leaf skill-consent scope gap | LOW/INFO | Upstream CC defect, no local fix — reference GH-312 |
