# Foreman architecture — the two-tier cast and its failure modes

## Roles

```
supervisor (human, AFK)
   └── watchdog (main session) — reacts to watcher events only
         ├── Monitor: `dev10x foreman watch` (single pre-approved command)
         └── foreman (cheap overseer subagent)
               └── crew worker (one chunk at a time, work-on lifecycle)
```

**Why two tiers:** the main session's turn is the single point of
failure — if IT hits a permission prompt mid-night, nothing restarts
it. So the watchdog's action surface is reduced to a handful of
shapes proven unpromptable in Phase 0: reading watcher events,
SendMessage, TaskStop, Agent (respawn), and appending to the decision
log. Everything chatty (spawn prompts, relays, closure verification,
CI nudges) lives in the foreman, which is disposable and restartable.

## Spawn-by-request fallback

Overseer subagents may lack the Agent tool on some platforms (a flat
team roster leaves the `name` parameter unavailable). The foreman then
sends the watchdog a message:

```
SPAWN REQUEST <chunk-id>
name: crew-<chunk-id>
model: <from manifest>
prompt: <complete worker prompt, ready to paste>
```

The watchdog executes exactly that Agent call and nothing else. The
brief stays authored by the foreman; the watchdog stays a dumb relay.

### It inverts the event flow — the overseer goes idle by design

Because the **watchdog** issues the `Agent` call, it — not the foreman
— becomes the parent of every crew worker. All worker lifecycle events
(idle notifications, completion reports) are therefore delivered to
the watchdog, and the foreman has **no event source of its own**. It
does nothing but wait between relays.

An idle subagent cannot write heartbeats. So under spawn-by-request
`status-foreman.md` goes stale on a fixed cadence and the watcher
emits `STALL:` for a perfectly healthy overseer roughly once per stall
window, all night (GH-972 F1).

**This mode therefore overrides the "silent foreman → `TaskStop` and
respawn" recovery in the table below.** Read literally, those two
rules combine into an instruction to kill and respawn a healthy
overseer every cycle. Under spawn-by-request:

- Treat a `STALL` on `status-foreman.md` as **expected**, not as a
  fault signal. The foreman is idle by instruction, the same way a
  foreman holding for a relay is.
- Run the stand-down handshake anyway — it is cheap — but the default
  outcome is a **nudge** ("report state and heartbeat"), not a
  respawn. Escalate to `TaskStop` only when the foreman also fails to
  answer a direct message through a second window.
- The watchdog's own view of the crew is the better liveness signal
  here: it receives the worker events the overseer cannot.

Record the mode in `DECISIONS.md` the moment the fallback engages, so
a later generation of watchdog does not re-derive the interaction at
03:00.

### Verify a generated worker spec before running it "verbatim"

Phase 0.2 assigns the overseer to the cheapest tier on the rationale
that "it only relays, monitors, and spawns; it never writes code."
Under spawn-by-request that rationale no longer holds: the same cheap
agent **authors the worker prompts**, and "the watchdog runs it
verbatim" turns any hallucination into a top-tier worker's entire
mission (GH-972 F2).

Field case: a generated spec carried a confidently-worded evidence
trail citing a source module that exists nowhere in the repository —
the ticket's real subject was a test-harness file in a different tree.

So "verbatim" governs **authorship, not review**. Before executing a
relayed `Agent(...)` call, the watchdog runs a lightweight sanity
check — seconds, not a re-write:

1. Every file path the spec cites as evidence exists. `Glob` or a
   single `Read` per path; a path that does not resolve is the signal.
2. The chunk's issue numbers match the manifest's queue entry.
3. The branch name and worktree path follow the run's convention.

On a miss, correct that section **from the issue body** (`issue_get`),
send the correction back to the foreman so its later specs improve,
and note it in `DECISIONS.md`. Do not silently rewrite the whole
brief — the foreman still owns authorship.

## Failure modes and recoveries (all field-observed, GH-890)

