# Reaching another worktree's content

Rules for the one situation the foreman crew keeps rediscovering the
hard way: work that exists only inside a worktree the current agent
does not own.

Companion to [`stall-protocol.md`](stall-protocol.md) § Takeover cannot
reach the dead worker's tree, which covers *when* a takeover happens.
This file covers *who* is allowed to reach across, and why nobody else
is.

For the other worktree failure — the tree is reachable but **damaged**
(tracked files truncated to zero bytes after a hard kill) — see
[`corrupted-worktree-repair.md`](corrupted-worktree-repair.md).

## The rule

**Only the top-level session enters a worktree. A subagent never does.**

An agent dispatched with `isolation="worktree"` is pinned to the
worktree the platform created for it. That pin is not advisory and it
is not reversible from inside — every documented way out has been
tried on a live run and every one of them makes the agent worse off,
not better.

When a subagent discovers it needs another worktree's content, its
whole job is to **report and stop**:

1. Post the exact **absolute worktree path** and the **branch name**.
2. Say what state that tree is in — uncommitted files, a branch never
   pushed, a rebase in progress.
3. Return. Do not attempt to reach it.

The watchdog (or the human) then enters that worktree directly and
drives the remaining lifecycle. That is the path that actually shipped
stranded chunks on 2026-08-01 (PRs #953, #954).

## Why the subagent must not try it itself

Three reach attempts have been observed in the field. All three fail,
and the two failure *shapes* are worth telling apart, because the
instinct to "just try it and see" is wrong for opposite reasons in each.

### Silent: cross-worktree file copy (GH-957, investigation in GH-966)

A rescue agent copied five files out of a parked worktree. The copies
reported success. On recheck none of the files existed, and no error
surfaced anywhere — not in the tool result, not in a hook message.

The danger here is **banked work that does not exist**. An agent that
believes the copy worked reports the chunk as recovered, and the run
proceeds on a lie. GH-966 carries the open investigation into which
layer swallows the write.

### Loud but too late: `EnterWorktree` into a sibling (GH-977)

`EnterWorktree(path=<sibling worktree>)` **reports success**. Then
every subsequent Bash command — `pwd` and `true` included — is refused
by the isolation guard ("resolved to the shared checkout … Refusing to
run it there"). The refusal does not clear by `cd`-ing back to the
pinned path, and `ExitWorktree` refuses as well: it "cannot be called
from a subagent with a cwd override".

Bash is wedged for the remainder of that agent's life. There is no
exit path — the agent cannot lint, cannot commit, cannot push, cannot
even finish the chunk it was already halfway through before it tried.

This is the mirror image of the silent failure. The error is loud, but
it arrives at the *next* command instead of at the call that caused
it, so the guard cannot be treated as a safe probe. The cost of "just
trying" is not a failed attempt — it is the whole remaining session.

### Neither: `ExitWorktree` first

Unavailable to isolated subagents by design. It is not a way to
un-pin before reaching across.

## Consequence for crew prompts

A crew worker prompt must never instruct a worker to "pick up where
the last one left off" in another worktree, and must never name
`EnterWorktree` as a recovery step. The first is a silent no-op; the
second wedges the worker.

Prevention sits upstream of all of it: **a worker that pushes early
has nothing stranded.** Uncommitted work in an isolation worktree is a
liability the moment the worker goes quiet — which is why the crew
contract asks for a push as soon as there is anything worth keeping,
not at the end.

## Status

`EnterWorktree` / `ExitWorktree` and the isolation guard are harness
primitives. They are not implemented in this plugin, and no Dev10x
hook fires on them, so the "fail loudly upfront" fix suggested in
GH-977 is not reachable from here. Until the harness grows an exit
path, the rule at the top of this file is the whole mitigation.
