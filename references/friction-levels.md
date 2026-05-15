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
~/.claude/memory/Dev10x/skill-reinforcement.yaml
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

## Acceptance Criteria (verify-acc-dod)

| Level | Automated checks | Manual checks | Decision gate |
|-------|-----------------|---------------|---------------|
| strict | Run, must all pass | AskUserQuestion per item | AskUserQuestion required |
| guided | Run, failures shown | AskUserQuestion per item | AskUserQuestion with recommendation |
| adaptive | Run, auto-pass/fail | Converted to `prompt` (Claude evaluates) | Auto-select "Work complete" if all pass |

At adaptive level, the ACC skill runs fully unattended:
1. Execute all automated checks
2. Convert `manual` checks to `prompt` checks (Claude evaluates
   from session context)
3. If all pass → auto-complete, no user interruption
4. If any fail → queue failure report, continue with next task

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

Skills read friction level and active modes from
`.claude/Dev10x/session.yaml`:

```yaml
friction_level: adaptive
active_modes: [solo-maintainer]
```

Resolution order: session override > project override > default.

The recommended approach:

1. **Hook-based enforcement** (preferred): The PreToolUse hook
   already reads friction_level and blocks/allows accordingly.
   Most skills don't need to read it directly.

2. **Skill-level awareness** (for gate behavior): Skills that
   modify their `AskUserQuestion` behavior based on friction
   level should read `.claude/Dev10x/session.yaml` and adapt.

3. **Playbook-level override**: Playbook steps can include
   `friction:` mappings to override the global setting
   for specific steps.

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

## References

- ADR-0002: Data-driven skill redirect with friction levels
- `references/execution-modes.md`: Structural modes (orthogonal)
- `src/dev10x/validators/command-skill-map.yaml`: Config source
- `src/dev10x/validators/skill_redirect.py`: Hook implementation
- `skills/verify-acc-dod/SKILL.md`: First skill-level adopter
