# Execution Modes — Per-Step Behavioral Adaptation

Declarative mode system for playbook steps. Modes control *what
steps exist and who is involved* independently of friction levels
(which control *how gates fire*).

## Problem

Execution modes are implemented inconsistently across skills:
- `gh-pr-create` detects `--unattended` + parent orchestrator context
- `jtbd` has attended/unattended code paths for draft approval
- `review` checks `--unattended` to skip findings presentation
- `git-commit` auto-skips review gate in unattended mode

Project overrides that want different behavior must fork entire
plays (~310 lines), causing drift when defaults improve.

## Design Principle: Orthogonal Dimensions

Friction levels and modes are **independent axes**:

|  | strict | guided | adaptive |
|---|---|---|---|
| **team** (default) | All gates block, reviewers required | Gates with recommendations | Auto-advance, reviewers auto-assigned |
| **solo-maintainer** | All gates block, no reviewer/Slack | Gates with recommendations, no reviewer | Auto-advance, no reviewer, self-merge |

**Friction level** = how gates behave (block, recommend, auto).
Adaptive friction covers AFK/unattended behavior — no separate
`afk` or `auto-advance` modes needed.

**Mode** = what steps exist and who is involved (structural).

## Mode Taxonomy

Modes are purely structural — they change *what* happens, not
*how aggressively* the agent proceeds. Pacing and gate behavior
belong to `friction_level` (strict/guided/adaptive).

| Mode | Intent | Replaces |
|------|--------|----------|
| `solo-maintainer` | No reviewer assignment, no Slack, self-merge | Project override prompt hints |
| `supervised` | Extra approval gates at design/PR/merge | Default attended behavior |
| `cautious` | Extra verification, confirm destructive ops | No current equivalent |
| `pair-review` | Human review at implementation checkpoints | No current equivalent |

**Not modes** (use friction_level instead):
- `afk` -> `friction_level: adaptive`
- `auto-advance` -> `friction_level: adaptive`
- `--unattended` -> `friction_level: adaptive`

## Configuration

### Session-level (set by Phase 0 of work-on/fanout)

```yaml
# .claude/Dev10x/session.yaml
friction_level: adaptive
active_modes: [solo-maintainer]
```

### Project-level (persistent across sessions)

```yaml
# ~/.claude/Dev10x/playbooks/work-on.yaml (global, preferred)
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

1. Session override (`.claude/Dev10x/session.yaml`)
2. Project override (`~/.claude/Dev10x/playbooks/<skill>.yaml`)
3. Default (no modes active)

## Per-Step Mode Mappings

Steps declare how they adapt under each mode:

```yaml
- subject: Draft Job Story
  type: detailed
  skills: [Dev10x:jtbd]
  modes:
    solo-maintainer:
      prompt: >
        Draft JTBD as a documentation artifact. Useful as
        an indicator of how well the agent understood the task.
  friction:
    adaptive:
      prompt: >
        Accept what the skill produces and auto-advance.
        No approval needed.

- subject: Request review
  type: detailed
  skills: [Dev10x:gh-pr-request-review]
  modes:
    solo-maintainer:
      subject: Mark PR ready for review
      prompt: >
        Run `gh pr ready`. No reviewers, no Slack.
  friction:
    adaptive:
      prompt: >
        Auto-assign reviewers from CODEOWNERS. No
        AskUserQuestion for reviewer selection.
```

### Mode Actions

| Action | Meaning |
|--------|---------|
| `skip` | Remove step when mode is active |
| `{subject, prompt, skills, ...}` | Override specific fields |
| (absent) | Step unchanged under this mode |

### Friction Actions (per-step)

Same actions as modes, declared under `friction:`:

| Action | Meaning |
|--------|---------|
| `skip: true` | Remove step at this friction level |
| `{prompt, subject, skills, ...}` | Override fields at this level |
| (absent) | Step unchanged at this level |

## Resolution Order

1. Load defaults from plugin `playbook.yaml`
2. Resolve fragments (existing behavior)
3. Apply active modes from session/project config:
   a. For each step, check if active modes define behavior
   b. Apply `skip` actions (remove steps)
   c. Apply field overrides (merge, not replace)
   d. Apply `mode_extensions` from project file (merge on top)
4. Apply friction-level adaptations (per-step `friction:`)
5. Apply `overrides` if present (full replacement, escape hatch)

Modes run before friction so mode-added steps can have their
own `friction:` mappings resolved in step 4.

## Mode Precedence

When multiple active modes conflict on the same step field:

- `skip` wins over any field override (if any active mode says
  skip, the step is removed)
- For field conflicts, last-listed mode in `active_modes` wins
- `mode_extensions` always win over default mode definitions

## Skill Integration

Skills read session config from `.claude/Dev10x/session.yaml`:

```yaml
# .claude/Dev10x/session.yaml
friction_level: adaptive
active_modes: [solo-maintainer]
```

Skills check `active_modes` for structural behavior:
- `solo-maintainer` in active_modes -> skip reviewer assignment
- `supervised` in active_modes -> add approval gates

Skills check `friction_level` for pacing behavior:
- `adaptive` -> auto-advance, skip non-ALWAYS_ASK gates
- `guided` -> present recommendations
- `strict` -> block for user input

The playbook resolver applies per-step mode and friction
mappings before task creation, so most skills receive
pre-adapted prompts and don't need detection at all.

## Matrix Interaction Examples

**solo-maintainer + adaptive** (AFK solo dev):
- "Draft Job Story" -> auto-draft, accept and advance (no approval)
- "Request review" -> "Mark PR ready" (mode: solo-maintainer)
- All gates auto-resolve (friction: adaptive)
- Auto-merge when CI green

**solo-maintainer + guided** (solo dev, checkpoints):
- "Draft Job Story" -> draft as doc artifact (mode: solo-maintainer)
- "Request review" -> "Mark PR ready" (mode: solo-maintainer)
- Gates present recommendations (friction: guided)

**team + adaptive** (team project, fast shipping):
- "Draft Job Story" -> auto-draft, accept and advance
- "Request review" -> auto-assign reviewers (friction: adaptive)
- Merge gate is ALWAYS_ASK regardless of friction

**team + strict** (regulated project):
- Every gate blocks for user input
- Reviewer assignment requires explicit selection
- Merge requires approval + all checks passing

## Migration from Ad-Hoc Patterns

| Current pattern | Maps to |
|----------------|---------|
| `--unattended` flag per skill | `friction_level: adaptive` |
| Auto-advance in task-orchestration.md | `friction_level: adaptive` |
| Solo-maintainer prompt hints | `active_modes: [solo-maintainer]` |
| "Draft Job Story" unattended mode | `friction: { adaptive: { prompt: "accept and advance" } }` |
| "Request review" -> "Mark PR ready" | `solo-maintainer` mode on step |
| Full play override (310 lines) | `active_modes: [solo-maintainer]` + `friction_level: adaptive` (2 lines) |

## References

- `references/friction-levels.md` — gate behavior per level
- `skills/playbook/references/playbook.yaml` — step schema
- `skills/playbook/SKILL.md` — playbook manager documentation
- `skills/work-on/SKILL.md` — Phase 3 mode resolution
