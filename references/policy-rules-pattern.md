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
class BuildAutonomyReassuranceRule:
    """Reassures the agent in adaptive + solo-maintainer sessions."""

    friction_level: FrictionLevel
    active_modes: list[str]

    def apply(self) -> str:
        ...
```

The rule receives already-loaded values as fields — the file read is
owned by `SessionYamlDocument` (see § Fallback Consistency), keeping the
rule free of I/O (ADR-0007 D3).

### apply() Method

The `apply()` method is the rule's only public interface:

- **Signature**: `def apply(self) -> <ReturnType>`
- **Return value**: Decision result (str, bool, dict, etc.)
- **Silence pattern**: Return empty string `""` when the rule
  does not fire (e.g., conditions not met, optional field missing)

### Testing

Each rule is tested in isolation:

```python
def test_fires_when_adaptive_and_solo():
    rule = BuildAutonomyReassuranceRule(
        friction_level=FrictionLevel.ADAPTIVE, active_modes=["solo-maintainer"]
    )
    assert rule.apply() != ""

def test_silent_when_not_adaptive():
    rule = BuildAutonomyReassuranceRule(
        friction_level=FrictionLevel.GUIDED, active_modes=["solo-maintainer"]
    )
    assert rule.apply() == ""
```

Because the rule holds plain values rather than a path, it is tested
fully in-memory — no temp files. The file-read fallbacks (missing /
malformed YAML) are tested on `SessionYamlDocument` instead.

## Re-Export Pattern

Pure session rules live in `src/dev10x/domain/session_rules.py`
(ADR-0008: they depend only on `domain/` types). Adapter-layer modules
re-export them for backward compatibility:

**domain/session_rules.py:**
```python
__all__ = ["DecisionGuidanceRule", "BuildAutonomyReassuranceRule", ...]
```

**hooks/session_policy.py** (compatibility re-export):
```python
from dev10x.domain.session_rules import (
    BuildAutonomyReassuranceRule,
    DecisionGuidanceRule,
)
```

This keeps the rules discoverable from their historical import path
without tying the domain module's organization to adapter imports.

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

- File reads are owned by a Document (e.g. `SessionYamlDocument`),
  which returns soft fallbacks (`FrictionLevel.default()`, empty
  modes) on a missing or malformed file — the rule performs no I/O
  (ADR-0007 D3)
- If a rule depends on optional config, return `""` (silent) when
  the resolved value does not meet its firing conditions
- **Never raise exceptions** — exceptions break the orchestrator

Example:

```python
# The file read + fallback live in the Document (ADR-0007 D3):
def read_friction_level(self) -> FrictionLevel:
    return FrictionLevel.from_yaml(self._load().get("friction_level"))

# The rule receives the resolved value and decides — no I/O:
def apply(self) -> str:
    if self.friction_level is FrictionLevel.ADAPTIVE:
        return "Reassurance text"
    return ""
```

## Examples

See `src/dev10x/domain/session_rules.py` for current Policy Rule
implementations (re-exported from `hooks/session_policy.py`):

1. **`BuildAutonomyReassuranceRule`** — Returns reassurance text
   when adaptive + solo-maintainer is active. Receives
   `friction_level` + `active_modes` as fields (no I/O).
2. **`DecisionGuidanceRule`** — Returns guidance text tailored to
   the friction level.
3. **`MigratePluginPermissionsRule`** — Guidance for permission
   migrations (`hooks/session_policy.py`; delegates file writes to
   `SettingsDocument`).

The `session.yaml` read those rules used to perform is owned by
`SessionYamlDocument` (`src/dev10x/domain/documents/session_yaml.py`).

## Related Patterns

- **Hook-patterns.md** § "Direct-Shebang + Orchestrator Pattern"
  — SessionStart orchestrator consolidation
- **hook-state-schema.md** — Documenting state schemas that rules
  depend on (e.g., `session.yaml`)
- **task-orchestration.md** — Orchestration patterns for multi-step
  skills (similar composition idea)
