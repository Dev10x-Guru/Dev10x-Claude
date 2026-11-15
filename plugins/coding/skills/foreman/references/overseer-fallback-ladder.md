# Overseer-tier fallback ladder (GH-1054)

Extracted from `overseer-discipline.md` (GH-1599) so that file could
take the watchdog run-dir rule without breaching the 200-line
reference cap.

Overseers fail the way the crew does — by abandoning the turn
(`overseer-discipline.md` § An idle agent cannot heartbeat). Three
failed sequentially in one run before recovery came from dropping the
tier entirely, now a named mode (`collapsed-merge-guidance.md`). Climb
on a *repeat* of the same failure, not on the first instance:

| Rung | When | Action |
|---|---|---|
| 1. Nudge | First stale overseer heartbeat while crew branch tips and PR state still move | Direct message naming the missing step ("heartbeat, ONE bounded blocking wait, heartbeat"). Cheap; keeps its accumulated context. |
| 2. Respawn | Same overseer goes silent again after a nudge, or ends its turn twice | Stand-down handshake, `TaskStop`, respawn from `manifest.md` + `roster.md` + newest heartbeats. Context lost, queue intact. |
| 3. Collapse | Two or more overseers fail the same way, or a respawn fails inside one chunk | Drop the tier — watchdog-direct dispatch, observation and gating. |

## A repeat on a cheap tier is a tier problem

Repeated turn-abandonment on a cheap tier is a tier problem, not an
instruction problem. `stall-protocol.md` § Repeated stalls on one
tier says this for crew workers (GH-956); it applies unchanged to the
overseer. Before rung 2, prefer respawning at a *higher model tier*
over respawning the same one — three haiku overseers failing
identically is evidence about haiku, not about the third agent.

## What rung 3 costs

In the run that produced this ladder the remaining chunks ran at
roughly twice the prior throughput after collapsing. That is one run,
not a benchmark: a reason not to fear rung 3, not a reason to start
there. What rung 3 costs is in `collapsed-merge-guidance.md`.
