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

When the WHOLE queue is idle by instruction — a burn-gate hold, waiting
out a quota block, a supervisor-only decision blocking every chunk —
say so in the run directory instead of reasoning about it per event:
touch `parked` while the hold lasts and remove it on release. The
watcher then suppresses `STALL` (and quota milestones) for the
duration, and grants one stall window of grace after release so
resuming crew is not alarmed on before their first heartbeat lands
(GH-946). A hold that is not flagged produces exactly the false STALL
alarms this section warns about, one per tick.

## Takeover cannot reach the dead worker's tree

A respawned `Agent(isolation="worktree")` gets a **fresh** worktree.
It does not inherit the predecessor's, and there is no sanctioned way
for it to reach one: its Bash refuses to run outside its own isolation
directory, `ExitWorktree` is unavailable to isolated subagents, and
cross-worktree file copies have failed **silently** — five files
reported copied, none present on recheck, no error surfaced (GH-957).

So respawn recovers a *chunk*, never a *tree*. Work that exists only
as uncommitted files in a dead worker's worktree is unreachable to
every agent below the watchdog. Two sanctioned paths:

1. **Watchdog-driven lifecycle completion.** The top-level session
   enters the parked worktree directly and drives lint → commit →
   rebase → push → PR → merge itself. This is what actually shipped
   both stranded chunks on 2026-08-01 (PRs #953, #954).
2. **Explicit deferral.** Post a comment on the chunk's issue naming
   the worktree path AND the branch, so the next run resumes instead
   of reimplementing.

What is NOT a path: respawning a worker and telling it to "pick up
where the last one left off". It cannot see the tree, and the failure
is silent, so it will report success on work that does not exist.

The prevention is upstream of all of this — a worker that pushes
early has nothing stranded. Uncommitted work in an isolation worktree
is a liability the moment the worker goes quiet.

## Model tier for crew workers

Dispatch crew workers on `model="sonnet"` by default. Reserve a
stronger tier for a chunk that demonstrably needs it, and expect to
pay for it in supervision.

Long unattended background workers dispatched on opus have shown a
silent-stall failure shape: clean status write, clean branch setup,
then 30–52 min of zero tool calls until killed. On the 2026-08-01 run
this hit four consecutive opus spawns across two chunks, while the
same chunks on sonnet ran the full lifecycle without a stall
(GH-956). Root cause is still open — treat the tier default as risk
management, not as a settled explanation.

## Repeated stalls on one tier — switch the tier

After **two stalls of identical shape** on the same chunk, the third
respawn changes the model tier instead of rewriting the brief again.

A progressively more directive brief is the tempting response, and it
does not work when the failure is not comprehension: on 2026-08-01,
C6/#920 burned three opus attempts — attempt 3 mandated the heartbeat
write as a literal Step 0 — and all three stalled identically. The
same chunk on sonnet completed minutes later (GH-956).

Identical shape means the same failure signature, not merely the same
outcome: same phase reached, same silence duration band, no
intervening tool calls. Two stalls at different phases are two
different problems and each still gets its own corrective brief.

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
