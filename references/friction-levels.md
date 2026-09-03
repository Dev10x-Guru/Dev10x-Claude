# Gate Behaviour — One Baseline, One Review Fact

How Dev10x decides whether an `AskUserQuestion` fires. Two things
answer that: the **baseline**, which auto-advances, and
**`supervisor_review`**, which says whether the supervisor reads the
PR before the next step is allowed. `friction_level` does not — it
names the separate ADR-0002 dial (§ The other `friction_level`).

## The model

There is **one shipped base preset, `adaptive`**, and no session-time
posture choice
([ADR-0022](../docs/adr/0022-single-baseline-gate-model-with-supervisor-review.md)
D-1). `strict` and `guided` are retired — artefacts of the
pre-ADR-0016 ladder, not a choice anyone made.

**Auto-advance is the baseline.** Every gate resolves to its
recommended option unless a floor, a project pin, or a per-toggle
override says otherwise. The preset *mechanism* survives: user-defined
presets in `~/.config/Dev10x/friction-presets.yaml` and per-toggle
overrides (ADR-0016 D-4) keep working. What is gone is the shipped
*choice* between three postures.

Three layers decide one gate, in order:

1. **Safety floors** — deny-overrides. Always `ask`.
2. **`supervisor_review`** — the durable project fact, expressed as a
   floor so it can force `ask` and never grant autonomy.
3. **The resolved toggle** — baseline + overlays + project pin +
   session `gate_overrides`.

## Resolving a gate

> Skills do **not** read config to derive whether a gate fires. Call
> `mcp__plugin_Dev10x_cli__resolve_gate(gate=…, context=…)` and honour
> the returned `effect`. The resolver owns floor/preset/overlay/pin
> precedence; re-deriving it drifts (GH-760). Pass the concrete facts
> about the instance — author type, destructiveness, blocking,
> reversibility — as `context`; do not hand-classify.

| `effect` | What the skill does |
|---|---|
| `ask` | Fire the `AskUserQuestion` widget; block on the answer |
| `auto-advance` | Execute the recommended option AND surface `record` |
| `skip` | Do not present the gate at all |

### Auto-advance means execute, not skip (GH-808)

**Auto-advance means the agent proceeds as if the supervisor chose the
recommended option.** It does NOT mean skip the gate and do nothing.
The gate still resolves and the decision is still recorded; only the
`AskUserQuestion` interruption is removed.

Agents get this wrong in one specific way: they read "auto-select" as
"skip", so the plan is never approved and execution never starts.
Auto-advance on `plan_approval` means *approve the plan and begin*.

### The visible record is mandatory (ADR-0016 D-7)

Every `auto-advance` returns a `record` line:

```
⚙ gate:plan_approval auto-advance → "Approve" (baseline auto-advance)
```

Surface it in the transcript and append it to the audit log and the
resolved `doubt_sink`. **Silent auto-advance is a compliance bug** — a
present supervisor must be able to notice a decision mid-flight and
veto it, and a suppressed gate with no log entry is indistinguishable
from a bug. `ask` and `skip` produce no record.

### The baseline does not waive skill bodies (GH-112)

**The baseline suppresses `AskUserQuestion` gates. It suppresses
nothing else.** When a skill's invocation prompt says _"Read
`instructions.md` and follow it end-to-end; the `TaskCreate` and
`AskUserQuestion` calls documented there are REQUIRED"_, that is
**not waivable by gate policy**. The skill's `TaskCreate` /
`TaskUpdate` / checklist work runs unchanged.

**Anti-pattern:** the agent invokes `Skill(Dev10x:gh-pr-merge)`, reads
the first part of `instructions.md`, and decides its autonomy licenses
a shortcut to one `gh pr view --json mergeable,isDraft` plus a direct
merge. The skill's pre-merge checks — unresolved threads, CI, draft
state, mergeability, working copy, fixup commits, approval, branch
protection — never execute. No gate policy authorizes that.

**Detection signal:** if you are reasoning _"gates auto-advance here,
so I can skip the skill body and just run the CLI"_, STOP. That
reasoning is the violation. Auto-advance changes the **pace** at
gates, not the **rules** of the skill body.

### The "no checkpoints" rule

A checkpoint is any pause where the agent waits for an implicit "ok,
continue". **There are no checkpoints.** The approved plan is the
authorization to proceed through every remaining step until the plan
completion gate.

**Forbidden — these are checkpoints:**

- Trailing "Ready to proceed?" / "Should I continue?" prompts
- Summarising progress and stopping when the next step is unambiguous
- Pausing after a commit, push, or skill completion to await
  acknowledgement
- Inserting an `AskUserQuestion` that is not `ALWAYS_ASK` and is not
  in the current skill's documented gate list

**Allowed — these are NOT checkpoints:**

- `ALWAYS_ASK` gates — destructive operations, true ambiguity,
  irreversible state changes
- Batched A/B decisions per the queue pattern in
  `references/task-orchestration.md` (collect, advance, ask once when
  ALL tasks are blocked)
- Hard blockers — unrecoverable CI, missing credentials, merge
  conflicts requiring human judgment
- The single Plan Completion Gate at end of plan
- Documented gates that fire unconditionally (e.g. the merge-anyway
  override in `Dev10x:gh-pr-merge`)

