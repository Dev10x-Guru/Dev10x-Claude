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

## The quota-exhaustion signature — everything stops at once

A **cluster** of simultaneous silences is not a cluster of stalls. It
is the signature of a spent usage block, and it is diagnosed from the
*shape* of the mtimes rather than their age:

| | Per-worker stall | Quota exhaustion |
|---|---|---|
| Mtimes | One file stale, the rest advancing | **Every** file — workers, foreman, watchdog — stops within the same minute or two |
| Onset | Staggered, as each agent hits its own fault | Simultaneous, mid-turn, with no preceding error |
| Git/PR state | The stale worker's branch is frozen; others move | Nothing moves anywhere in the run |
| Ends when | A takeover or respawn is performed | `QUOTA RESET` — the next 5h block opens, unprompted |

The tell is the *simultaneity*, which no per-agent fault can produce:
independent agents do not fail in lockstep. Read the flat block of
mtimes as one fact about the harness, not N facts about N agents.

**Do not run the handshake against a quota freeze.** Every takeover,
respawn, and probe it prescribes costs budget that no longer exists,
and the messages cannot be delivered anyway — the 2026-08-01 run
queued four stall events against agents that were merely frozen and
burned the rest of the block trying to revive them (GH-979). Confirm
with `dev10x foreman probe`: a spent block shows the burn line's
`to_budget_min` at or near zero. Then touch `parked`, log it, and
wait for `QUOTA RESET`.

The forward-looking `QUOTA LOW:` event exists so this state is
entered deliberately — checkpoint, park, resume — instead of being
discovered as a mass stall two hours later. If `QUOTA LOW` never
fired before the freeze, check whether the watcher armed with
`quota_ceiling_tokens=unknown`: with no completed-block history it has
no ceiling to project against and stays silent by design.

## Structural false positives — when the crew composition changes

The watcher's signal is the **newest heartbeat mtime across the run
directory**. That is a property of the run's file set, not of any one
agent, so it ages whenever the *composition* of the crew changes even
though nothing is wrong. Two shapes recur (GH-972 F3 — two of three
`STALL:` events in one run were structural, not real):

| Shape | What is actually happening | Ground truth that disproves the stall |
|---|---|---|
| **Idle-by-design overseer** | The foreman has no event source of its own — most sharply under spawn-by-request, where worker events go to the watchdog — so it cannot heartbeat on its own schedule | Crew worktrees are advancing: branch tips move, PR/CI state changes, per-worker `status-<chunk>.md` mtimes are fresh |
| **Handoff window** | One worker finished its chunk and the next has not yet written its first heartbeat; the newest mtime ages across the gap while the queue advances normally | The finished chunk has an open PR / merged SHA; the new worker was spawned within the window; `parked` grace has not been applied |

Both are cheap to disambiguate and expensive to get wrong. **Before
treating a `STALL` as "abort and respawn", check ground truth:**

1. Per-file mtimes, not just the newest — `stat` each
   `status-<chunk>.md` and ask *which* file is stale.
2. The branch tip and PR/CI state of the chunk the stale file names.
3. Whether an agent is idle by instruction (relay pending, queue
   `parked`, spawn-by-request overseer) — that is a documented,
   expected stale heartbeat, not a fault.

Only a stale file belonging to an agent that should be progressing,
with no movement in git or on the PR, is a stall worth the handshake.
Everything else is noise the detector cannot see past on its own.

This is the same lesson as the cost-flatline trap and the
idle-notification asymmetry, applied to the mtime signal itself: the
detector reports *a property of the file set*, and only the controller
can turn that into a claim about an agent. A `STALL:` event is a
prompt to look, never a verdict.

## Alive-but-not-heartbeating — the second liveness signal (GH-967)

The heartbeat file is a **cooperative** signal: it moves only when the
model chooses to call `Write`. So mtime alone cannot separate the two
states that matter most —

| State | Heartbeat mtime | Own tool-call activity |
|---|---|---|
| Dead / wedged | stale | stale |
| **Alive but not heartbeating** | stale | **recent** |
| Healthy | fresh | recent |

Every incident in the 2026-08-01 run was the middle row, and the
ambiguity cost 30–90 minutes per incident before a stand-down
handshake even began.