| Failure | Signal | Recovery |
|---|---|---|
| Crew worker hangs on a blocking wait / permission wall | `STALL:` while foreman heartbeat is fresh | Foreman: run the stand-down handshake (`stall-protocol.md`); on a second silent window, TaskStop worker and respawn with a corrective brief naming the banned shape and the current on-disk state (branch/PR survive — resume, don't redo) |
| Foreman itself dies or hangs | `STALL:` and `status-foreman.md` is the stale file | Watchdog: handshake first (a foreman waiting on a relay is idle by instruction, not dead), then TaskStop and respawn from `manifest.md` + newest heartbeats. All durable state is on disk by design. **Under spawn-by-request this signal is expected noise — see § It inverts the event flow; nudge, do not respawn.** |
| A replaced foreman revives and duplicates the supervisor | Two live foremen on one queue; the older one relays orders to workers `SendMessage` reports as having no transcript | Prevented, not recovered: a session-limit death PAUSES a top-level session while KILLING its subagents, so "replaced" never implies "gone". The watchdog rewrites `current-generation` in the run dir on every spawn/replacement, and every foreman re-reads it before acting — a predecessor that finds another name stands itself down (GH-971) |
| A worker declared dead revives after takeover | Duplicate commits/comments; a second agent acting on the same chunk | Prevented, not recovered: the stand-down handshake positively retires the original before anyone else touches the chunk (`stall-protocol.md`) |
| Watchdog turn frozen by a prompt | Nothing fires; discovered in the morning | Prevented, not recovered: Phase 0 pre-flight + script-only watcher + minimal action surface. If it still happens, workers keep running — only queue advancement stops. |
| Quota block exhausts mid-run | Session paused by the platform; `QUOTA RESET:` on the new block | Foreman resumes/respawns interrupted crew; in-flight PRs pick up from their on-disk state |
| Base branch moves under an open PR | `BASE MOVED:` | Relay chain → active worker: fetch, rebase, re-verify, safe force-push; never merge on stale ancestry. Re-check freshness immediately before every merge gate. |
| The run's own merge echoes back as `BASE MOVED` | `BASE MOVED:` minutes after this run's merge gate landed a PR | Prevented, not recovered: the gate appends the new base tip SHA to `merged-shas` in the run dir, and the watcher rebaselines matching echoes silently (GH-946 — 6 of 7 events in one run were self-echoes, each costing a relay plus a verification turn) |
| Quota-milestone / STALL noise while the queue is deliberately held | Milestones and stall alarms with no crew to act on them | Prevented, not recovered: touch `parked` in the run dir for the hold, remove it on release; milestones roll up into one line and the stall clock gets a release grace window (GH-946) |
| Worker "completes" but issues stay open | Foreman closure verification (issue_get per Fixes link) | Foreman closes stragglers with a completion comment, or reopens the chunk as a remainder |
| Idle-notification noise mistaken for stalls | Idle pings between turns, often delayed | Ignore as evidence; only heartbeat mtimes and live PR/CI state count |
| Catastrophic harness loss (session killed, host reboot — run dir in /tmp is gone) | Nothing fires; discovered by the supervisor | The tracker is the durable store by contract: every queued chunk maps to open issues and every scope cut left an open issue (crew contract). A fresh foreman run rebuilds the queue from open milestone/label issues alone; nothing is lost but time. |
| Session death mid-run (API session limit) — the new session inherits a handover, not a live crew | `SendMessage` to any prior `agentId` returns "No transcript found for agent ID" | Spawn every worker fresh and re-derive each inherited claim (branch, SHA, PR state) from origin before acting on it — the handover's author could not see whether the work landed (`durability-envelope.md`, GH-965) |

## Run-directory files

Everything durable about a run lives here (and only here until it
reaches the tracker). Each file has exactly one writer.

| File | Writer | Purpose |
|---|---|---|
| `manifest.md` | watchdog | Queue order, per-chunk model + scope, gate policy, base branch, verified command shapes. Authoritative for what was queued |
| `DECISIONS.md` | watchdog | Numbered supervisor-grade decisions (D1, D2, …). Authoritative for why anything changed; the escalation channel |
| `decisions-<chunk>.md` | that chunk's worker | Per-chunk rationale, scope cuts |
| `status-<chunk>.md` | that chunk's worker | Heartbeat log; mtime is the stall detector's truth |
| `status-foreman.md` | foreman | Foreman heartbeat log |
| `roster.md` | foreman | At-a-glance table of every delegated chunk — `Chunk \| Issue(s) \| State \| PR \| Worker \| Last update`. A **derived rendering** of the manifest + decision logs + live tracker state, rewritten at existing transition write points so the queue is readable without opening every status file (GH-976). Never the sole record of anything — see [`roster.md`](roster.md) |
| `merged-shas` | watchdog | Base tips this run merged; mutes the watcher's self-echo |
| `parked` | watchdog | Present while the queue is deliberately held; mutes stall/quota noise |
| `current-generation` | watchdog | `G<n> <agent-name> <UTC ts>` — the foremen's authority token |

## Heartbeat protocol

- One `status-<chunk>.md` per crew worker + `status-foreman.md`, all
  in the run directory; appended via the Write tool (never shell
  redirects).
- Line format: `- <UTC timestamp> <phase>: <one-liner>`, where the
  timestamp comes from `date -u` and is never composed by hand.
- **mtime is truth.** Workers mis-stamp their line text (wrong clock
  math is common); the watcher only trusts `stat` mtimes.
- **Each status file has exactly one writer — the agent it is named
  for.** The foreman and watchdog read `status-<chunk>.md`; they never
  write to it. A `Write` from a third party refreshes the very mtime
  the detector uses as liveness, so a dead worker would never trip
  `STALL`. Foreman/watchdog notes about a chunk go in `DECISIONS.md`
  or `decisions-<chunk>.md`.
- Stall threshold 25 min (crew writes every ~15), re-alert suppressed
  for one threshold window, grace period until first write.
- A tripped `STALL` opens the stand-down handshake — it is not an
  authorization to take over. See `stall-protocol.md`.

## Quota policy

- `dev10x foreman watch` (or `uv run dev10x foreman watch` when the
  bare entry point is not tool-installed — GH-947) tracks the active
  5h block offline (`dev10x.domain.usage`): cost milestones every
  `--cost-step` USD and block-identity change = `QUOTA RESET`.
  Milestones are muted while `parked` is present and reported as one
  rollup line on release.
- The harness never throttles itself preemptively — the platform
  pause + reset-resume cycle is cheaper than idling capacity on a
  guess. The morning report includes per-block spend.
