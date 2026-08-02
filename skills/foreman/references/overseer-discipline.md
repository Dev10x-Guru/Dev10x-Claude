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
2. **Then** send the message, as a nudge that the disk record exists.
3. **Never block on the reply.** Continue with anything the
   escalation does not gate, and re-check the decision log rather
   than re-sending.

The reader's side mirrors it: when something seems to have gone quiet,
read the run directory before concluding nothing was said. A message
that never arrived and a decision that was never made look identical
from the outside, and only the disk tells them apart.

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
