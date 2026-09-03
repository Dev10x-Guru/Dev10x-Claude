# Execution Modes — Per-Step Behavioral Adaptation

Declarative mode system for playbook steps. Modes control *what
steps exist and who is involved*. How a gate fires is not a
per-step axis — one baseline answers that for every step
(ADR-0022).

## Problem

Execution modes are implemented inconsistently across skills:
- `gh-pr-create` detects `--unattended` + parent orchestrator context
- `jtbd` has attended/unattended code paths for draft approval
- `review` checks `--unattended` to skip findings presentation
- `git-commit` auto-skips review gate in unattended mode

Project overrides that want different behavior must fork entire
plays (~310 lines), causing drift when defaults improve.

## Design Principle: Structure, Not Pacing

**Mode** = what steps exist and who is involved (structural).

Gate behavior is not a second axis to compose with: the single
shipped baseline covers AFK/unattended behavior, so no separate
`afk` or `auto-advance` mode is needed, and a step never restates
its pacing per level.

## Mode Taxonomy

Modes are purely structural — they change *what* happens, not
*how aggressively* the agent proceeds. Gate posture is baseline
policy plus overlays, resolved by `resolve_gate`.

| Mode | Intent | Replaces |
|------|--------|----------|
| `solo-maintainer` | No reviewer assignment, no Slack, self-merge | Project override prompt hints |
| `supervised` | Extra approval gates at design/PR/merge | Default attended behavior |
| `cautious` | Extra verification, confirm destructive ops | No current equivalent |
| `pair-review` | Human review at implementation checkpoints | No current equivalent |
| `auto-plan` | Auto-approve the plan gate only; downstream gates follow baseline policy | Unreachable friction cell (GH-678) |

### Gate-flipping modes (the `solo-maintainer` / `auto-plan` exception)

Most modes are *purely* structural. Two are not: `solo-maintainer`
and `auto-plan` change how the **plan-approval gate** resolves. This
is a deliberate, bounded exception — the plan gate is a single,
well-known gate, and expressing "trust the plan" as a mode lets it
compose with any gate overlay (auto-approve the plan, attend
everything else). `auto-plan` flips
*only* the plan gate; it never touches downstream gate pacing.

**ADR-0016 (GH-760):** the actual gate resolution now runs through
`resolve_gate` (`dev10x.domain.gate_policy`), not the former
`session_rules.plan_gate_auto_approves()` predicate. The
`solo-maintainer` effect lives in the `solo-maintainer` overlay
(`presets/friction/overlays/solo-maintainer.yaml`:
`request_review`/`external_notify: skip`, `merge: auto-advance`) and
the `plan_approval` posture lives in the shipped presets. These modes
still describe *intent* here; their gate effect is encoded as
preset/overlay data the resolver composes. See
[`friction-levels.md`](friction-levels.md) § Plan-Approval Gate and
[ADR-0014](../docs/adr/0014-auto-plan-mode-for-plan-approval-gate.md).

**Not modes** (composed as a preset or overlay instead):
- `afk` -> `gate_overlays: [afk]` on the baseline — the `afk`
  overlay carries `session_adoption`/`doubt_sink`
- `auto-advance` -> `gate_preset: adaptive`
- `--unattended` -> `gate_preset: adaptive`

## Configuration

### Durable, per-project (set by Phase 0 of work-on/fanout)

```yaml
# ~/.config/Dev10x/friction.yaml — ADR-0018 D1
defaults:
  active_modes: []
projects:
  - match: ["*/<repo>", "*/<repo>-*"]
    active_modes: [solo-maintainer]
```

The retired `.claude/Dev10x/session.yaml` is **not** a config source
(ADR-0018 D2; its remaining task-index role moved out of the repo in
D5). Writing prefs there costs a self-settings consent prompt and is
read only in a repo with no `friction.yaml` entry — so in any
configured repo the value was written and never read (GH-950).

### Project-level (persistent across sessions)

```yaml
# ~/.config/Dev10x/playbooks/work-on.yaml (global, preferred)
# or .claude/Dev10x/playbooks/work-on.yaml (project-local)
active_modes: [solo-maintainer]

mode_extensions:
  solo-maintainer:
    steps:
      "Create draft PR":
        prompt: >
          Always use --unattended. Never pause for PR preview.
```

### Resolution order

