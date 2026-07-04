# Friction Levels — Universal Enforcement Model

Three-tier enforcement model for all Dev10x skills, hooks, and
acceptance criteria. Originally defined in ADR-0002 for command
redirection; this document extends the model to cover decision
gates, acceptance criteria, and loop enforcement.

## Levels

| Level | Hook behavior | Skill gate behavior | ACC behavior |
|-------|--------------|-------------------|-------------|
| **strict** | Hard deny (exit 2) | Always block for user input | All checks run, manual gates block |
| **guided** | Hard deny + fallback | Block with recommendation, user overrides | All checks run, failures shown with guidance |
| **adaptive** | Allow + warning | Auto-select recommended option, no interruption | Auto-decide pass/fail, no AskUserQuestion |

Default: `guided` (balances enforcement with practical flexibility).

`adaptive` = the supervisor is AFK. The agent should auto-advance
through all non-ALWAYS_ASK gates without interruption, making
best-effort decisions autonomously. This replaces the former
`--unattended`, `afk`, and `auto-advance` concepts — they are
all expressed as `friction_level: adaptive`.

## Configuration

Friction level is set in `command-skill-map.yaml`:

```yaml
config:
  friction_level: guided  # strict | guided | adaptive
```

User overrides via:
```
~/.claude/memory/Dev10x/diag-friction.yaml
```

Session-level overrides (set by Phase 0 of `Dev10x:work-on`
and `Dev10x:fanout`):
```
~/.claude/Dev10x/session.yaml
```

Resolution order: session override > project override > default.

## Skill Decision Gates

Skills with `AskUserQuestion` gates adapt behavior based on level:

### strict

- All gates fire as documented
- No auto-selection
- User must respond to every decision point

### guided (default)

- All gates fire
- Recommended option is highlighted
- User can override or accept recommendation

### adaptive

- Gates with a `(Recommended)` option auto-select it
- Auto-select means the agent **proceeds as if the user chose the
  recommended option** — it does NOT mean skip the gate entirely.
  The gate still resolves (the decision is recorded), but no
  `AskUserQuestion` call interrupts execution.
- Exceptions: gates marked `ALWAYS_ASK` still fire (e.g., destructive
  operations like branch deletion, data loss scenarios)

**Common mistake (GH-808):** Agents interpret "auto-select" as
"skip the gate and do nothing." This is wrong. Auto-select means
execute the recommended option's action (e.g., approve the plan,
start execution). Skipping the gate entirely means the plan is
never approved and execution never starts.

### Adaptive does not waive skill bodies (GH-112)

**Adaptive friction only suppresses `AskUserQuestion` gates marked
`(Recommended)`.** When a skill's invocation prompt says _"Read
`instructions.md` and follow it end-to-end. `TaskCreate` and
`AskUserQuestion` calls documented there are REQUIRED"_, that
instruction is **not waivable by friction level**. The skill's
`TaskCreate`/`TaskUpdate`/checklist work still runs at every level,
including adaptive.

**Anti-pattern (GH-112):** Agent invokes `Skill(Dev10x:gh-pr-merge)`,
reads the first part of `instructions.md`, decides adaptive mode
licenses a "shortcut" to a one-line `gh pr view --json
mergeable,isDraft,reviewDecision` followed by `gh pr merge` directly.
The skill's 8 pre-merge checks (unresolved threads, CI, draft state,
mergeability, working copy, fixup commits, approval, branch
protection) never execute. Adaptive friction does not authorize this
substitution — it only auto-selects `(Recommended)` options at
`AskUserQuestion` gates.

**Detection signal:** If you are reasoning _"I'm in adaptive mode,
so I can skip the skill body and just run the CLI"_, STOP. That
reasoning is the violation. Adaptive changes the **pace** at gates,
not the **rules** of the skill body.

**How to mark a gate as ALWAYS_ASK:**

```markdown
**REQUIRED: Call `AskUserQuestion`** (ALWAYS_ASK — fires at all
friction levels, including adaptive).
```

