# ADR-0032: The Stop gate consults gate policy in-process, for its stand-down branch only

- **Status:** Proposed (awaiting supervisor decision; recommendation
  below is Option D)
- **Date:** 2026-09-27
- **Supersedes:** none
- **Amends:** ADR-0016 D-2 ("skills are policy-ignorant; a resolver
  answers per gate") by naming the Stop hook as a resolver consumer
- **Related:** GH-1348, GH-1251, GH-1314, GH-1339, GH-1366, GH-1404,
  GH-1470, GH-1433, ADR-0022 (FRIC-M1)

## Context

Every Dev10x decision gate resolves through `resolve_gate` (ADR-0016),
except one. The Stop-verdict gate's policy is hardcoded in
`dev10x.hooks.stop_verdict.decide` (`stop_verdict.py:1177-1258`). No
preset, overlay, project pin or override reaches it. GH-1348 asks for
that to be decided explicitly rather than left to grow.

### What `decide()` actually contains

`decide()` returns one of 15 `StopSignal` values
(`stop_verdict.py:199-241`). Most of them are not gates at all:

| Branch | Signals | Kind |
|---|---|---|
| Loop guards | `stop_hook_active`, `cooldown_marker` (`:1202-1215`) | **Floor.** Without them a blocking hook never lets a turn end |
| Nobody to ask | `subagent`, `subagent_path`, `standby`, `no_transcript`, `no_task_list`, `foreign_plan` (`:1205-1242`) | **Structural.** No evidence, or no human on the other end |
| Already answered | `asked`, `stood_down` (`:1228-1252`) | **Structural** |
| Keep working | `continue` (`:1263-1271`, GH-1366) | **Not a gate.** This is how auto-advance is implemented: a Stop `block` continues the turn |
| Waiting correctly | `awaiting_subagents`, `awaiting_supervisor` (`:1273-1295`) | **Structural** (GH-1464, GH-149) |
| Tree says not done | `dirty_tree` (`:1282-1290`, GH-1365) | **Instruction**, not a question |
| **Everything complete** | `blocked` (`:1297`) with the stand-down steer (`_reason`, `:1092-1174`) | **The one decision gate.** It asks the supervisor to choose the next move, stand down, or go on standby |

So GH-1348 is really about **one branch**. Everything else either is a
floor, which by ADR-0016 D-5 no posture should lift, or has no
supervisor to ask.

### Facts that bear on the options

1. **The hook runs Dev10x in-process and cannot reach the MCP server.**
   `hooks/scripts/session-stop.py:43-53` imports `dev10x.hooks.session`
   directly, and `hooks/hooks.json:74-75` gives it a 10s timeout. There
   is no IPC path from a hook to the long-lived MCP daemon. "Route
   through `resolve_gate`" therefore cannot mean an MCP round trip.
2. **The resolver is not MCP-bound.** GH-840 and GH-1433 split the
   read-and-compute half into `GateResolutionQuery`
   (`mcp/gate_query.py:341-421`). It is a plain class that calls the
   domain function `gate_policy.resolve_gate` (`domain/gate_policy.py:506`).
   Its expensive probes are gate-scoped. The `review:cleared` GitHub
   call runs only for `merge`/`request_review` (`gate_query.py:116-160`,
   `:286-320`), and staleness only for `session_adoption` (`:266-283`).
   A stand-down gate would pay only for the YAML reads and the
   worktree→repo fallback in `_policy_toplevel` (`:65-104`).
3. **The Stop hook is not in the startup benchmark.**
   `tests/benchmarks/test_startup_time.py:133-145` measures
   `validate-bash`, `session-tmpdir`, `skill-metrics` and the MCP cold
   import. The budget GH-1348 cites is the 10s timeout, not a
   benchmarked baseline.
4. **Only presence should reach this gate, not review posture.**
   ADR-0022 D-6 keeps `afk` ("is anyone at the terminal?") orthogonal
   to `supervisor_review` ("does the supervisor read the PR?"). The
   stand-down question is a presence question. `supervisor_review: none`
   says nothing about whether a human will answer a widget, so it should
   not silence this gate.
5. **Field cost.** GH-1348's 2026-09-16 comment measured one
   unattended session (`--preset adaptive --overlay solo-maintainer`).
   It rendered 78 `AskUserQuestion` widgets, and 42 of them timed out
   after 600s: about 7 hours of wall-clock blocking. Several of those
   followed an "On standby" answer that a recurring prompt then cleared.
   That re-arm defect belongs to GH-1314 (standby scoping), not to
   policy.

## Options

### Option A: route through `resolve_gate` over MCP (GH-1348 option 1)

- **−** Not implementable as stated (fact 1). It would need a new IPC
  channel into the daemon, with its own failure mode inside a 10s
  timeout.

### Option B: read `friction.yaml` directly in the hook (GH-1348 option 2)

Parse `gate_overlays` in `build_stop_verdict` and branch on `afk`.

- **+** Cheap.
- **−** It re-derives preset ⊕ overlay ⊕ project pin ⊕ override
  precedence outside the resolver. That is the drift the rules warn
  about: it would ignore `allowed_overlays` (GH-805) and per-toggle
  overrides the day it ships.

### Option C: leave it hardcoded, and document why (GH-1348 option 3)

- **+** Zero risk. It is defensible for the floor branches, which the
  table above shows are most of them.
- **−** The one real decision gate keeps asking an empty chair (fact 5),
  and the `afk` overlay stays unable to say "nobody will answer".

### Option D: consult the resolver in-process, for the `blocked` branch only

1. Add one enum toggle, `stand_down`, to `_ENUM_TOGGLES`
   (`gate_policy.py:74-94`).
2. The baseline value is `ask`, which is today's behaviour. The `afk`
   overlay sets it to `auto-advance` (`SHIPPED_OVERLAYS`, `:197-207`).
3. On the `blocked` path only, `build_stop_verdict`
   (`hooks/session_dispatch.py:301-369`) runs
   `GateResolutionQuery(gate="stand_down", …)` in-process.
   - An `ask` result keeps today's block.
   - An `auto-advance` result lets the turn end. It writes the D-7
     visible record, and the open-loop sweep result goes to the
     `doubt_sink` instead of a widget.
4. Any exception or error result falls back to today's hardcoded
   verdict. That is what a policy-free gate would have done, so an
   unreadable policy can never change attended behaviour.
5. All other branches stay hardcoded, and a comment block states that
   they are floors or structural.

- **+** One mechanism for gates, with no re-derived precedence and no
  MCP hop. `allowed_overlays` and overrides apply for free.
- **+** Cost is paid only on the rarest blocking branch. GH-1339 already
  moved the common case off it.
- **−** `decide()` stays pure, but the wiring gains a second I/O read.
  The `blocked` path must be covered by a test with an unreadable
  policy.

### Option E: no policy; make standby survive a recurring prompt

This is the middle path raised in GH-1348's field comment.

- **+** Smallest change that addresses the observed cost.
- **−** It is a GH-1314 scoping fix, not a decision about policy. It
  should land either way, and it does not let `afk` pre-empt the first
  widget.

## Recommendation

**Option D, with Option E landed independently on GH-1314.**

Option C would be right if the Stop gate were only a floor. The table
shows it is a floor **plus exactly one decision gate**, and it is that
gate which fired at an empty chair 42 times in one night. Option D
routes that one gate through the existing resolver without the
MCP hop that made GH-1348 look like a redesign (facts 1 and 2). The
floors are documented as floors and left untouched.

The fallback direction is chosen deliberately. `stop_verdict.py`
elsewhere degrades toward *ending* the turn (`_diagnose`, `:119-129`),
because a failed check is not evidence of a skipped gate. Here the
degraded state is "policy unknown", and the pre-existing verdict is
already the safe answer. Falling back to it keeps every attended session
bit-for-bit unchanged when `friction.yaml` is unreadable.

## Open Questions for the supervisor

1. Should `auto-advance` on `stand_down` **end the turn** or **enter
   standby**? Standby would let the next supervisor message re-arm the
   gate, which is the more conservative choice.
2. Should `solo-maintainer` also set `stand_down: auto-advance`, or only
   `afk`? This ADR recommends `afk` only, per fact 4.
3. Should an unreadable policy fall back to today's verdict (as
   recommended), or degrade toward ending the turn, as the rest of the
   module does?
