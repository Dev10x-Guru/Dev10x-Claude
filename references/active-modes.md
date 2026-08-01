# Active Modes

Behaviors enabled by entries in
`.claude/Dev10x/session.yaml` → `active_modes:`.

Modes layer on top of the `friction_level`. The friction level
controls how gates fire; modes change *what* skills decide at
those gates and which steps execute unattended.

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
- `Dev10x:gh-pr-create` finishes with `gh pr ready` instead of
  `gh pr create --draft`
- Auto-dispatch `Dev10x:gh-pr-monitor` after PR creation
- `Dev10x:gh-pr-merge` accepts solo-maintainer approval override
  (no second review required)
- Auto-merge with `--rebase` when CI is green and no unresolved
  review threads exist
- Auto-close milestone after PR merge if all milestone issues
  are resolved
- Plan-approval and merge gate behavior is resolved by
  `resolve_gate` (ADR-0016), not by re-deriving it from
  `active_modes`. The gate effects are encoded in the
  `solo-maintainer` overlay
  (`presets/friction/overlays/solo-maintainer.yaml`:
  `request_review`/`external_notify: skip`, `merge: auto-advance`),
  which the resolver composes onto the session's base preset. The
  former `adaptive+solo-maintainer` plan-gate bypass (GH-252) is
  subsumed by that composition — `solo-maintainer` remains a
  session mode for the *structural* behaviors above, and its gate
  effect travels through the overlay

When NOT to use: team repositories where PRs require external
review. The mode short-circuits the review cycle entirely.

### `auto-plan`

"Trust the plan" pacing for the plan-approval gate only (GH-678).
The supervisor wants execution to start on the agent's plan without
an approval click, but keeps the *downstream* judgment calls
attended.

Documented behaviors:

- `Dev10x:work-on` Phase 3 plan-approval gate is **auto-approved** —
  execution starts immediately on the agent's plan, no
  `AskUserQuestion` widget for plan sign-off
- Downstream decision gates (design forks, A/B choices, strategy
  selection, batch layout) **still fire per `friction_level`** —
  `auto-plan` does NOT auto-resolve them. Pair with
  `friction_level: guided` for the canonical "attend the judgment
  calls" behavior
- `ALWAYS_ASK` gates fire unchanged
- The Plan Completion Gate still fires for end-state sign-off
- Composes with other modes without re-enabling reviewers, Slack, or
  self-merge — `auto-plan` touches only the plan gate. Under
  `solo-maintainer`, the existing `adaptive+solo-maintainer` bypass
  (GH-252) already covers the plan gate, so adding `auto-plan` there
  is a no-op

Scope nuance: this is a mode that flips a gate's resolution, which
mildly bends the "modes are purely structural" taxonomy in
`references/execution-modes.md`. The precedent is `solo-maintainer`,
which already flips the same gate under adaptive. See
[ADR-0014](../docs/adr/0014-auto-plan-mode-for-plan-approval-gate.md).

When NOT to use: when you also want downstream gates to auto-resolve
(use `friction_level: adaptive` instead) or when you want to keep the
plan gate as a veto point (omit `auto-plan`).

### `review-deferred`

The supervisor has explicitly scoped the session to **defer** open PR
review threads — e.g. "land the CI fix only, leave the review comments
for a follow-up". The review workflow is out of scope for *this*
session, so the definition-of-done must not stay red on review-thread
criteria the supervisor agreed to skip.

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
not a blanket "ignore reviews" switch. Set it only when the supervisor
has deferred review threads for the current session.

## Resolution order

Active modes are resolved in this order (see
`references/execution-modes.md` for full precedence rules):

1. `active_modes:` in the durable gate policy — the first matching
   `projects[]` entry in the global `~/.config/Dev10x/friction.yaml`.
   A match wins outright.
2. Only when no entry matches: the legacy per-repo
   `.claude/Dev10x/config.yaml`, with a pre-split
   `.claude/Dev10x/session.yaml` fallback, so an un-migrated checkout
   keeps working until `dev10x permission migrate-config` folds it in.
3. `active_modes:` in the project playbook file (merged in).

Both per-repo files in step 2 are **retired** (ADR-0018) — they are a
read-compat fallback, never a write target.

> **Known gap (GH-950).** Ephemeral modes (`review-deferred`,
> `swarm-child`) have no post-ADR-0018 home. Their writers still target
> the deleted `session.yaml`, which step 2 reaches only in an
> unconfigured repo — so in a configured one the mode is written and
> never read. GH-950 picks the ephemeral store and rewires both ends.

## Adding a new mode

1. Document the mode's behaviors here under the catalog
2. Wire skill behavior changes in the relevant playbook
   (`skills/*/references/playbook.yaml`) via the
   `modes:` mapping pattern
3. Update `references/execution-modes.md` with any new
   precedence rules
4. Cross-link from `references/friction-levels.md` if the mode
   changes gate behavior beyond the friction level alone

See `skills/work-on/instructions.md` § Session Mode Summary
(GH-189) for the supervisor-facing display contract.