**Check the worker's own tool-call activity alongside the heartbeat
file** — `audit_hook_recent` / the audit log keyed by `agentId`, or any
harness-level last-tool-call timestamp. The two signals disagreeing
*is* the diagnosis:

- **Heartbeat stale, tool calls recent** → alive but absorbed. Send a
  plain nudge at ~10–15 min of heartbeat silence. Do **not** declare a
  stall, do not start the stand-down handshake, and do not `TaskStop` —
  killing this worker throws away real in-flight work (the run lost a
  complete `gate_query.py` fix and a finished reference doc this way,
  both one edit from done).
- **Both stale** → genuine inactivity. This is the only shape that
  earns the full stand-down handshake and the destructive kill
  decision.

Reserve `TaskStop` for the both-stale case. A nudge is cheap and
reversible; a kill on a live worker is neither.

**The durable fix is to stop depending on model cooperation.** A
PostToolUse hook on the worker's own session could append a
lightweight `last tool: <name> at <T>` line to its status file
regardless of whether the model remembers to heartbeat — the same
move `audit-wrap` already makes for hook timing, which captures
duration without asking the wrapped script to report it.

## Takeover cannot reach the dead worker's tree

A respawned `Agent(isolation="worktree")` gets a **fresh** worktree.
It does not inherit the predecessor's, and there is no sanctioned way
for it to reach one: its Bash refuses to run outside its own isolation
directory, `ExitWorktree` is unavailable to isolated subagents, and
cross-worktree file copies have failed **silently** — five files
reported copied, none present on recheck, no error surfaced (GH-957).

**Scope of that silent-copy claim (GH-966).** A controlled retest on
2026-08-02 did **not** reproduce it through the `Write` tool: a write
from one isolation worktree into a sibling (dead) worktree succeeded
and read back correctly. So the silent-copy failure is *not*
unconditional and is not a property of `Write`; the GH-957 incident
most likely sits in the rescue path's own copy mechanism, or depends
on a precondition not captured then (the target's git index state, a
race with worktree teardown). Treat "cross-worktree copies fail
silently" as a hazard worth verifying after the fact, not as a
guaranteed block — and still do not build a recovery path on it.

What the retest **did** reproduce is the same *class* of defect on a
different surface: a Bash `cd` into a sibling worktree completes with
no output and no error, but a separate later command shows the CWD
never moved — the isolation guard silently pins it back. That is not
the `EnterWorktree` wedge below (Bash keeps working); it is a silent
no-op. Any relative-path operation written after such a `cd` will
quietly target the wrong tree. **Always verify with a separate `pwd`
after crossing worktrees, and never trust a bare `cd` as proof of
location.**

Nor can a subagent talk its way in with `EnterWorktree`. That call
**reports success** and then wedges the agent's Bash permanently —
every later command, `pwd` included, is refused by the isolation
guard, and `ExitWorktree` refuses too, so there is no way back
(GH-977). It is the one failure here that is loud but *too late*:
the damage is done at the call, not reported at the call. Full
rules for reaching another worktree's content:
[`worktree-recovery.md`](worktree-recovery.md).

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
Nor is instructing that worker to `EnterWorktree` into the dead one —
that trades a silent no-op for a wedged agent (GH-977).

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

**Sonnet reduces the risk; it does not eliminate it (GH-967).** The
tier correlation held at n=3 opus incidents, which is what motivated
the default. It broke at n=4: a **sonnet** worker on the very next
run stalled with the identical shape (one early heartbeat, then
silence through active, productive work). The full 2026-08-01 count
is 6 clean opus chunks against 3 opus incidents and 1 sonnet
incident — enough to keep the default on risk-reduction grounds, not
enough to call sonnet immune. Do not skip the liveness checks in
§ Alive-but-not-heartbeating on a sonnet worker.

The best-supported mechanism is not a tier effect at all: heartbeats
are cooperative and nothing preempts a model mid-turn to emit one, so
any sufficiently absorbing multi-file burst can swallow the cadence
on any tier. See § Alive-but-not-heartbeating for the detection
consequence and `crew-prompt-template.md` § 4 for the event-triggered
heartbeat wording that addresses it.

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
