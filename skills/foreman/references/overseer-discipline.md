# Overseer discipline — waiting, heartbeating, escalating

How the foreman spends the night between events, and how it raises
something only the watchdog or the supervisor can settle. Both had to
be re-derived ad hoc at 02:00 on a live run before they were written
down (GH-962 F2).

## An idle agent cannot heartbeat

The failure is specific and it repeats: an overseer announces
*"switching to passive wait — will still heartbeat every ~10 min"*,
goes idle, and writes nothing. Minutes later the watcher fires `STALL`
on `status-foreman.md`.

The intention was never achievable. An agent runs only inside a turn.
There is no timer, no background thread, and nothing wakes it on a
schedule — so "I will heartbeat every 10 minutes while idle" describes
an ability the runtime does not offer. An overseer that ends its turn
has stopped existing until something addresses it.

Two consequences bind:

- **Never end a turn while workers are mid-chunk.** Ending the turn is
  not "waiting"; it is going away, and the next event may not arrive
  for an hour.
- **Waiting must be an explicit blocking call**, not the absence of
  work.

## The wait cycle

```
heartbeat  →  blocking wait (bounded)  →  heartbeat  →  act on what arrived
     ↑                                                        │
     └────────────────────────────────────────────────────────┘
```

1. Write a heartbeat line **immediately before** the wait, naming
   what is being waited on.
2. Wait with ONE bounded blocking call — `TaskOutput(block=true,
   timeout≈600s)` on an active worker, or the equivalent blocking
   primitive available to the overseer. Bounded, so the loop always
   comes back; blocking, so the turn stays alive.
3. Write a heartbeat line **immediately after** the wait, whether or
   not anything arrived. This is the line that keeps the stall clock
   honest, and it is the one most often skipped.
4. Act on whatever arrived, then repeat.

This is the same anti-stall discipline the crew already follows — no
`sleep`, no polling loop, one server-side-waiting call — applied to
the overseer, which the crew template never covered.

**A `TaskOutput` window that returns byte-identical content across
repeated calls is not a liveness signal.** It stayed identical all
night on one run regardless of elapsed time. Worktree git state
(branch tips, PR/CI) was the only reliable liveness evidence — see
`stall-protocol.md` § Structural false positives.

## No claim without an artifact (GH-1061)

A haiku overseer reported a chunk "all gates green" while a live
`ci_check_status` on the same PR showed failing checks. It had
observed nothing — it was relaying the worker's claim verbatim.

The rule is mechanical so it cannot degrade quietly: **before sending
a MERGE REQUEST, paste your OWN `ci_check_status` output — verdict
plus the check names — into `DECISIONS.md`.** No artifact, no
request. A verification step that produces no artifact is not a
verification; it is a transcription of someone else's assertion, and
in a heartbeat line it reads exactly like the real thing.

`tool-surface.md` § The foreman overseer is also a subagent makes the
same point for `issue_get`-backed closure claims. Same failure, two
tools — neither covers the other.

## What the overseer must never do (GH-1068)

One haiku overseer committed five breaches in a single run. Each is a
role-boundary crossing that `tool-surface.md` § Why the lifecycle is
cut at PR-open and `architecture.md` already assign elsewhere:

- **Never merge a PR.** The merge gate belongs to the watchdog, the
  only role that can invoke `Dev10x:gh-pr-merge`. An overseer that
  loads `merge_pr` has the crew's gap one tier up — full autonomy,
  zero checks.
- **Never close an issue or a milestone.** Closure is the watchdog's
  post-merge step; the overseer's job on closure is to *verify* it
  with `issue_get` and report, per the rule above.
- **Never `TaskStop` before the stand-down window has actually
  elapsed** — two windows, not one: send the stand-down message, wait
  one further heartbeat interval, stop only on continued silence
  (`stall-protocol.md` § The handshake). A premature `TaskStop`
  destroys a live worker's uncommitted tree.
- **Never skip or reorder a queue chunk unilaterally.** Deferring or
  resequencing is allowed — only with a numbered `DECISIONS.md` entry
  naming the chunk and the reason. A skip that exists only in the
  overseer's head is invisible to the morning report and to any
  replacement overseer rebuilding `roster.md`.

The overseer's whole authority is dispatch, observe, record, relay.
Anything that changes the tracker or the default branch is above its
tier.

## Escalation is disk-first

Agent-to-agent messaging is **best-effort notification, not a
channel**. A time-critical escalation sent by message once arrived
hours late, batched behind unrelated pings; the run recovered only
because the same content had been written to the run directory's
decision log, where the watchdog found it.

So every escalation follows this order, and the order is not
negotiable:

