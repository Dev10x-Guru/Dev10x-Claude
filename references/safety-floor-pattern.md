# Safety Floor Pattern for Deny Rules

When implementing allow/deny overlays, suppressions, or permission catalogs:

**Denies are the safety floor.** Suppressions or user overrides may never
remove a deny rule, even if explicitly requested. This ensures safety
guarantees are never weakened by mistake or policy update.

## Implementation Pattern

1. **Track problematic suppressions separately** — Identify which suppressions
   name shipped (base) deny rules. Do not apply them.
2. **Log explicitly** — Warn the user when they attempt to suppress a base
   deny. Make it visible, never silent.
3. **Test the refusal** — Use a test class (e.g., `TestDenySuppressionIsRefused`)
   that verifies base denies survive suppression attempts.

**Example test pattern:**
```python
class TestDenySuppressionIsRefused:
    def test_cannot_suppress_shipped_deny(self):
        shipped = {"denies": ["destructive-op-deny"]}
        user = {"suppressions": ["destructive-op-deny"]}
        merged = merge_catalogs(shipped, user)
        assert "destructive-op-deny" in merged["denies"]
        assert "destructive-op-deny" not in merged["suppressions"]
```

## Why This Matters

**GH-925 E6 finding**: An agent attempted to justify bypassing a
destructive operation (high-risk command) by claiming false reasoning. The
deny rule protecting that operation should not be suppressible — if an
agent or user wants to bypass a safety rule, that requires explicit
decision-making, not silent suppression.

Treating denies as a floor ensures:
- Safety invariants are not accidentally weakened by config merges
- Admin-configured safeguards survive user customization
- Permission drift is always explicit and logged

## Scope

This pattern applies to:
- Permission catalogs (ADR-0021, GH-912)
- User suppressions and overlays (GH-925 A3.3)
- Any system where lower-privilege users can customize higher-privilege policy

Do NOT apply to allow-rule suppressions — those are user-owned and can be
disabled freely.
