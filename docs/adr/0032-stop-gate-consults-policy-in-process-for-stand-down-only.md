# ADR-0032: How the Stop gate stops asking an empty chair

- **Status:** Proposed (awaiting supervisor decision)
- **Date:** 2026-09-27; refreshed 2026-11-03 against `a3ea3142`
- **Supersedes:** none
- **Amends:** ADR-0016 D-2, under Option D′ only, by naming the Stop
  hook as a resolver consumer
- **Related:** GH-1348, GH-1314, GH-1470, GH-1404, GH-1475, GH-1339,
  GH-149, ADR-0016, ADR-0022

## Context

Every Dev10x decision gate resolves through `resolve_gate` (ADR-0016),
except the Stop verdict. Its policy is hardcoded in `decide()`
(`src/dev10x/core/hooks/stop_verdict.py:1053-1161`). GH-1348 asks for
that to be decided explicitly.

### What `decide()` contains now

Since the first draft, GH-1475 (`861fdd9f`) removed the subagent
branches, because Stop never fires for a subagent. `1ad15720` stopped
open work from blocking. `decide()` now returns one of **13** signals
(`:200-212`), and **two** of them block:

| Branch | Signals | Kind |
|---|---|---|
| Loop guards | `stop_hook_active`, `cooldown_marker` | **Floor** |
| No evidence | `no_transcript`, `no_task_list`, `foreign_plan` | Structural |
| Already handled | `standby`, `asked`, `stood_down` | Structural (GH-1314, GH-1470) |
| Work in flight | `open_work`, `awaiting_subagents`, `awaiting_supervisor` | Quiet ending. `awaiting_supervisor` is the GH-149 `Verify AC` exit |
| Tree says not done | `dirty_tree` (`:1146-1154`) | **Blocks.** An instruction, and a floor under ADR-0016 D-5 |
| List says done | `blocked` (`:1161`) | **Blocks.** The stand-down question, and the one decision gate |

`blocked` is reached only when the task list exists, belongs to this
session, has nothing actionable or parked, the tree is clean, **and** no
`Verify AC` task is open (`:1156-1159`). A skill that honours GH-149
ends on `awaiting_supervisor` and never sees this gate.

### What GH-1470 and GH-1314 do and do not bound

Both advocates found the same gap independently, and the code confirms
it:

- **After an answer:** GH-1470 records a stand-down against the task-set
  fingerprint (`:1112-1125`; hash at `:419-431`). That bounds the gate
  to at most one question per distinct task set.
- **With nobody there:** a widget that times out writes **neither**
  marker. `_STAND_DOWN_RE` and `_STANDBY_RE` (`:142-148`) need answer
  text. So the next woken turn on the same list blocks again. The bound
  is about one widget per externally woken turn, not per task set. With
  a 10-minute recurring prompt that is the same order as the field
  night's 42 timeouts [Verify: derived from code, not measured].
- **The field baseline is stale.** The 78 widgets and 42 timeouts were
  measured on 2026-09-16, before GH-1470, GH-1404, `1ad15720` and
  GH-1475. One attended day on the current build (2026-11-03 audit log,
  259 Stop verdicts) shows 4 `blocked` and 3 `dirty_tree`. No afk night
  has been measured since.

### Facts about the resolver

- The hook runs in-process (`hooks/scripts/session-stop.py`) with a 10s
  timeout. It cannot reach the MCP daemon, so GH-1348's option 1 (an MCP
  round trip) is not implementable.
- `GateResolutionQuery` (`src/dev10x/core/mcp/gate_query.py`) imports
  only stdlib and domain modules (`:19-25`). Its `run()` is `async`
  (`:354`), so the hook would need `asyncio.run`. Its GitHub probe is
  scoped to `merge` / `request_review`.
- The D-7 visible-record writer `_emit_auto_advance` lives in
  `gate_tools.py:58`, which imports the MCP app (`:19`). The hook cannot
  import it as it stands.
- `completion_signoff` already exists with baseline `auto-advance`
  (`gate_policy.py:88, 183`) and governs a different decision. The `afk`
  overlay sets only `session_adoption` and `doubt_sink` (`:203-205`).

## Options

### Option C: stay policy-free, document why

Record in `hook-patterns.md` that the two blocking branches are a floor
plus a question that GH-149-compliant skills never reach.

- **+** Zero risk, and `decide()` stays pure.
- **−** It leaves the empty-chair cost exactly where it is, and nothing
  documented reduces it.

### Option C+: stay policy-free; a timed-out widget records standby

Same as C, plus: when the turn's last `AskUserQuestion` result is a
timeout, record the standby marker (`:338-340`), exactly as an
"On standby" answer does. Standby already lasts until the supervisor
next speaks (GH-1314), which is the right meaning for "nobody answered".

- **+** It closes the observed cost without letting any posture speak
  for the supervisor. The gate still asks once, and the GH-149 tripwire
  stays.
