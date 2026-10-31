---
name: dev10x:friction-setup
description: >
  Guide the supervisor through the one question the model needs — does the
  supervisor read the PR before the next step is allowed? — via a blocking
  AskUserQuestion gated on `pinned: false`, plus the existing solo-vs-team
  overlay / per-gate-deviation / skippable-step walk, then persist the
  choices to the global ~/.config/Dev10x/friction.yaml (gate axis) and
  ~/.config/Dev10x/playbooks/<skill>.yaml (playbook axis) so the resolver
  stops silently falling back to a posture the supervisor never chose.
  TRIGGER when: SessionStart nudges that this project is unconfigured, or the
  user says "configure friction", "set up autonomy", "friction setup", or
  wants to change a project's review posture deliberately.
  DO NOT TRIGGER when: only flipping walk-away mode for one session (use
  dev10x:afk), or bootstrapping a brand-new install (use dev10x init --setup).
user-invocable: true
invocation-name: dev10x:friction-setup
allowed-tools:
  - AskUserQuestion
  - mcp__plugin_dev10x_cli__supervisor_review_status
  - mcp__plugin_dev10x_cli__pin_supervisor_review
  - mcp__plugin_dev10x_cli__resolve_gate
  - Bash(uvx dev10x session pin:*)
  - Bash(dev10x session pin:*)
  - Bash(uvx dev10x session set-friction:*)
  - Bash(dev10x session set-friction:*)
  - Bash(uvx dev10x session set-playbook:*)
  - Bash(dev10x session set-playbook:*)
---

**Announce:** "Using dev10x:friction-setup to configure this project's friction preferences."

# dev10x:friction-setup — Guided per-project friction setup

Walks the supervisor through the single review-policy question (ADR-0022) —
plus the existing solo-vs-team overlay and any per-gate deviations — and
**writes only the deviations** to two global, gate-free files (ADR-0018):

| Axis | File | Keys written |
|------|------|--------------|
| Review policy | `~/.config/Dev10x/friction.yaml` (`projects[]` entry) | `supervisor_review` |
| Gate | `~/.config/Dev10x/friction.yaml` (`projects[]` entry) | `gate_overlays`, `gate_overrides` |
| Playbook | `~/.config/Dev10x/playbooks/<skill>.yaml` | `active_modes`, per-step `skip` |

`adaptive` is the sole shipped baseline preset (ADR-0022 D-1) — there is no
preset to choose, so nothing here asks for one. All writes go through
`mcp__plugin_dev10x_cli__pin_supervisor_review` / `dev10x session pin` /
`set-playbook`, which lock + atomically write (GH-827 / ADR-0011) — this
skill never edits the YAML with the Write tool. Nothing is written under the
repo's `.claude/`, so Claude Code's self-settings gate never fires (GH-812).

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

### Gate 1 — Review policy (REQUIRED, gated on `pinned: false`)

Call `mcp__plugin_dev10x_cli__supervisor_review_status()` first. This is the
**first-pick condition** (mirrors `preset_pin_status` for the old preset
gate): only when it returns `pinned: false` does the question below fire.
`pinned: true` means a `projects[]` entry already answers this for the repo
— adopt the resolved `supervisor_review` value silently and do NOT ask;
re-asking on every invocation is exactly the friction this gate exists to
remove.

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text) — "Does the
supervisor read the PR before it moves on?" This blocks until the supervisor
responds; a dismissal aborts with no write. Options:

- **Yes — the supervisor reviews first (Recommended)** —
  `supervisor_review=required`. In a solo repo the park lands before merge;
  in a team repo it lands before teammates are asked to review (ADR-0022
  D-3). This is the safe default and matches an unset value.
- **No — the agent ships it** — `supervisor_review=none`. AI self-review and
  CI still run in every case (ADR-0022 D-4) — this only removes the
  supervisor's own park.

This is the **entire replacement for preset selection**. There is no
`strict` / `guided` / `adaptive` choice to make — `adaptive` is the sole
shipped baseline (ADR-0022 D-1) and every gate auto-advances unless a floor,
a project pin, or a per-toggle override says otherwise. The existing
solo-vs-team question below (Gate 2) is what decides *where* the
`supervisor_review: required` park lands — it is not a duplicate of this
gate.

### Gate 2 — Overlays (REQUIRED)

**REQUIRED: Call `AskUserQuestion`** with `multiSelect: true`. Overlays patch
the adaptive baseline. Options:

- **None (Recommended)** — the baseline stands alone.
- **solo-maintainer** — skip reviewer assignment + external notify; auto-merge.
- **afk** — adopt the persisted session even when stale; route mid-flight
  doubts to the PR description.