**Detection signal:** if you are about to output "Ready to proceed to
the next step?", STOP. Skip the question and execute the step.

## Safety floors are deny-overrides

Floors force `ask` regardless of preset, overlay, or pin — the
resolver's `ALWAYS_ASK` equivalent, and why one auto-advancing
baseline is safe: `secret_access`, `destructive_irreversible`,
`cross_author_push`, `privacy_disclosure`, `blocking`, and
`supervisor_review` (below).

A floor can only ever force `ask`; nothing lifts one by asking for
more autonomy. That is what keeps `supervisor_review` a
**precondition** for merge autonomy and never a grant of it.

To mark a skill's own gate unconditional:

```markdown
**REQUIRED: Call `AskUserQuestion`** (ALWAYS_ASK — fires
unconditionally, never auto-advances).
```

## `supervisor_review`

One durable per-project key answering one question: *must the
supervisor read this PR before the next step is allowed?* It lives in
the matching `projects[]` entry of `~/.config/Dev10x/friction.yaml`.
Absent, unrecognised, or malformed values read as `required`, so every
unconfigured repo and every typo fails toward more oversight.

Which gate it floors follows repo shape (ADR-0022 D-3):

| repo | value | Behaviour |
|---|---|---|
| solo | `none` | AI self-review → CI → agent merges |
| solo | `required` | AI self-review → CI → **park** → merge |
| team | `none` | AI self-review → CI → agent requests team review |
| team | `required` | AI self-review → CI → **park** → request review |

- **AI self-review and CI always come first**, in all four cells, and
  neither is gateable (ADR-0022 D-4). The supervisor is never handed a
  PR the agent has not already reviewed and greened.
- **`required` inserts a park; it never removes a step.** In the team
  rows it precedes the team request rather than replacing it.
- **The `review:cleared` PR label lifts the floor** (GH-1008,
  GH-1163). `Dev10x:gh-pr-request-review` writes it once the
  supervisor has read the commits; `Dev10x:git-groom` removes it after
  a force-push, since a clearance cannot survive the rewrite that
  invalidated it.
- Read it with `mcp__plugin_Dev10x_cli__supervisor_review_status`,
  write it with `pin_supervisor_review`. The gate reads it
  **unconditionally** — a `supervisor_review` key passed in a
  `resolve_gate` context lands in `ignored_context_fields` (GH-1000),
  so no caller can self-authorise past the supervisor.

## Configuration

Durable prefs live in the global `~/.config/Dev10x/friction.yaml`,
first-match-wins by project glob (ADR-0018). Schema v2 carries no
`gate_preset` and no `friction_level`; see
`references/session-config-schema.md` for the key reference and the
`dev10x config migrate-schema` conversion.

```yaml
projects:
  - match: ["*/my-solo-repo", "*/my-solo-repo-*"]
    supervisor_review: none
    gate_overlays: [solo-maintainer]
    gate_overrides: {merge: ask}   # per-toggle pins still work
```

Toggle pins every teammate shares live in the git-tracked
`.dev10x/gate-policy.yaml` (ADR-0016 D-8). A `plan_approval: ask` or
`merge: ask` pin there is the supported way to make a gate fire that
the baseline would auto-advance.

## Completion is merge-gated (GH-729)

Completion is reserved for the **merged** state; "shippable" is not
terminal. The recommended — and, absent a floor, auto-selected —
option follows PR merge state: **Work complete** when merged or
PR-less, **Monitor for review** (→ `Dev10x:gh-pr-monitor`) when the PR
is open and green, **Go back** on any failing or pending check. The
merge signal is a **gate input, not a pass/fail check** — an
unmerged-but-green PR is the normal awaiting-review state, so a
failing "PR merged" check would loop on "Go back" forever. The matrix
is encoded once in
`dev10x.domain.session_rules.completion_gate_recommendation()`, which
`Dev10x:verify-acc-dod` and work-on's Plan Completion Gate defer to;
whether the gate *fires* is `resolve_gate(gate="completion_signoff")`.

## The other `friction_level`

`config.friction_level` in
`src/dev10x/validators/command-skill-map.yaml`, consumed by
`skill_redirect.py`, is the **ADR-0002 command-redirect axis**: how
hard the PreToolUse Bash hook pushes an agent from a raw CLI command
toward its skill wrapper. It constrains the *agent's tool choice*, not
the *supervisor's involvement*, and ADR-0022 does not touch it. It is
what enforces skill routing, on **every** iteration of a loop — no
gate posture relaxes it after the first pass.

## References

- [ADR-0022](../docs/adr/0022-single-baseline-gate-model-with-supervisor-review.md)
  — one baseline, `supervisor_review`, the D-3 effect table
- [ADR-0016](../docs/adr/0016-friction-gate-policy-presets-over-toggles.md)
  — resolver, toggle taxonomy, safety floors, D-7 visible record
- `references/session-config-schema.md` — schema v2 key reference
- `references/walk-away.md` — the `afk` overlay and `doubt_sink`
- `references/active-modes.md` — the non-gate `active_modes` consumers
- `references/execution-modes.md` — structural modes (orthogonal:
  gate policy decides *how a gate resolves*, modes *what steps exist*)
- `src/dev10x/domain/gate_policy.py` — `SHIPPED_PRESETS`, `_floors()`
