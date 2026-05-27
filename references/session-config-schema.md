# Session Configuration Schema

Schema for `.claude/Dev10x/session.yaml`, read by SessionStart hooks
to configure session behavior.

## File Location

```
~/.claude/Dev10x/session.yaml
```

This file is user-created and persists across sessions. It is not
auto-initialized; users create it when needed to customize friction
levels or activate session modes.

## Schema Definition

| Field | Type | Required | Default | Example |
|-------|------|----------|---------|---------|
| `friction_level` | string (enum) | Yes | `strict` | `adaptive` |
| `active_modes` | list of strings | Yes | `[]` | `[solo-maintainer, open-source]` |

### friction_level

Controls how often the agent pauses for user decisions.

| Value | Behavior |
|-------|----------|
| `strict` | Agent pauses frequently; asks confirmation before each major action. Recommended for collaborative work. |
| `guided` | Agent proceeds with confidence but pauses for significant architectural or policy decisions. |
| `adaptive` | Agent operates with high autonomy; pauses only when facing ambiguity that cannot be resolved by the current task context. Recommended for solo-maintainer mode. |

### active_modes

List of named modes that customize agent behavior. Known modes:

| Mode | Behavior | Set by |
|------|----------|--------|
| `solo-maintainer` | Skip reviewer assignment and Slack notifications. Agent assumes single owner and high autonomy. | User (set in session.yaml) |
| `open-source` | Prefer issue templates and public-safe language. Assume external contribution norms. | User (set in session.yaml) |
| `swarm-child` | Internal mode for fanout skill (GH-300+). Agent is part of a swarm and reports to orchestrator. | Skill (set by fanout orchestrator) |

Empty list is valid (no modes active).

## Readers (Consumers)

All readers are located in `src/dev10x/hooks/session_policy.py`:

1. **`ReadFrictionLevelRule`** (lines 80–101)
   - Reads `friction_level` field
   - Fallback: `"strict"` if missing or malformed
   - Sets context for `BuildAutonomyReassuranceRule` and `DecisionGuidanceRule`

2. **`BuildAutonomyReassuranceRule`** (lines 104–149)
   - Reads `friction_level` and `active_modes`
   - Fires only when: `friction_level == "adaptive"` AND `"solo-maintainer"` in `active_modes`
   - Fallback: Silent (returns empty string) if conditions not met
   - Output: Reassurance text displayed at SessionStart

3. **`DecisionGuidanceRule`** (lines 151+)
   - Reads `friction_level`
   - Provides guidance text tailored to the selected level

## Fallback Behavior

When fields are missing or malformed:

- **Missing `friction_level`**: Defaults to `"strict"`
- **Malformed `friction_level`** (not in enum): Defaults to `"strict"`, no error
- **Missing `active_modes`**: Defaults to `[]` (empty list, no modes active)
- **Malformed `active_modes`** (not a list): Treated as `[]`, no error
- **Missing entire file**: All defaults apply; session runs in default configuration

All readers handle missing/null fields gracefully — no exceptions are raised.

## Template

Users can create a minimal session.yaml:

```yaml
# ~/.claude/Dev10x/session.yaml
friction_level: adaptive
active_modes:
  - solo-maintainer
```

Or:

```yaml
friction_level: guided
active_modes:
  - open-source
```

## Testing

Verify session.yaml parsing in `tests/hooks/test_orchestrators.py`:

- Test case: `test_autonomy_reassurance_fires_when_adaptive_and_solo`
- Test case: `test_autonomy_reassurance_silent_when_not_adaptive`
- Test case: `test_autonomy_reassurance_silent_when_session_yaml_missing`
- Test case: `test_autonomy_reassurance_silent_when_session_yaml_malformed`

## Related Files

- `src/dev10x/domain/friction_level.py` — Friction level enum definition
- `src/dev10x/commands/init.py` — Template initialization
- Skills using `active_modes`: playbook, gh-pr-merge, gh-pr-monitor,
  git-commit, fanout, verify-acc-dod, review
