# Collapsed mode — watchdog-direct operation

The full harness has three tiers: watchdog → foreman overseer → crew.
**Collapsed mode removes the middle one.** The watchdog dispatches the
crew itself, observes it itself, and runs the merge gate itself.

It is not a degraded improvisation. It was one until GH-1054: three
overseers failed sequentially in a single run and the recovery — the
watchdog taking the tier over — was undocumented, so nobody could tell
whether it was allowed. It is.

## When to choose it

- **Rung 3 of the overseer fallback ladder** — two or more overseers
  fail the same way, or a respawn fails inside one chunk. See
  `overseer-discipline.md` § Overseer-tier fallback ladder for rungs 1
  and 2; do not skip to collapse on a first stale heartbeat.
- **In-session / attended runs**, where the watchdog is already
  reading everything the overseer would relay and the extra hop only
  adds latency.
- **Short queues** — one or two chunks, where the overseer's context
  saving never pays for its spawn and briefing cost.

Record the switch as a numbered `DECISIONS.md` entry. A fresh foreman
spawned later must not find itself competing with a watchdog that has
already taken the tier.

## What the watchdog takes on

Everything in `overseer-discipline.md` that was the foreman's:

- Dispatching each chunk's worker from `crew-prompt-template.md`, and
  holding the roster.
- The wait cycle — heartbeat, ONE bounded blocking call, heartbeat.
  The watchdog is a top-level session and does not die between turns,
  but a stall clock still runs against the files it owns.
- Stall triage per `stall-protocol.md`, including the two-window
  stand-down handshake before any takeover.
- The merge gate, which it already owned. There is no MERGE REQUEST
  relay any more — the gate's inputs are read directly.

The crew contract does not change. Workers still stop at PR-open, and
the watchdog still never writes implementation code.

## What collapsing costs

The overseer tier exists to keep the night's minute-by-minute
observation — heartbeat reads, roster churn, relay traffic — out of
the watchdog's context, on a cheap model. Collapse spends that saving:
every worker report, every status file, every triage now lands in the
top-level session, and a long queue can exhaust it before dawn. That
is the trade, and it is why collapse is rung 3 and not rung 1.

Observed once (GH-1054): the remaining chunks after a collapse ran at
roughly twice the prior throughput. One run, not a benchmark — enough
to say collapse is not a penalty, not enough to make it the default.

## Merge guidance when no watcher is armed

Applies to whoever runs the merge gate — the watchdog in the full
harness, or you directly in collapsed mode. It is never a crew worker.

The merge discipline in `instructions.md` Phase 2 assumes the full
night-shift harness (watcher relaying `BASE MOVED`). With no
`dev10x foreman watch` armed, a rebase→CI-pending→park cycle
re-triggers CI on every rebase and can ping-pong indefinitely.

When `pr_get` reports the PR green and `MERGEABLE`, and the diff
cannot conflict with what merged since (e.g. docs-only, disjoint
files), merge directly and let the rebase-merge strategy replay the
commit. Only fall back to a local rebase when `pr_get` reports
`CONFLICTING`.
