---
name: Dev10x:friction-setup
description: >
  Guide the supervisor through setting a project's friction / autonomy
  preferences via a blocking AskUserQuestion walk (preset -> overlays ->
  per-gate deviations -> skippable steps), then persist the choices to the
  global ~/.config/Dev10x/friction.yaml (gate axis) and
  ~/.config/Dev10x/playbooks/<skill>.yaml (playbook axis) so the resolver
  stops silently falling back to a preset the supervisor never chose.
  TRIGGER when: SessionStart nudges that this project is unconfigured, or the
  user says "configure friction", "set up autonomy", "friction setup", or
  wants to change a project's gate posture deliberately.
  DO NOT TRIGGER when: only flipping walk-away mode for one session (use
  Dev10x:afk), or bootstrapping a brand-new install (use dev10x init --setup).
user-invocable: true
invocation-name: Dev10x:friction-setup
allowed-tools:
  - AskUserQuestion
  - Bash(uvx dev10x session pin:*)
  - Bash(dev10x session pin:*)
  - Bash(uvx dev10x session set-friction:*)
  - Bash(dev10x session set-friction:*)
  - Bash(uvx dev10x session set-playbook:*)
  - Bash(dev10x session set-playbook:*)
---

**Announce:** "Using Dev10x:friction-setup to configure this project's friction preferences."

# Dev10x:friction-setup — Guided per-project friction setup

Walks the supervisor through an explicit choice of autonomy posture and
**writes only the deviations** to two global, gate-free files (ADR-0018):

| Axis | File | Keys written |
|------|------|--------------|
| Gate | `~/.config/Dev10x/friction.yaml` (`projects[]` entry) | `gate_preset`, `gate_overlays`, `gate_overrides` |
| Playbook | `~/.config/Dev10x/playbooks/<skill>.yaml` | `active_modes`, per-step `skip` |

Both writes go through `dev10x session pin` / `set-playbook`, which
lock + atomically write (GH-827 / ADR-0011) — this skill never edits the YAML
with the Write tool. Nothing is written under the repo's `.claude/`, so Claude
Code's self-settings gate never fires (GH-812).

**Write-only-on-completion contract.** A write happens **only** when the
supervisor completes the walk with a real choice. Dismissing / cancelling any
REQUIRED gate aborts with **no write** — the SessionStart nudge simply fires
again next session (skip = retry; a real choice = never re-prompt).

## Orchestration

**REQUIRED: Create a task at invocation.** Execute at startup:

1. `TaskCreate(subject="Configure project friction preferences", activeForm="Configuring friction")`

Then walk the gates below in order. Mark the task `completed` only after the
persist step returns (or `pending` with a note if the supervisor dismisses).

## The guided walk

### Gate 1 — Preset (REQUIRED)

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text). This blocks until
the supervisor responds; a dismissal aborts with no write. Options:

- **guided (Recommended)** — mechanical pipeline auto-advances through
  self-review; team interactions + merge stay human.
- **strict** — every gate fires; nothing auto-advances.
- **adaptive** — full walk-away, merges included.

### Gate 2 — Overlays (REQUIRED)

**REQUIRED: Call `AskUserQuestion`** with `multiSelect: true`. Overlays patch
the preset. Options:

- **None (Recommended)** — preset stands alone.
- **solo-maintainer** — skip reviewer assignment + external notify; auto-merge.
- **afk** — adopt the persisted session even when stale; route mid-flight
  doubts to the PR description.

### Gate 3 — Per-gate deviations (REQUIRED gate; per-gate follow-ups optional)

**REQUIRED: Call `AskUserQuestion`** — "Override any individual gates, or keep
the preset defaults?" Options: **Keep preset defaults (Recommended)** /
**Override specific gates**. Only when the supervisor picks *Override* do you
ask, per chosen gate, for `ask` / `auto-advance` / `skip`, and collect each as
a `--gate-override <toggle>=<value>` pair. The 17 gates:

`plan_approval`, `batch_layout`, `strategy_choice`, `artifact_preview`,
`triage_response`, `thread_resolution`, `comment_hide`, `yagni_routing`,
`shipping_continuation`, `request_review`, `external_notify`, `merge`,
`completion_signoff`, `history_rewrite`, `workspace_choice`, `branch_cleanup`,
`session_adoption`.

Write **only** the gates that deviate from the preset — an unchanged gate must
never appear in `gate_overrides`.

### Gate 4 — Skippable steps (REQUIRED)

**REQUIRED: Call `AskUserQuestion`** with `multiSelect: true` — "Always skip
any optional play steps for this project?" Options:

- **None (Recommended)** — run every play step.
- **Draft Job Story (JTBD)** — skip the `Dev10x:jtbd` step in the work-on play.

Selected steps become `--skip-step "<subject>"` on `set-playbook`; any enabled
overlay that is also a structural mode becomes `--mode <name>`.

## Persist (only on genuine completion)

**REQUIRED: Execute these steps in order, only after all four gates
completed with real choices.** Both commands accept `--path <dir>` (defaults
to CWD) and are idempotent — a re-run replaces this project's entry rather
than appending. If any REQUIRED gate was dismissed, do NOT run either write.

1. Gate-axis write (always, once a preset was chosen): `uvx dev10x session
   pin <preset> [--overlay <o>]... [--gate-override <t>=<v>]...`. `pin` keys
   the entry off the **repo stem** resolved from the git common dir, so a walk
   run inside worktree `<repo>-3` configures `<repo>` and every present or
   future worktree of it (GH-855) — add `--scope repo-only` / `--scope dir` if
   the supervisor asked to narrow it. Use `set-friction --path <dir>` instead
   only when configuring a *different* checkout than the CWD; it keys off that
   literal path and so does not span worktrees.
2. Playbook-axis write **only if** Gate 4 selected steps or an overlay mode
   applies: `uvx dev10x session set-playbook --skill work-on [--mode <m>]...
   [--skip-step "<subject>"]...`. Skip this step entirely when no steps were
   selected and no structural overlay applies.
3. `TaskUpdate(taskId, status="completed")` and print a one-line summary: the
   preset, any overlays, the deviating gates, and any skipped steps written.

## Anti-Patterns

- **Writing on dismissal.** If the supervisor cancels a REQUIRED gate, abort
  with no write — do not persist a partial choice. Skip = retry next session.
- **Editing the YAML directly.** Never Write/Edit `friction.yaml` or the
  playbook file — always go through the CLI so the lock + atomic write hold.
- **Recording non-deviations.** Only gates that differ from the preset belong
  in `gate_overrides`; copying the whole preset in defeats the point.
- **Confusing with `Dev10x:afk`.** `afk` flips one session to walk-away;
  this skill sets a *durable, per-project* posture.