Gates without `ALWAYS_ASK` auto-resolve at adaptive level.

### "No checkpoints" rule

Adaptive friction means **no checkpoints** between steps. A
checkpoint is any pause where the agent waits for an implicit
"ok, continue" from the user. Under adaptive friction, the
approved plan is the authorization to proceed through every
remaining step until the plan completion gate.

**What counts as a checkpoint (forbidden under adaptive):**

- Trailing "Ready to proceed?" / "Should I continue?" prompts
- Summarising progress and stopping when the next step is
  unambiguous
- Pausing after a commit, push, or skill completion to await
  acknowledgement
- Inserting an `AskUserQuestion` gate that is not marked
  `ALWAYS_ASK` and is not in the documented gate list for the
  current skill

**What is NOT a checkpoint (allowed at every friction level):**

- `ALWAYS_ASK` gates — destructive operations, true ambiguity,
  irreversible state changes
- Batched A/B decisions per the queue pattern in
  `references/task-orchestration.md` (collect, advance, ask
  once when ALL tasks are blocked)
- Hard blockers — unrecoverable CI, missing credentials, merge
  conflicts requiring human judgment
- The single Plan Completion Gate at end of plan
- Documented gates in a skill's instructions that fire at every
  friction level (e.g., merge-anyway overrides in
  `Dev10x:gh-pr-merge`)

**Detection signal:** If you are about to output "Ready to
proceed to the next step?" or "Continue with the shipping
pipeline?" under `friction_level: adaptive`, STOP. That is a
checkpoint. Skip the question and execute the next step.

**Cross-cutting reinforcement:** Every skill's `**Auto-advance:**`
line ends with "— no checkpoints under adaptive friction." so
the rule travels with the orchestration contract regardless of
which skill is in flight.

## Plan-Approval Gate (work-on Phase 3)

The `Dev10x:work-on` Phase 3 plan-approval gate resolves through the
gate-policy resolver (ADR-0016 Phase 2 / GH-755). Work-on calls
`resolve_gate(gate="plan_approval")` (the `resolve_gate` MCP tool) and
honours the returned `effect` instead of re-deriving the decision from
`friction_level` / `active_modes`. The resolver is the single source
of truth; the former
`dev10x.domain.session_rules.plan_gate_auto_approves()` predicate is
superseded — its `auto-plan` and `adaptive`+`solo-maintainer` shapes
now live in the shipped presets and the `solo-maintainer` overlay.

**How the shipped presets resolve `plan_approval`:**

| preset | `plan_approval` | Plan gate |
|--------|-----------------|-----------|
| `strict` | `ask` | **Fires** — supervisor approves before any branch checkout |
| `guided` | `auto-advance` | **Auto-approved** — light-AFK: the mechanical pipeline (plan included) auto-advances; team interactions + merge stay gated (GH-748 / D-9) |
| `adaptive` | `auto-advance` | **Auto-approved** — walk-away |

A durable project pin (`.dev10x/gate-policy.yaml`) or a session
`gate_overrides` entry can force `plan_approval: ask` back on when a
repo or session wants the veto regardless of preset. Legacy
`friction_level` / `active_modes` sessions are mapped to a preset +
overlays by the resolver's read-compat seam, so an un-migrated
`session.yaml` keeps working without change.

**Effect semantics** (uniform across every gate): `ask` → fire the
`AskUserQuestion` widget; `auto-advance` → proceed with the
recommended option and surface the resolver's `record` line (the D-7
`⚙ gate:…` transcript record) so a present supervisor can still veto;
`skip` → do not present the gate at all. Safety floors
(destructive/irreversible, blocking, secret access, cross-author,
privacy disclosure) always resolve to `ask` regardless of preset —
they are deny-overrides, the resolver's ALWAYS_ASK equivalent.

## Acceptance Criteria (verify-acc-dod)

