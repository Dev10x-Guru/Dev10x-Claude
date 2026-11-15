# Durability envelope — what survives a session death

What an unattended orchestration may rely on across a session
boundary, and what it must never assume. Companion to
[`stall-protocol.md`](stall-protocol.md), which covers a *worker*
going quiet; this file covers the *session* dying underneath the
whole cast.

Filed from a three-session run (8-chunk milestone, three API
session-limit deaths, GH-965). Every point below cost a reversal or
a rebuilt artifact.

## The contract in one line

**Exactly two things survive a session death: commits pushed to
origin, and text posted in a GitHub issue comment.** Everything else
— transcripts, scratchpads, the run directory — is session-scoped or
host-scoped and is gone without warning.

| Artifact | Survives worker turn end | Survives session death |
|---|---|---|
| Commits pushed to `origin` | yes | yes |
| GitHub issue / PR comments | yes | yes |
| Run directory (`/tmp/…`) — manifest, queue, heartbeats | yes | no (temp dir; dies with the host) |
| Worker scratchpad files | no | no |
| Agent transcripts (the `SendMessage` channel) | yes | **no** |

## Rule 1 — durable-first, as it is produced

Anything that must outlive the session goes into a pushed branch or
an issue comment **as it is produced**, not saved for wrap-up.
Deaths give no warning, so "write it down when you're finishing"
reliably loses the work of everyone who does not get to finish.

Making early handover posting a standing instruction to every worker
was the single highest-leverage process change across the three-run
series: session 3 resumed cheaply *because of it*.

The cost of ignoring this is concrete. The most expensive artifact
of that run — a grep-derived 55-file / ~330-hit caller inventory —
lived only in the run directory, was lost once already, and was
rescued into a GitHub comment by the third foreman only because it
happened to re-verify a claim in its own brief.

## Rule 2 — a resumed orchestrator re-derives state from origin

An inherited brief is a **hypothesis, not a record**. Its author
could not see whether the work landed: a worker reporting "committed
work on a branch" may have been killed between the commit and the
push, and nothing in the handover distinguishes the two.

Before acting on any inherited claim, verify by command:

- branch existence and SHA (`git branch -r`, `git ls-remote`)
- PR existence and state (`pr_get`)
- issue state (`issue_get`)

Field case: a run-3 handover asserted a chunk had "committed work on
a branch". `git branch -r` showed **no such branch existed**. Acting
on the brief would have meant an hour spent chasing a tree that was
never pushed.

This is the same discipline the merge gate applies to a worker's
report ("a memory, not a fact") — lifted to the session boundary.

## Rule 3 — transcripts die with the session

`SendMessage` to a worker's `agentId` returns **"No transcript found
for agent ID"** once the dispatching session has died, even though
the ID is well-formed and the worker's own commits are intact on
origin.

The distinction that matters:

| Boundary | Resumable? |
|---|---|
| A worker **ends its turn** — still in the same session | yes — `SendMessage` resumes it with full context |
| The **session** dies (API session limit, host loss, kill) | **no** — every transcript is discarded |

Both are described with the word "resume", and they behave
completely differently. Our run recorded "exited workers are
resumable" as a verified decision in one session and had to reverse
it in the next.

**Consequence: every worker a resumed foreman needs must be freshly
spawned.** A resumption plan built around messaging the previous
run's crew is dead on arrival — and that is discovered only after
the plan has already committed to it. Rebuild the queue from open
tracker issues and pushed branches instead (the same path
`architecture.md` prescribes for catastrophic harness loss).

## Rule 3b — a pause silences the session's own event queue (GH-1109)

Rule 3 covers a session that *dies*. A quota **pause** is the milder
boundary and has its own trap: the session survives, and so does
everything queued for it, but nothing is read while it is paused —
including the events that would tell it the pause is over.

| Signal | Delivered to a paused session? |
|---|---|
| `QUOTA RESET:` from the in-session watcher | no — the watcher is paused too |
| Queued `Monitor` notifications | no — they wait, unread |
| A due `ScheduleWakeup` | no — it does not revive the session |
| An inbound cross-session message / `--resume` | **yes** — this is the only re-entry |

So a paused run cannot observe its own reset. The consequence is
measured, not theoretical: in the 2026-08-31 run the block reset at
01:00Z, 15 minutes after the freeze, and the session slept until a
human nudged it at 06:28Z — five hours of paid, available capacity
unused, which is exactly the outcome the harness exists to prevent.

**Consequence: the actor that notices a reset must live outside every
session.** `dev10x watchdog wake`, armed as a cron/systemd timer in
Phase 1 step 2 and removed in Phase 3, is that actor. It probes the quota
block offline, finds run directories whose heartbeats have all gone
silent, and fires an operator-supplied resume command at most once per
block boundary. It deliberately does not speak the harness's
cross-session protocol — that transport is not ours, the same finding
`mcp-connectivity.md` records — so the operator supplies the command
that works for their setup.

## Rule 4 — a foreman cannot spawn NAMED teammates

`Agent(..., name=...)` fails from inside an agent with **"teammates
cannot spawn teammates."** The foreman is itself a subagent, so the
entire named-agent addressing surface is unavailable to it.

The working channel is the raw `agentId` returned in the spawn
result, addressed via `SendMessage(to=<agentId>)`. That works
reliably — but it is the *less* durable handle: names are documented
as surviving an agent's completion, while a raw `agentId` evaporates
at the session boundary per Rule 3.

So the practical rule is: **raw `agentId` is the only push channel a
foreman has, and it does not cross a session boundary.** Neither the
failure message nor the named-agent docs say this; it is why the
constraint is written down here.

Where the foreman also lacks the `Agent` tool entirely, the
spawn-by-request fallback in [`architecture.md`](architecture.md)
applies — the watchdog runs the one `Agent` call verbatim.

## Checklist for a resumed foreman

1. Re-derive every inherited claim from origin before acting (Rule 2).
2. Assume zero live workers; spawn fresh (Rule 3).
3. Rebuild the queue from open tracker issues, not from the previous
   run directory (which may not exist).
4. Instruct every new worker to post handover state early and keep
   it updated (Rule 1).
