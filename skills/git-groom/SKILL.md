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
