# Active Modes

Behaviors enabled by entries in the durable `active_modes:` list —
resolved from the global `~/.config/Dev10x/friction.yaml` per
[§ Resolution order](#resolution-order) below, not from the retired
per-repo session file (ADR-0018).

## `active_modes` does not decide gates

**`active_modes` has no gate-resolution role.** Whether an
`AskUserQuestion` fires is decided by `resolve_gate` alone, from the
baseline preset, the composed overlays, the project pin, and the
safety floors (ADR-0016 D-4, ADR-0022 D-1). A skill that reads
`active_modes` to derive a gate effect is re-deriving policy the
resolver owns, and it will drift.

What `active_modes` still feeds — its only remaining consumers:

1. **Structural skill behaviour** — the non-gate steps in the mode
   catalog below (draft state, reviewer assignment, Slack
   notification, milestone cleanup).
2. **`Dev10x:verify-acc-dod`'s check filter** — the
   `modes.<name>.skip` clauses in
   `skills/verify-acc-dod/references/defaults.yaml`.
3. **Playbook step `modes:` blocks** — which steps exist in a play
   (`references/execution-modes.md`).

Overlays and modes are separate lists with separate readers, and
nothing derives one from the other: an overlay-only entry leaves the
three consumers above seeing `[]`. Set both when a mode must reach
both surfaces. A config that still declares its posture through the
v1 keys is refused rather than translated —
`legacy_policy_keys()` in `src/dev10x/domain/gate_policy.py` names
the offending keys, and the migrator's own v1 readers in
`src/dev10x/domain/config_migration.py` convert them.

## Mode catalog

### `solo-maintainer`

Single-author repository with no team review workflow. PRs are
the maintainer's own and ship directly.

Documented behaviors:

- PRs ship ready-for-review (no draft state)
- No reviewer assignment — `Dev10x:gh-pr-request-review` is
  skipped
- No Slack review notification — `Dev10x:slack-review-request`
  is skipped
- `Dev10x:gh-pr-create` finishes with `pr_ready` instead of
  `gh pr create --draft`
- Auto-dispatch `Dev10x:gh-pr-monitor` after PR creation
- `Dev10x:gh-pr-merge` accepts solo-maintainer approval override
  (no second review required)
- Auto-merge with `--rebase` when CI is green and no unresolved
  review threads exist
- Auto-close milestone after PR merge if all milestone issues
  are resolved

Its **gate** effects travel through the `solo-maintainer` *overlay*
(`presets/friction/overlays/solo-maintainer.yaml`:
`request_review`/`external_notify: skip`, `merge: auto-advance`),
which the resolver composes onto the baseline — not through this
list. The overlay is also what declares the repo solo-shaped, which
is how `supervisor_review` knows to park before `merge` rather than
before `request_review` (ADR-0022 D-3).

When NOT to use: team repositories where PRs require external
review. The mode short-circuits the review cycle entirely.

### `auto-plan` — no longer adds anything

"Trust the plan" pacing for the plan-approval gate only (GH-678,
[ADR-0014](../docs/adr/0014-auto-plan-mode-for-plan-approval-gate.md)).

Auto-advance is now the baseline (ADR-0022 D-1), so `plan_approval`
already resolves to `auto-advance` without this mode. `auto-plan` is
retained as a read-compat name — naming it changes nothing and
breaks nothing — but it is not a way to express anything.

To keep the plan gate as a veto point, pin it: a
`plan_approval: ask` entry in the git-tracked
`.dev10x/gate-policy.yaml`, or a session `gate_overrides` entry.
That is the supported way to make a gate fire that the baseline
would auto-advance.

### `review-deferred` — DEPRECATED (ADR-0022)

> **Superseded by durable `supervisor_review` (GH-950, GH-1161).**
> Whether the supervisor reads the PR is a **standing project
> property**, not a per-session scope decision, so it lives as
> `supervisor_review: required | none` in the matching `projects[]`
> entry of `~/.config/Dev10x/friction.yaml` — read via
> `mcp__plugin_Dev10x_cli__supervisor_review_status`. See
> [ADR-0022](../docs/adr/0022-single-baseline-gate-model-with-supervisor-review.md)
> D-2, which renamed and generalised ADR-0019's `human_review`
> boolean.
>
> **Nothing writes `review-deferred` anymore.** The mode string is
> still *read* — the `skip` clauses below keep working when a playbook
> or a legacy `active_modes` list names it — so un-migrated repos and
> hand-edited playbooks are unaffected. There is no per-session
> deferral: to take the supervisor pass out of scope, set the durable
> key.

Documented behaviors:

- `Dev10x:verify-acc-dod` skips the **"No unresolved review threads"**
  check (the `modes.review-deferred.skip: true` clause in
  `skills/verify-acc-dod/references/defaults.yaml`)
- `Dev10x:verify-acc-dod` skips the **"Review requested" /
  "Re-review requested"** check
- The Plan Completion Gate then resolves honestly: with the deferred
  checks excluded, a green run recommends **Work complete** (merged /
  PR-less) or **Monitor for review** (open PR) instead of papering over
  a known-red check with gate framing (GH-736)

When NOT to use: when open review threads must be resolved before the
work is shippable. This mode records an explicit scope decision — it is
not a blanket "ignore reviews" switch.

## Resolution order

Active modes are resolved in this order (see
`references/execution-modes.md` for full precedence rules):

1. `active_modes:` in the durable gate policy — the first matching
   `projects[]` entry in the global `~/.config/Dev10x/friction.yaml`.
   A match wins outright.
2. Only when no entry matches: the legacy per-repo
   `.claude/Dev10x/config.yaml`, with a pre-split
   `.claude/Dev10x/session.yaml` fallback, so an un-migrated checkout
   keeps working until `dev10x config migrate-schema` folds it in.
3. `active_modes:` in the project playbook file (merged in).

Both per-repo files in step 2 are **retired** (ADR-0018) — they are a
read-compat fallback, never a write target.

### Not every posture is a mode (ADR-0022)

`review-deferred` used to be written into `active_modes` on the
retired `session.yaml`, which step 2 reaches only in an unconfigured
repo — so in a configured one it was written and never read (GH-950).
The fix was not a new store but a better model: the review posture is
one **durable, project-wide** key, `supervisor_review`, resolved by the
same first-match-wins precedence as step 1.

`swarm-child` is **not** affected. It is genuinely per-dispatch — a
worker either is or is not a swarm child, and the dispatcher sets it —
so it keeps its dispatch-time delivery rather than moving to a durable
project key.

When adding a mode, ask first whether the thing you are modelling is a
per-session structural choice (a mode) or a standing property of the
project (a durable key). A standing property written as a mode is the
GH-950 failure shape. And if what you are modelling is *when the agent
stops and asks*, it is neither — it is a gate toggle, and it belongs in
`gate_overrides` or a project pin.

## Adding a new mode

1. Document the mode's behaviors here under the catalog
2. Wire skill behavior changes in the relevant playbook
   (`skills/*/references/playbook.yaml`) via the
   `modes:` mapping pattern
3. Update `references/execution-modes.md` with any new
   precedence rules
4. If the mode needs a gate to resolve differently, add an **overlay**
   under `presets/friction/overlays/` and name it in `gate_overlays`
   — do not teach a skill to branch on `active_modes` at a gate

See `skills/work-on/instructions.md` § Session Mode Summary
(GH-189) for the supervisor-facing display contract.
