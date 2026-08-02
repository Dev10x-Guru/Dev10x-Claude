# STALL signal disambiguation and the generation authority token

Depth behind three Phase 2 STALL-handling rules in `instructions.md`:
disambiguating the watcher's signal, the replaced-foreman hazard, and
the spawn-by-request carve-out. Read this before treating any `STALL`
as a verdict.

## Disambiguate the signal before the handshake (GH-972 F3)

The watcher reports the newest heartbeat mtime across the whole run
directory, so it also ages when the crew's *composition* changes — an
idle-by-design overseer, or the handoff window between one worker
finishing and the next's first heartbeat. `stat` the individual
`status-<chunk>.md` files to find WHICH one is stale, then check that
chunk's branch tip and PR/CI state. A stale file belonging to an agent
that is idle by instruction is expected, not a fault. The shapes and
their ground-truth checks are tabulated in `stall-protocol.md` §
Structural false positives.

## A replaced foreman is not necessarily gone (GH-971 F3)

A session-limit death is a PAUSE for a top-level session and a KILL
for its subagents. "The silent foreman is gone" is therefore a false
premise: an interrupted foreman can revive well before its stated
reset, resume issuing instructions, and leave two live supervisors on
one queue — each unaware of the other, the older one acting on stale
state and relaying orders to a crew that `SendMessage` reports as
having no transcript. Observed twice in one run, across two
generations. The asymmetry is what makes it invisible: the workers
really are dead, so a revived foreman's crew never contradicts it.

This makes replacement idempotent from the predecessor's side, so a
revival stands itself down instead of needing the watchdog to notice.
`TaskStop` remains the watchdog's tool, not its only defence. Distinct
from GH-965, which covers the flat-roster spawn limit and the
non-survival of subagent transcripts: that is about what a revived
foreman *can reach*; this is about the orchestrator treating a pause
as a death and creating the duplicate at all.

## The `current-generation` token, in full

The run dir gets a `current-generation` file — one line, `G<n>
<agent-name> <UTC timestamp>` — rewritten by the watchdog on every
foreman spawn or replacement. Every foreman prompt must include:

> Before ANY broadcast, spawn request, relay, or queue advance, `Read`
> `<run-dir>/current-generation`. If the agent name on that line is
> not yours, you have been replaced: write one final line to
> `status-foreman.md` saying so, send no further messages, and stop.
> Do not verify this by asking another agent — the file is the
> authority.

## Under spawn-by-request, a STALL on status-foreman.md is expected noise (GH-972 F1)

The foreman has no event source of its own in that mode — worker
events arrive at the watchdog — so it cannot heartbeat on its own
schedule. The default response is a nudge ("report state and
heartbeat"), never a respawn; escalate to `TaskStop` only if it also
ignores a direct message through a second window.

Two further rules live in `stall-protocol.md` and bind here: a
respawn gets a FRESH worktree, so uncommitted work in a dead worker's
tree is reachable only by the watchdog entering it directly (GH-957);
and after two stalls of identical shape on one chunk, the third
respawn switches model tier rather than rewriting the brief again
(GH-956).