- **+** A small change inside the module's existing marker machinery.
  No new toggle and no resolver dependency in the hook.
- **−** It needs one captured timeout payload first. This module has
  guessed payload shapes wrongly three times (GH-1257, GH-1314,
  GH-1336).
- **−** A recurring prompt is a boundary message, so standby can re-arm
  on it (the GH-1314 class). C+ bounds the cost to about one widget per
  supervisor silence plus prompt cadence, not to zero [Verify].
- **−** `afk` still cannot say "nobody will answer" to this gate, and
  the Stop verdict remains the one gate outside ADR-0016 D-2.

### Option D′: `afk` turns the question into an instruction, resolved in-process

The first draft's Option D, corrected by its own advocate:

1. Add the enum toggle `stand_down`, with baseline `ask`. The `afk`
   overlay sets it to `auto-advance`.
2. On `blocked` only, `build_stop_verdict` resolves it in-process. Any
   error keeps today's verdict.
3. `auto-advance` does **not** end the turn quietly. The hook cannot run
   GH-1404's open-loop sweep, so a quiet ending would hard-code "Stand
   down" as the winner. Instead it **blocks with an instruction**, like
   `dirty_tree`: run the sweep, act on anything pending, otherwise
   re-create `Verify AC` with a summary and end without
   `AskUserQuestion`. The same verdict records the stand-down
   fingerprint, so new work re-arms the gate.

- **+** `afk` means at this gate what ADR-0022 D-6 says it means.
  Precedence, `allowed_overlays` and overrides apply for free, and no
  precedence logic is re-derived in the hook.
- **+** It restores GH-149 instead of skipping past it: the instruction
  ends on `awaiting_supervisor`.
- **−** More surface:
  - an 18th toggle, the second baseline `ask` (after `external_notify`),
    and a second "is the work done?" knob beside `completion_signoff`;
  - moving the D-7 writer out of `gate_tools.py`;
  - `asyncio.run` in the hook;
  - bounding the `--git-common-dir` lookup, whose 10s timeout
    (`preset_pin.py:41`) equals the whole hook budget;
  - parsing `friction.yaml` once instead of three times.
- **−** A durable `afk` overlay left on after the supervisor returns
  suppresses the question, unless `allowed_overlays` limits it.

### Dominated options

- **A, route over MCP:** not implementable from a hook.
- **B, read `friction.yaml` in the hook:** re-derives precedence and
  ignores `allowed_overlays`, overrides and the GH-978 fallback.

## Ranking

The evaluation ranks **C+, then D′, then C**, with **medium**
confidence. The decision is the supervisor's.

- C+ fixes the measured failure (unanswered widgets) with the least
  surface, and it keeps the gate's one job: making sure an agent never
  signs itself off.
- D′ is the right shape if `afk` should speak for presence at every gate
  without exception. Its cost is about five prerequisite changes.
- C is acceptable only if an afk night on the current build shows the
  cost is already gone.

**Two facts would most change this ranking, and both are cheap to
get:**

1. one captured timed-out `AskUserQuestion` payload;
2. one afk night's Stop signals, grouped by `signal` and
   `harness_version` (`hook-patterns.md` GH-1390).

## Open questions

1. **C+ or D′:** capture the timeout payload and measure an afk night
   before building, or build on the code reading?
2. **D′ only:** should `solo-maintainer` set `stand_down` too, or only
   `afk`? Presence (`afk`) is orthogonal to review posture (ADR-0022 D-6).
3. **Either:** if the 4-of-259 `blocked` endings on 2026-11-03 came from
   skills that broke GH-149 [Verify: which skills is not in the log],
   are those skills fixed first?

## Consequences

- **C / C+:** `hook-patterns.md` gains a "Stop gate and policy" note
  naming the floors and the one question, which is GH-1348's acceptance.
  Under C+, `decide()` gains a timeout branch with its own `StopSignal`.
- **D′:** the same note, plus `stand_down` in `_ENUM_TOGGLES` and the
  drift-guarded preset files. The D-7 writer moves to a domain module,
  and the Stop hook joins `test_startup_time.py`.

## References

- `src/dev10x/core/hooks/stop_verdict.py:135, 142-148, 200-212, 338-340, 419-431, 1053-1161`
- `src/dev10x/core/hooks/session_dispatch.py:301-369`
- `src/dev10x/core/mcp/gate_query.py:19-25, 354`;
  `src/dev10x/core/mcp/gate_tools.py:19, 55-82`
- `src/dev10x/core/domain/gate_policy.py:74-100, 170-206`
- `src/dev10x/core/session/preset_pin.py:41`
- `.claude/rules/hook-patterns.md` § "A Stop Feature May Carry a Verdict"
- [ADR-0016](0016-friction-gate-policy-presets-over-toggles.md),
  [ADR-0022](0022-single-baseline-gate-model-with-supervisor-review.md)
- [GH-1348](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1348),
  [GH-1314](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1314),
  [GH-1470](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1470)