4. Is the `dirty_tree` instruction a floor that no posture lifts, as
   this ADR treats it, or should `afk` soften it too?

## Consequences (if Option D is accepted)

- `.claude/rules/hook-patterns.md` gains a short "Stop gate and policy"
  note. It names the `blocked` branch as the only resolver consumer and
  lists the floors, which is GH-1348's acceptance.
- A walk-away run under `afk` stops rendering stand-down widgets. Each
  skip leaves a `⚙ gate:stand_down auto-advance` record, so the
  supervisor can audit what the gate would have asked.
- `stand_down` becomes the 18th enum toggle. Every consumer of
  `KNOWN_TOGGLES` (friction-setup, `pin_gate_preset`) sees it.

## References

- `src/dev10x/hooks/stop_verdict.py:119-129, 199-241, 1092-1174, 1177-1297`
- `src/dev10x/hooks/session_dispatch.py:301-369`
- `hooks/scripts/session-stop.py:43-53, 86-100`; `hooks/hooks.json:74-75`
- `src/dev10x/mcp/gate_query.py:65-160, 266-421` (split by GH-1433,
  `11374fb6`)
- `src/dev10x/domain/gate_policy.py:74-94, 161-207, 314-343, 506`
- `tests/benchmarks/test_startup_time.py:133-145`
- [ADR-0016](0016-friction-gate-policy-presets-over-toggles.md),
  [ADR-0022](0022-single-baseline-gate-model-with-supervisor-review.md)
- [GH-1348](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1348),
  [GH-1314](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1314)
