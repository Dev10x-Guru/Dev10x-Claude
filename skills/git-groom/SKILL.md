---
name: Dev10x:git-groom
description: >
  Restructure, polish, and clean up git commit history in the current
  branch before merging. Creates atomic, well-organized commits that
  tell a clear story.
  TRIGGER when: branch is ready for merge and commit history needs
  cleanup (squash fixups, reorder, reword).
  DO NOT TRIGGER when: branch has clean history already, or splitting
  individual commits (use Dev10x:git-commit-split).
user-invocable: true
invocation-name: Dev10x:git-groom
allowed-tools:
  - mcp__plugin_Dev10x_cli__mass_rewrite
  - mcp__plugin_Dev10x_cli__rebase_groom
  - mcp__plugin_Dev10x_cli__update_pr
  - Bash(${CLAUDE_PLUGIN_ROOT}/skills/git-groom/scripts/:*)
  - Bash(${CLAUDE_PLUGIN_ROOT}/skills/git/scripts/git-rebase-groom.sh:*)
  - Bash(git reset --soft:*)
  - Bash(git push --force-with-lease:*)
  - Bash(/tmp/Dev10x/bin/mktmp.sh:*)
  - mcp__plugin_Dev10x_cli__mktmp
  - Write(/tmp/Dev10x/git/**)
  - AskUserQuestion
---

# Git Branch History Grooming

Restructure, polish, and clean up git commit history before
merging. Produces atomic, well-organized commits with outcome-
focused titles (JTBD style).

## Instructions

The full workflow — strategy selection gate, mass rewrite vs
interactive rebase, fixup autosquash, force-push safety — lives
in [`instructions.md`](instructions.md).

When this skill is invoked, Read `instructions.md` now and
follow it end-to-end. The strategy `AskUserQuestion` gate
documented there is REQUIRED.

## Legacy script path warning (GH-97)

This skill MUST be invoked via `Skill('Dev10x:git-groom')`.
Direct script invocation is unsupported and the historical
path `~/.claude/skills/dx:git/scripts/git-rebase-groom.sh`
no longer exists (it predates the current plugin layout).
Audit sessions show agents reaching for that path from
muscle memory, then falling back to raw
`git -c sequence.editor=... rebase -i --autosquash` when it
ENOENTs. Neither path is correct — both bypass the safety
checks this skill wraps around `git rebase` (protected-branch
guard, autosquash sanity, force-push-with-lease). If you see
the ENOENT, the corrective action is to invoke the skill,
not to retry the script.
