# Grandchild Completion Semantics (GH-1464)

A fanout child that dispatches sub-agents of its own is an
orchestrator for them. [`subagent-dispatch.md`](subagent-dispatch.md)
covers the caller side: collect results as notifications arrive, and
mark a task `completed` only when its notification lands. This file
covers the three ways that rule failed one level down.

## What went wrong

In one audited wave, two children each dispatched sub-agents of their
own:

- **Child-2 (docs compaction)** dispatched four sub-agents. On a "no
  live background children" notice it assumed none had edited
  anything. Two had landed partial edits and one had landed nothing,
  so it redid the pass inline. Three decision-record files were left
  uncommitted, and they surfaced only through the orchestrator's
  `stranded-work` check.
- **Child-14 (frontend strip)** believed its sub-agent had stopped
  and began rewriting the same two locale files by hand. The
  sub-agent was still running, and its commit is what landed.

## The rules

1. **A delegated file belongs to the sub-agent until its completion
   notification arrives.** Do not edit it, even to "help". Two writers
   on one working tree are a clobber, not a merge, and the loser's
   work vanishes without an error.
2. **A "no live background children" notice says nothing about
   edits.** It only means nothing is still running. Before redoing
   anything, run `git status` and `git diff`, and read what each
   sub-agent actually left. A partial edit is work you keep, not
   noise you overwrite.
3. **Whatever landed is yours to commit.** Sub-agents that exit
   without committing leave their changes in *your* worktree, and an
   isolated worktree is reclaimed with everything uncommitted in it
   (GH-427, GH-1363). Commit through `Skill(Dev10x:git-commit)` before
   you report a status, and before you redo a pass inline.
4. **A sub-agent's report is a claim, not evidence.** "Done" from a
   grandchild is checked against the tree like any other status. The
   orchestrator's `dev10x orchestration stranded-work` check is the
   last line of defence, not the first.

## Why this is its own file

`subagent-dispatch.md` is already past its size budget. These rules
also bind a *dispatched* agent, not a session orchestrator: they are
quoted into the fanout child brief so a worker sees them before it
dispatches anything.