### Gate 3 — Per-gate deviations (REQUIRED gate; per-gate follow-ups optional)

**REQUIRED: Call `AskUserQuestion`** (call spec:
[ask-gate-overrides.md](./tool-calls/ask-gate-overrides.md)) — "Should any
decision point stop and ask you, or be skipped, instead of following the
adaptive baseline?" Options: **Keep baseline (Recommended)** — the agent
continues through every gate except safety floors and the Gate 1 review
choice / **Customize gates** — gates set to ask, auto-advance or skip, saved
per repo and its worktrees, changeable by re-running this skill. Before
asking, resolve each gate's current value with
`mcp__plugin_dev10x_cli__resolve_gate` and show it in the option `preview`,
grouped (planning, review/PR, merge/history, session) as the spec describes.
Only on *Customize gates* do you ask, per chosen gate, for `ask` /
`auto-advance` / `skip`, collecting each as `--gate-override <toggle>=<value>`.
The 17 gates and their grouping are listed in the call spec.

Write **only** the gates that deviate from the baseline — an unchanged gate
must never appear in `gate_overrides`.

### Gate 4 — Skippable steps (REQUIRED)

**REQUIRED: Call `AskUserQuestion`** with `multiSelect: false` — "Should the
agent skip any optional play steps for this project?" Options:

- **No — run every step (Recommended)** — nothing is saved.
- **Yes — choose steps to skip** — saved per repo; re-run this skill to undo.

Only on *Yes*, **REQUIRED: Call `AskUserQuestion`** with `multiSelect: true`
(no "None" checkbox) listing the skippable steps, each stating what it
produces and what happens without it:

- **Draft Job Story (JTBD)** — produces the `dev10x:jtbd` Job Story that
  opens the PR body. Without it the agent opens PRs with no Job Story, and the
  PR-hygiene check may flag the body. Persists for this repo.

Selected steps become `--skip-step "<subject>"` on `set-playbook`; any enabled
overlay that is also a structural mode becomes `--mode <name>`.

## Persist (only on genuine completion)

**REQUIRED: Execute these steps in order, only after every gate that fired
completed with a real choice.** All writes are idempotent — a re-run
replaces this project's entry rather than appending. If any REQUIRED gate
was dismissed, do NOT run any write.

1. Review-policy write **only if Gate 1 actually asked** (i.e.
   `supervisor_review_status` returned `pinned: false` and the supervisor
   answered): `mcp__plugin_dev10x_cli__pin_supervisor_review(value=
   "required"|"none")`. Skip this call entirely when Gate 1 was skipped
   because the repo was already pinned — there is nothing new to persist.
2. Gate-axis write **only if Gate 2, 3, or 4 produced a real overlay,
   override, or skip**: `uvx dev10x session pin adaptive [--overlay <o>]...
   [--gate-override <t>=<v>]...`. `adaptive` is the sole shipped baseline
   (ADR-0022 D-1), so it is never itself a choice — this call exists only to
   carry overlays/overrides. `pin` keys the entry off the **repo stem**
   resolved from the git common dir, so a walk run inside worktree
   `<repo>-3` configures `<repo>` and every present or future worktree of it
   (GH-855) — add `--scope repo-only` / `--scope dir` if the supervisor
   asked to narrow it. Use `set-friction --path <dir>` instead only when
   configuring a *different* checkout than the CWD; it keys off that literal
   path and so does not span worktrees.
3. Playbook-axis write **only if** Gate 4 selected steps or an overlay mode
   applies: `uvx dev10x session set-playbook --skill work-on [--mode <m>]...
   [--skip-step "<subject>"]...`. Skip this step entirely when no steps were
   selected and no structural overlay applies.
4. `TaskUpdate(taskId, status="completed")` and print a one-line summary: the
   review policy, any overlays, the deviating gates, and any skipped steps
   written.

## Anti-Patterns

- **Writing on dismissal.** If the supervisor cancels a REQUIRED gate, abort
  with no write — do not persist a partial choice. Skip = retry next session.
- **Editing the YAML directly.** Never Write/Edit `friction.yaml` or the
  playbook file — always go through the CLI/MCP tools so the lock + atomic
  write hold.
- **Re-asking a pinned review policy.** Once `supervisor_review_status`
  reports `pinned: true`, never fire Gate 1 again — adopt the resolved value
  silently.
- **Offering a preset choice.** There is no `strict` / `guided` / `adaptive`
  picker any more (ADR-0022 D-1) — do not reintroduce one.
- **Recording non-deviations.** Only gates that differ from the baseline
  belong in `gate_overrides`; copying every gate in defeats the point.
- **Confusing with `dev10x:afk`.** `afk` flips one session to walk-away;
  this skill sets a *durable, per-project* posture.
