# Stall handling — the stand-down handshake

What a `STALL:` event from `dev10x foreman watch` means, what it does
NOT mean, and the handshake that must run before any takeover.

## What heartbeat silence proves

A stale `status-<chunk>.md` mtime proves exactly one thing: **the
agent is not progressing.** It does not prove the process is gone.

The distinction matters because the two states have different risk
profiles. A dead worker is inert — taking its chunk over costs
nothing but the duplicated effort already lost. A live-but-idle
worker that wakes after a takeover is a *conflict*: two agents each
believing they own the chunk, pushing to the same branch, closing the
same issues, posting duplicate comments on the same PR.

So the protocol never asks "is it dead?" — a question no available
signal answers. It asks "is it responsive?", which a direct message
does answer.

## The handshake (mandatory before takeover)

1. **Stand-down message.** Send the stalled agent a direct message
   that:
   - names every action already completed on its chunk — branch,
     commits, PR number, merges, comments posted, issues closed;
   - instructs it to **reply `STOP-ACK` and cease all writes**;
   - states explicitly: report state, do **not** re-execute any
     completed step.

   Naming the completed actions is not courtesy — it is what stops a
   revived worker from redoing them. An agent that wakes with no
   knowledge of the takeover will faithfully re-run its whole mission.

2. **Wait one more heartbeat interval** (~15 min, or the next watcher
   tick). Do useful work elsewhere; do not poll.

3. **Branch on the reply.**
   - **Any reply at all** — `STOP-ACK`, a status report, a question —
     is strong evidence of liveness. The agent is alive: resume it
     with a corrective brief (naming the banned shape or the blocker)
     rather than replacing it. A live worker that resumes keeps its
     uncommitted tree; a replacement loses it.
   - **Silence through this second window** → takeover proceeds:
     `TaskStop` the agent, then respawn from `manifest.md` plus the
     newest heartbeats and the live PR/CI state.

## Evidence — why this exists (2026-07-30, plugin 0.91.0)

Two stalls in one run, handled differently, with opposite outcomes:

- **crew-C0** — heartbeat 28 min stale, spend flat. Concluded dead;
  the watchdog completed the remainder of the chunk itself. 22
  minutes later C0 emitted an idle notification and reported having
  completed the *full* mission, including its own `gh pr close`
  attempt that returned "already closed". Result: duplicate rationale
  comments on PR #872 (C0 posted `5134370673` and `5134375198`; the
  watchdog had posted `5134676433`).
- **crew-C2** — heartbeat 27 min stale, spend flat, uncommitted work
  in the tree. The watchdog sent an explicit status-check message
  before taking anything over. C2 was alive, resumed, and delivered
  PR #921 cleanly.

The inputs were near-identical. The only difference in outcome was
the handshake.

A later run in the same series landed PR #926 as a draft after a
force-push — a reminder that takeover-adjacent recovery steps
(force-push, re-push, respawn) each need their own post-condition
re-check, not an assumption that prior state survived.

## The cost-flatline trap

Flat spend over the stall window was used in case (1) as
corroborating evidence of death. **It is not evidence of anything.**
A cheap idle agent and a dead agent produce identical spend graphs.
The inference is tempting precisely because it feels quantitative;
treat any appeal to a flat cost curve as a rationalization and fall
back to the handshake.

## The idle-notification asymmetry

- An **idle notification** proves neither liveness nor death. Idle
  pings fire between turns and arrive late and out of order — case
  (1)'s ping arrived 22 minutes after the agent was declared dead.
- A **reply to a direct message** is strong evidence of liveness.

Responsiveness is the discriminator, not silence.

This cuts the other way too: an agent that is idle **by instruction**
has expected-stale heartbeats. A foreman holding for a relay — a
`QUOTA RESET`, a base-branch rebase instruction, a supervisor
decision — is behaving correctly while its heartbeat ages. A literal
reading of "silent foreman → `TaskStop` and respawn" would destroy a
healthy overseer mid-wait and reset the queue. Message it and wait for
the reply before concluding anything.

## Status-file ownership

Every `status-<chunk>.md` has exactly ONE writer: the agent named in
its filename. The foreman and watchdog read these files; they never
write to them.

`Write` refreshes the file's mtime, and mtime is the sole signal the
stall detector trusts. A foreman that writes a note into a crew
worker's status file resets that worker's stall clock — a genuinely
dead worker would then never trip `STALL` at all. (This happened: a
foreman wrote its own progress into `status-C0.md`.)

Foreman and watchdog observations about a chunk belong in
`DECISIONS.md` or `decisions-<chunk>.md`, never in a status file.

## Timestamp discipline

The line format is `- <UTC timestamp> <phase>: <one-liner>`, and the
timestamp is obtained ONLY by running `date -u`. Never compose,
estimate, or carry forward a timestamp: in the same run, C0 logged
`20:49:00Z` while real UTC was `17:57`.

mtimes remain ground truth for the detector precisely because
self-reported times lie — but a worker writing invented times also
corrupts the morning audit trail the supervisor reads to reconstruct
the night.