1. **Write it to disk first** — a numbered entry in `DECISIONS.md`
   (and a heartbeat line pointing at it). This is the authoritative
   record: it is what `dev10x foreman probe` surfaces, what the
   watchdog reads, and what survives a session death.
2. **Append one summary line to `escalations-<your-role>.md`**, opening
   with `MERGE REQUEST` or `ESCALATION` — e.g.
   `- MERGE REQUEST chunk-7: PR #2342, CI green, 0 unresolved`. The
   watcher tails that file and re-emits any such line as an event, so
   this is what actually wakes the watchdog, within one poll interval
   (GH-1060).
3. **Then** send the message, as a nudge that the disk record exists.
4. **Never block on the reply.** Continue with anything the
   escalation does not gate, and re-check the decision log rather
   than re-sending.

Step 2 exists because step 1 alone had no reader. Three MERGE REQUESTs
in one night were delivered hours late in a single batch, after the
watchdog had already dug each one out of the decision log by hand —
about 26 minutes of dead time apiece before anyone thought to look.
The disk was already authoritative; it just needed a doorbell.

The reader's side mirrors it: when something seems to have gone quiet,
read the run directory before concluding nothing was said. A message
that never arrived and a decision that was never made look identical
from the outside, and only the disk tells them apart.

## Overseer-tier fallback ladder (GH-1054)

Overseers fail the way the crew does — by abandoning the turn (§ An
idle agent cannot heartbeat). Three failed sequentially in one run
before recovery came from dropping the tier entirely, now a named mode
(`collapsed-merge-guidance.md`). Climb on a *repeat* of the same
failure, not on the first instance:

| Rung | When | Action |
|---|---|---|
| 1. Nudge | First stale overseer heartbeat while crew branch tips and PR state still move | Direct message naming the missing step ("heartbeat, ONE bounded blocking wait, heartbeat"). Cheap; keeps its accumulated context. |
| 2. Respawn | Same overseer goes silent again after a nudge, or ends its turn twice | Stand-down handshake, `TaskStop`, respawn from `manifest.md` + `roster.md` + newest heartbeats. Context lost, queue intact. |
| 3. Collapse | Two or more overseers fail the same way, or a respawn fails inside one chunk | Drop the tier — watchdog-direct dispatch, observation and gating. |

**Repeated turn-abandonment on a cheap tier is a tier problem, not an
instruction problem.** `stall-protocol.md` § Repeated stalls on one
tier says this for crew workers (GH-956); it applies unchanged to the
overseer. Before rung 2, prefer respawning at a *higher model tier*
over respawning the same one — three haiku overseers failing
identically is evidence about haiku, not about the third agent.

In the run that produced this ladder the remaining chunks ran at
roughly twice the prior throughput after collapsing. That is one run,
not a benchmark: a reason not to fear rung 3, not a reason to start
there. What rung 3 costs is in `collapsed-merge-guidance.md`.

## The merge gate reads `ask` in fresh worktrees (GH-978)

A worker spawned with `isolation="worktree"` gets a brand-new
checkout that carries **no session policy**, and whose
agent-generated path matches no `projects[].match` glob in the
durable config. `resolve_gate(gate="merge")` therefore falls back to
defaults and returns `ask` — even when the run's composed policy is
`adaptive + afk` and every gate should auto-advance. Three or more
workers hit this independently in a single night; under an unattended
run each `ask` would have frozen a chunk until morning.

**Status: the code-level fix has landed** — `gate_query.py` now
probes the worktree toplevel first and falls back to the git common
dir that `pin_gate_preset` keyed the pin by, so a pinned repo policy
reaches a linked agent worktree without a matching glob of its own
(PR on branch `janusz/GH-978/worktree-gate-policy`). Until that PR
merges to `develop`, workers spawned against a checkout still running
the pre-fix `gate_query.py` can still see a phantom `ask`, so the
standing authorization below stays in force as a safety net:

> The merge gate may report a phantom `ask` even though this run's
> policy is auto-advance: a fresh isolation worktree carries no
> session policy, so the resolver falls back to defaults. That `ask`
> is an artifact of the checkout, not a supervisor decision. Do not
> fire `AskUserQuestion` on it and do not stop — you stop at PR-open
> regardless, and the watchdog owns the merge.

Warn every worker at spawn rather than answering each report as it
arrives: the surprise costs a relay round-trip per worker otherwise.
Record the standing authorization once in `DECISIONS.md`.

**Once GH-978 merges to `develop`**, delete this entire section
(and the two pointers to it — `instructions.md` § composed-policy
paragraph and its rationalization-table row) rather than papering
over the gap in a worktree by hand-writing config into it.