| Level | Automated checks | Manual checks | Decision gate |
|-------|-----------------|---------------|---------------|
| strict | Run, must all pass | AskUserQuestion per item | AskUserQuestion required |
| guided | Run, failures shown | AskUserQuestion per item | AskUserQuestion with recommendation |
| adaptive | Run, auto-pass/fail | Converted to `prompt` (Claude evaluates) | Merge-gated (GH-729) — see § Completion Gate below |

At adaptive level, the ACC skill runs fully unattended:
1. Execute all automated checks
2. Convert `manual` checks to `prompt` checks (Claude evaluates
   from session context)
3. Resolve the completion recommendation (see § Completion Gate)
4. If recommendation is **Work complete** → auto-complete, no
   user interruption
5. If **Monitor for review** → dispatch `Dev10x:gh-pr-monitor` in
   the background and keep the session open (residual task:
   "Monitor PR #<N> for review / merge")
6. If **Go back** → queue failure report, continue with next task

### Completion Gate (verify-acc-dod) — merge-gated (GH-729)

Completion is reserved for the **merged** state — "shippable /
handed off" is not terminal. The gate's recommended (and, at
`adaptive`, auto-selected) option is driven by PR merge state, not
just "all checks pass":

| PR state | Blocking checks | Recommended | Auto (adaptive) |
|----------|-----------------|-------------|-----------------|
| Merged / no PR | pass | **Work complete** | auto-complete |
| Open, awaiting review | pass | **Monitor for review** (→ `Dev10x:gh-pr-monitor`, ~5 min) | auto-start monitor (background) |
| Any | fail / pending | **Go back** | Go back |

The PR-merge signal is a **gate input, not a pass/fail check** — an
unmerged-but-green PR is the normal awaiting-review state, so a
failing "PR merged" check would loop on "Go back" forever. The
three-way recommendation is encoded once in
`dev10x.domain.session_rules.completion_gate_recommendation()` —
verify-acc-dod's markdown and work-on's Plan Completion Gate defer to
it rather than re-deriving the matrix. Whether that gate *fires* is
resolved by `resolve_gate(gate="completion_signoff")`; this function
only chooses which option it recommends (§ Plan-Approval Gate).

**Boundary with verify-acc-dod's internal checks (GH-755).** The
resolver decides only whether work-on's `completion_signoff` gate
fires. The delegated `Dev10x:verify-acc-dod` skill keeps its own
`friction_level`-keyed tables (above) for its *internal*
automated/manual check behavior — that layer is intentionally left
on the friction-level model until the Phase 3 long-tail migration
(GATE-M3). The two systems meet at one gate by design: the resolver
gates the completion prompt, verify-acc-dod's friction table gates
its per-check evaluation. Neither overrides the other.

## Loop Enforcement

Skills that operate in iterative loops (e.g., fix → test → fix)
must maintain skill routing on every iteration, not just the first.

| Level | Loop behavior |
|-------|--------------|
| strict | Hook blocks raw commands on every iteration |
| guided | Hook blocks + shows fallback on every iteration |
| adaptive | First iteration: skill routing enforced. Subsequent: allowed with warning logged |

The `adaptive` relaxation for loops exists because iterative
debugging sometimes requires raw commands for speed. The warning
log ensures skill-audit can detect and report deviations.

## Playbook Integration

Friction levels and execution modes are **orthogonal dimensions**.
Friction controls *how gates behave*; modes control *what steps
exist*. See `references/execution-modes.md` for the mode system.

### Per-step friction overrides

Playbook steps can declare per-friction-level behavior:

```yaml
- subject: Draft Job Story
  type: detailed
  friction:
    adaptive:
      skip: true    # JTBD not needed in auto mode
    strict:
      prompt: >
        Present draft for approval. Block until confirmed.
```

### Resolution order with modes

1. Load defaults and resolve fragments
2. Apply active modes (skip/override per step)
3. Apply friction-level adaptations (skip/override per step)
4. Apply full overrides (escape hatch)

Modes run before friction so mode-added steps can have their
own `friction:` mappings.

