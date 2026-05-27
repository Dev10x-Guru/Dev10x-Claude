# Policy Rules Pattern

Architectural pattern for encapsulating named session decisions as
frozen dataclasses with an `apply()` method.

## What is a Policy Rule?

A Policy Rule is a stateless decision-maker that examines session
context and returns a value or guidance text. Multiple rules compose
into a session policy orchestrator.

**Pattern**:
```python
from dataclasses import dataclass

@dataclass(frozen=True)
class MyPolicyRule:
    """Encapsulates a named session decision.
    
    Fires when: <conditions>
    Returns: <type and example value>
    """
    
    def apply(self) -> str:
        # Examine context, return value or empty string
        return "..."
```

## When to Use Policy Rules

Use when:
- A session decision is **named and reusable** — multiple hooks or
  skills reference the same decision concept
- The logic is **independent** — does not require state mutations
  or side effects
- The result **informs other code** — other rules or hooks branch
  on the decision outcome

**Do NOT use** for:
- Stateful operations (use orchestrator steps instead)
- Side effects (file I/O, API calls — use orchestrator steps)
- Decisions that appear only once (use inline logic in the
  orchestrator instead)

## Structure

### Frozen Dataclass

The rule is a frozen dataclass to:
- Guarantee immutability (safe for caching/reuse)
- Enable type checking (static verification of constructor args)
- Document dependencies clearly (via dataclass fields)

```python
@dataclass(frozen=True)
class ReadFrictionLevelRule:
    """Reads friction_level from session.yaml."""
    project_root: Path
    
    def apply(self) -> str:
        ...
```

### apply() Method

The `apply()` method is the rule's only public interface:

- **Signature**: `def apply(self) -> <ReturnType>`
- **Return value**: Decision result (str, bool, dict, etc.)
- **Silence pattern**: Return empty string `""` when the rule
  does not fire (e.g., conditions not met, optional field missing)

### Testing

Each rule is tested in isolation:

```python
def test_reads_friction_level_when_present():
    rule = ReadFrictionLevelRule(project_root=Path("/tmp"))
    result = rule.apply()
    assert result in ("strict", "guided", "adaptive")

def test_silent_when_file_missing():
    rule = ReadFrictionLevelRule(project_root=Path("/nonexistent"))
    result = rule.apply()
    assert result == ""
```

## Re-Export Pattern

Rules are defined in `src/dev10x/hooks/session_policy.py` and
re-exported via `__all__` in `src/dev10x/hooks/session.py`:

**session_policy.py:**
```python
__all__ = ["ReadFrictionLevelRule", "BuildAutonomyReassuranceRule", ...]
```

**session.py:**
```python
from .session_policy import *  # Imports from __all__
```

This makes rules discoverable to orchestrators without tying the
policy module's internal organization to external imports.

## Composition in Orchestrators

Multiple rules compose into a session orchestrator. See the
`hooks/scripts/session-start.py` orchestrator pattern:

```python
@audit_hook(name="build_autonomy_reassurance_context", event="SessionStart")
def build_autonomy_reassurance_context(data: dict | None = None) -> str:
    rule = BuildAutonomyReassuranceRule(...)
    return rule.apply()
```

Each rule's result is collected and merged into the orchestrator's
final output.

## Fallback Consistency (Important)

**All policy rules must handle missing/malformed input gracefully:**

- If a rule depends on optional config, return `""` (silent) when
  config is missing
- If a rule depends on optional session state, return `""` when
  state file is missing or malformed
- **Never raise exceptions** — exceptions break the orchestrator

Example:

```python
def apply(self) -> str:
    try:
        config = yaml.safe_load(open(self.config_path))
    except FileNotFoundError:
        return ""  # Silent — this rule doesn't apply
    
    if config.get("friction_level") == "adaptive":
        return "Reassurance text"
    return ""
```

## Examples

See `src/dev10x/hooks/session_policy.py` for current implementations:

1. **`ReadFrictionLevelRule`** — Reads and returns `friction_level`
   from `session.yaml`
2. **`BuildAutonomyReassuranceRule`** — Returns reassurance text
   when adaptive + solo-maintainer is active
3. **`DecisionGuidanceRule`** — Returns guidance text tailored to
   the friction level
4. **`MigratePluginPermissionsRule`** — Guidance for permission
   migrations (one-time messages)

## Related Patterns

- **Hook-patterns.md** § "Direct-Shebang + Orchestrator Pattern"
  — SessionStart orchestrator consolidation
- **hook-state-schema.md** — Documenting state schemas that rules
  depend on (e.g., `session.yaml`)
- **task-orchestration.md** — Orchestration patterns for multi-step
  skills (similar composition idea)