1. Project entry in `~/.config/Dev10x/friction.yaml` (first match wins)
2. Project override (`~/.config/Dev10x/playbooks/<skill>.yaml`)
3. `defaults:` block in `friction.yaml`
4. Default (no modes active)

## Per-Step Mode Mappings

Steps declare how they adapt under each mode:

```yaml
- subject: Draft Job Story
  type: detailed
  skills: [Dev10x:jtbd]
  prompt: >
    Accept what the skill produces and auto-advance.
    No approval needed.
  modes:
    solo-maintainer:
      prompt: >
        Draft JTBD as a documentation artifact. Useful as
        an indicator of how well the agent understood the task.

- subject: Request review
  type: detailed
  skills: [Dev10x:gh-pr-request-review]
  prompt: >
    Auto-assign reviewers from CODEOWNERS. No
    AskUserQuestion for reviewer selection.
  modes:
    solo-maintainer:
      subject: Mark PR ready for review
      prompt: >
        Run `gh pr ready`. No reviewers, no Slack.
```

### Mode Actions

| Action | Meaning |
|--------|---------|
| `skip` | Remove step when mode is active |
| `{subject, prompt, skills, ...}` | Override specific fields |
| (absent) | Step unchanged under this mode |

There is no per-step friction key. With one baseline, a step's
pacing is not a variable — the step's own `prompt` states what it
does, once.

## Resolution Order

1. Load defaults from plugin `playbook.yaml`
2. Resolve fragments (existing behavior)
3. Apply active modes from session/project config:
   a. For each step, check if active modes define behavior
   b. Apply `skip` actions (remove steps)
   c. Apply field overrides (merge, not replace)
   d. Apply `mode_extensions` from project file (merge on top)
4. Apply `overrides` if present (full replacement, escape hatch)

## Mode Precedence

When multiple active modes conflict on the same step field:

- `skip` wins over any field override (if any active mode says
  skip, the step is removed)
- For field conflicts, last-listed mode in `active_modes` wins
- `mode_extensions` always win over default mode definitions

## Skill Integration

Skills read the resolved prefs from the matching `projects[]` entry
of `~/.config/Dev10x/friction.yaml` (see § Configuration). Prefer
`mcp__plugin_Dev10x_cli__resolve_gate` over reading the file: it owns
the preset / overlay / project-pin / safety-floor precedence, and
re-deriving that from raw keys drifts.

Skills check `active_modes` for structural behavior:
- `solo-maintainer` in active_modes -> skip reviewer assignment
- `supervised` in active_modes -> add approval gates

Pacing is not something a skill selects: the baseline
auto-advances and skips every gate that is not ALWAYS_ASK, and
`resolve_gate` is the only reader of that policy.

The playbook resolver applies per-step mode mappings before
task creation, so most skills receive pre-adapted prompts and
don't need detection at all.

## Mode Interaction Examples

**solo-maintainer** (solo dev):
- "Draft Job Story" -> auto-draft, accept and advance (no approval)
- "Request review" -> "Mark PR ready" (mode: solo-maintainer)
- Auto-merge when CI green

**no modes active** (team project):
- "Draft Job Story" -> auto-draft, accept and advance
- "Request review" -> auto-assign reviewers from CODEOWNERS
- Merge gate is ALWAYS_ASK

**supervised** (team project, extra checkpoints):
- "Draft Job Story" -> presented for approval before it is written
- "Code review" -> findings presented before auto-fixing
- Merge requires approval + all checks passing

**auto-plan** (trust the plan, attend the calls — GH-678):
- Plan-approval gate -> auto-approved, execution starts
- Merge gate is ALWAYS_ASK regardless -> fires
- Net: no babysitting the plan gate; hand stays on every judgment call

## Migration from Ad-Hoc Patterns

| Current pattern | Maps to |
|----------------|---------|
| `--unattended` flag per skill | baseline gate policy |
| Auto-advance in task-orchestration.md | baseline gate policy |
| Solo-maintainer prompt hints | `active_modes: [solo-maintainer]` |
| "Draft Job Story" unattended mode | the step's own `prompt: "accept and advance"` |
| "Request review" -> "Mark PR ready" | `solo-maintainer` mode on step |
| Full play override (310 lines) | `active_modes: [solo-maintainer]` (1 line) |

## References

- `references/friction-levels.md` — gate behavior
- `skills/playbook/references/playbook.yaml` — step schema
- `skills/playbook/SKILL.md` — playbook manager documentation
- `skills/work-on/SKILL.md` — Phase 3 mode resolution