## Reading Friction Level in Skills

> **ADR-0016 (GH-760):** Skills do **not** read `friction_level` /
> `active_modes` / `walk_away` to derive whether a gate fires. They
> call `mcp__plugin_Dev10x_cli__resolve_gate(gate=..., context=...)`
> and honor the returned `effect` (`ask` / `auto-advance` / `skip`).
> The resolver reads session policy itself — `gate_preset`,
> `gate_overlays`, the project pin, and `gate_overrides`, with a
> read-compat mapping for legacy `friction_level` / `active_modes` /
> `walk_away` files. The guidance below is retained for the two
> layers that legitimately still read the session file directly.

The remaining direct readers:

1. **Hook-based enforcement** (preferred): The PreToolUse hook
   reads `friction_level` for command-redirect strictness
   (strict/guided/adaptive per ADR-0002). This is the
   command-redirect axis, not the decision-gate axis.

2. **Session Mode Summary display**: `Dev10x:work-on` reads the
   session file to *print* the resolved posture (GH-189). This is
   display-only — it does not drive gate behavior.

3. **Playbook-level override**: Playbook steps can include
   `friction:` mappings to skip/override steps at a given level.
   This shapes *which steps exist*, not how a gate resolves.

For anything that decides whether an `AskUserQuestion` fires, call
`resolve_gate` — do not re-derive it from the session file.

## Examples

### Git-groom strategy gate at adaptive level

```
Phase 2: Choose Strategy
- Friction level: adaptive
- Only fixup commits detected → auto-select "Fixup (Recommended)"
- Mixed commits detected → auto-select "Fixup (Recommended)"
- No fixups, only rewording needed → auto-select "Mass rewrite"
- Gate skipped, execution continues to Phase 3
```

### ACC at adaptive level (AFK mode)

```
Acceptance criteria (feature):

Checks:
  ✅ Working copy clean
  ✅ CI passing
  ✅ PR not draft
  ✅ No fixup commits
  ✅ Loop compliance (auto-evaluated: all test runs via skill)
  ✅ PR ready (solo maintainer)

6/6 checks passed. Auto-completing — adaptive mode.
```

## Migration Path

Skills adopting friction-level awareness should:

1. Document adaptive behavior in SKILL.md (what auto-selects)
2. Mark destructive gates as `ALWAYS_ASK`
3. Add tests for adaptive auto-selection logic
4. Update playbook steps if level-specific behavior differs

## Walk-Away Layer (ADR-0016: the `afk` overlay)

`Dev10x:afk` composes the walk-away posture as `gate_preset:
adaptive` + `gate_overlays: [afk]`. The `afk` overlay
(`presets/friction/overlays/afk.yaml`) sets `session_adoption:
auto-advance` (trust a stale session) and `doubt_sink:
pr-description` (route deferred decisions to the PR body). Gate
suppression itself is just the `adaptive` base auto-advancing every
non-floored toggle — there is no separate suppression layer.

The legacy `walk_away: true` flag is **deprecated**: the resolver's
`legacy_session_mapping` still maps it to the `afk` overlay for
un-migrated sessions, but `Dev10x:afk` no longer writes it and
skills must not branch on it. See `references/walk-away.md` for the
deprecation note and the `doubt_sink` contract.

Resolution at a single gate is the resolver pipeline (§ Plan-Approval
Gate): safety floors → resolved toggle from preset + overlays +
project pin + session overrides. Destructive/blocking are floors
(always `ask`); everything else follows the composed preset.

## References

- ADR-0002: Data-driven skill redirect with friction levels
- `references/execution-modes.md`: Structural modes (orthogonal)
- `references/walk-away.md`: Walk-away layer contract
- `src/dev10x/validators/command-skill-map.yaml`: Config source
- `src/dev10x/validators/skill_redirect.py`: Hook implementation
- `skills/verify-acc-dod/SKILL.md`: First skill-level adopter
- `skills/afk/SKILL.md`: Walk-away mode skill
