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
- `Dev10x:work-on` Phase 3 plan-approval gate is bypassed under
  `adaptive+solo-maintainer` (GH-252) — the friction profile
  already resolves to a clear default

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

## Resolution order

Active modes are resolved in this order (see
`references/execution-modes.md` for full precedence rules):

1. `active_modes:` in `.claude/Dev10x/session.yaml` (session)
2. `active_modes:` in the project playbook file (merged in)

The session list is authoritative once written — the playbook
list extends it but does not overwrite non-empty session values.

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
