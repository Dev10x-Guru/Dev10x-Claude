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

Overseer subagents may lack the Agent tool on some platforms. The
foreman then sends the watchdog a message:

```
SPAWN REQUEST <chunk-id>
name: crew-<chunk-id>
model: <from manifest>
prompt: <complete worker prompt, ready to paste>
```

The watchdog executes exactly that Agent call and nothing else. The
brief stays authored by the foreman; the watchdog stays a dumb relay.

## Failure modes and recoveries (all field-observed, GH-890)

| Failure | Signal | Recovery |
|---|---|---|
| Crew worker hangs on a blocking wait / permission wall | `STALL:` while foreman heartbeat is fresh | Foreman: TaskStop worker, respawn with a corrective brief naming the banned shape and the current on-disk state (branch/PR survive — resume, don't redo) |
| Foreman itself dies or hangs | `STALL:` and `status-foreman.md` is the stale file | Watchdog: TaskStop foreman, respawn from `manifest.md` + newest heartbeats. All durable state is on disk by design. |
| Watchdog turn frozen by a prompt | Nothing fires; discovered in the morning | Prevented, not recovered: Phase 0 pre-flight + script-only watcher + minimal action surface. If it still happens, workers keep running — only queue advancement stops. |
| Quota block exhausts mid-run | Session paused by the platform; `QUOTA RESET:` on the new block | Foreman resumes/respawns interrupted crew; in-flight PRs pick up from their on-disk state |
| Base branch moves under an open PR | `BASE MOVED:` | Relay chain → active worker: fetch, rebase, re-verify, safe force-push; never merge on stale ancestry. Re-check freshness immediately before every merge gate. |
| Worker "completes" but issues stay open | Foreman closure verification (issue_get per Fixes link) | Foreman closes stragglers with a completion comment, or reopens the chunk as a remainder |
| Idle-notification noise mistaken for stalls | Idle pings between turns, often delayed | Ignore as evidence; only heartbeat mtimes and live PR/CI state count |
| Catastrophic harness loss (session killed, host reboot — run dir in /tmp is gone) | Nothing fires; discovered by the supervisor | The tracker is the durable store by contract: every queued chunk maps to open issues and every scope cut left an open issue (crew contract). A fresh foreman run rebuilds the queue from open milestone/label issues alone; nothing is lost but time. |

## Heartbeat protocol

- One `status-<chunk>.md` per crew worker + `status-foreman.md`, all
  in the run directory; appended via the Write tool (never shell
  redirects).
- Line format: `- <UTC from date -u> <phase>: <one-liner>`.
- **mtime is truth.** Workers mis-stamp their line text (wrong clock
  math is common); the watcher only trusts `stat` mtimes.
- Stall threshold 25 min (crew writes every ~15), re-alert suppressed
  for one threshold window, grace period until first write.

## Quota policy

- `dev10x foreman watch` tracks the active 5h block offline
  (`dev10x.domain.usage`): cost milestones every `--cost-step` USD
  and block-identity change = `QUOTA RESET`.
- The harness never throttles itself preemptively — the platform
  pause + reset-resume cycle is cheaper than idling capacity on a
  guess. The morning report includes per-block spend.
