# 7. Rule/Policy archetype unification

Date: 2026-05-31

## Status

Accepted

## Context

The architecture audit (`docs/memos/005-2026-05-18-architecture-audit.md`
§ 7, cross-phase convergence) found **three parallel "rule"
abstractions** in the codebase, each named with "Rule" or acting as a
rule, with no documented relationship between them. New contributors
cannot tell which one to reach for, and the policy tier silently mixes
decision logic with file I/O.

### Current State

| Archetype | Location | Shape | Lifecycle |
|-----------|----------|-------|-----------|
| **Matching Rule** (data) | `domain/rules/validation_rule.py::Rule` | Frozen dataclass: patterns + `matches_command()` / `matches_file()` predicates | Loaded from YAML, iterated by `RuleEngine` |
| **Policy Rule** | `hooks/session_policy.py::*Rule` | Frozen dataclass with `apply() -> T`; encapsulates one named decision | Instantiated per-call, `apply()`d once |
| **Validator** | `validators/base.py::Validator(Protocol)` | `should_run()` + `validate()` (+ optional `correct()`) | Lazy-loaded into a profile-filtered `ValidatorChain` |

The Policy Rule tier (`ReadFrictionLevelRule`,
`DecisionGuidanceRule`, `MigratePluginPermissionsRule`,
`BuildAutonomyReassuranceRule`) all expose `apply()`, but nothing
declares that as a contract — it is "true by reading the source".

### Problems

1. **No named hierarchy (A9).** Three mechanisms, all called "rule"
   in conversation, with no documentation of when each applies.
   Behavioral dispatch (`if/elif` chains in `analyze_actions.py`,
   `session_policy.py`, `skill_redirect.py`) reinvents selection
   instead of leaning on any of them.
2. **Untyped policy contract (A9).** The `*Rule` policy classes share
   the `apply()` shape by convention only. A new policy that forgets
   `apply()`, or names it `run()`, is caught by neither the type
   checker nor a Protocol.
3. **Policy logic doing I/O (D3).**
   `MigratePluginPermissionsRule.apply()` reads, parses, mutates and
   atomically rewrites `settings.json` / `settings.local.json`
   itself. A "decision" object is doing file persistence — the same
   anti-pattern the Document layer (`domain/documents/`) exists to
   prevent. This makes the rule hard to unit-test without a real
   filesystem and blurs the policy/persistence boundary.

### Prerequisites

This ADR must be accepted **before** the A9 + D3 implementation
lands — introducing `PolicyRule(Protocol)` and extracting
`SettingsDocument` reshapes the policy tier's public contract.
Tracked by GH-244 (Audit-2026-05-18 Milestone 5). Source:
`docs/memos/005-2026-05-18-architecture-audit.md` § 7 and §
"ADR Candidates" (A9 + D3 + F4).

## Decision

We **formalise the three archetypes** rather than collapse them — they
have genuinely different shapes and lifecycles — and we **codify the
Policy Rule contract** with a Protocol plus an I/O-free invariant.

### The Three Archetypes (documented hierarchy)

1. **Matching Rule** — declarative *data*. A pattern set plus pure
   predicates (`matches_*`). Carries no side effects and no `apply()`.
   Reach for it when behavior is fully describable in YAML and
   evaluated by `RuleEngine`.
2. **Policy Rule** — one named *decision*. A small immutable object
   that computes a single result via `apply()`. MUST be free of I/O:
   it reads its inputs from its fields and returns a value or a
   plan-of-record; persistence is delegated to the Document layer.
3. **Validator** — a *chain element* for the `PreToolUse` /
   `PermissionDenied` hooks. `should_run()` gate + `validate()` /
   `correct()`. Lives in a profile-filtered registry with its own
   capabilities metadata. Stays distinct because its lifecycle
   (lazy load, tier filtering, capability dispatch) is unlike a
   one-shot policy.

### `PolicyRule` Protocol

Introduce a generic, `@runtime_checkable` Protocol that the existing
`*Rule` policy classes already satisfy structurally:

```python
# src/dev10x/domain/rules/policy_rule.py
@runtime_checkable
class PolicyRule[T](Protocol):
    def apply(self) -> T: ...
```

The four policy classes are annotated as `PolicyRule[...]`
implementations. No behavior changes — the Protocol formalises the
contract that was previously implicit.

### I/O-free invariant (D3)

A Policy Rule MUST NOT perform file I/O. `MigratePluginPermissionsRule`
keeps the *decision* (which paths to migrate, building the
replacement list, whether the rule is applicable) and delegates the
read-mutate-write to a new `SettingsDocument` in the Document layer.

### New Components

| Component | Location | Responsibility |
|-----------|----------|----------------|
| `PolicyRule[T]` | `src/dev10x/domain/rules/policy_rule.py` | `@runtime_checkable` Protocol declaring `apply(self) -> T` |
| `SettingsDocument` | `src/dev10x/domain/documents/settings_document.py` | Owns `settings.json` `apply_replacements()` — one locked read-modify-write under `file_lock` + `atomic_write_text` |

### Code Examples

```python
# D3: before — Rule does its own I/O
class MigratePluginPermissionsRule:
    def apply(self) -> tuple[int, list[str]]:
        ...
        with file_lock(settings_file):
            settings = json.loads(settings_file.read_text())
            ...
            atomic_write_text(settings_file, json.dumps(settings, ...))

# after — Rule decides, Document persists
class MigratePluginPermissionsRule:
    def apply(self) -> tuple[int, list[str]]:
        replacements = _build_migration_replacements(...)
        total = 0
        changed: list[str] = []
        for settings_file in self._settings_files():
            count = SettingsDocument(path=settings_file).apply_replacements(
                replacements=replacements
            )
            if count:
                total += count
                changed.append(settings_file.name)
        return total, changed
```

## Alternatives Considered

### Alternative 1: Collapse all three into one mechanism

One base class / Protocol that Matching Rules, Policy Rules, and
Validators all implement.

**Pros:**
- A single "rule" word with one meaning.

**Cons:**
- Forces unlike lifecycles together: Matching Rules are inert data
  loaded from YAML; Validators carry registry/tier/capability
  machinery; Policy Rules are one-shot decisions. A union type would
  be a lowest-common-denominator `apply()` that fits none of them and
  would require rewriting `RuleEngine` and `ValidatorChain`.

**Verdict:** Rejected — conflates three deliberately different shapes;
maximal churn for a cosmetic win.

### Alternative 2: Leave the contract implicit (status quo)

Document nothing; rely on the shared `apply()` convention.

**Pros:**
- Zero code change.

**Cons:**
- The finding itself: no named hierarchy, untyped contract, and
  policy objects doing I/O. The next policy author has no guidance.

**Verdict:** Rejected — this is the problem being solved.

### Alternative 3 (Selected): Document three archetypes; formalise the Policy tier only

**Pros:**
- Names the hierarchy so contributors know which to use.
- `PolicyRule(Protocol)` makes the policy contract type-checkable with
  zero behavior change (the classes already satisfy it).
- The I/O-free invariant + `SettingsDocument` extraction makes
  `MigratePluginPermissionsRule` unit-testable and restores the
  policy/persistence boundary.
- Matching Rule and Validator keep their fit-for-purpose shapes.

**Cons:**
- Three archetypes still exist — but now intentionally and documented,
  rather than accidentally.

**Verdict:** Selected — formalises what works, fixes what is broken
(D3), and avoids a churny false unification.

## Consequences

### What Becomes Easier

1. A contributor picks an archetype from a documented table instead of
   copying the nearest "Rule".
2. `PolicyRule[T]` lets the type checker confirm a new policy exposes
   `apply()`; a forgotten/renamed method is caught statically.
3. `MigratePluginPermissionsRule` is testable with an in-memory
   `SettingsDocument`; the policy/persistence split mirrors the rest
   of `domain/documents/`.

### What Becomes More Difficult

1. New policies must keep `apply()` pure and route persistence through
   a Document. This is the intended constraint, not an accident.

### Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| `SettingsDocument` extraction changes migration behavior | Low | Medium | Preserve `file_lock` + `atomic_write_text` semantics exactly; existing migration tests must pass unchanged |
| `@runtime_checkable` checks method presence, not signature | Low | Low | Documented limitation; `apply()` shape is covered by per-rule unit tests |
| "Three archetypes" still confuses readers | Low | Low | The documented table in this ADR and in `domain/rules/` docstrings is the single reference |

## Implementation Plan

Shipped together under GH-244 (one PR, atomic commits per finding):

### Phase 1: Policy contract (this ADR)

1. `src/dev10x/domain/rules/policy_rule.py` — add
   `@runtime_checkable PolicyRule[T]` Protocol (A9).
2. Annotate the four `*Rule` policy classes as `PolicyRule[...]`
   implementations; document the three-archetype table in the
   `domain/rules/` package docstring.

### Phase 2: Policy/persistence split

3. `src/dev10x/domain/documents/settings_document.py` — add
   `SettingsDocument` with `apply_replacements()` (one locked
   read-modify-write); relocate the `_migrate_rules` /
   `_deduplicate_rules` transforms here (D3).
4. `hooks/session_policy.py::MigratePluginPermissionsRule.apply()` —
   delegate I/O to `SettingsDocument`; keep decision logic only.

## References

### Internal References

- [GH-244](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/244) —
  Audit-2026-05-18 M5: Context Boundary Sealing
- Audit memo: `docs/memos/005-2026-05-18-architecture-audit.md` § 7
- [ADR-0008](0008-context-boundary-protocol.md) — Context boundary
  protocol (sibling M5 ADR; relocates the policy rules to `domain/`)
- [ADR-0009](0009-result-contract-at-mcp-boundary.md) — the
  `ResultProtocol` precedent for a `@runtime_checkable` domain
  contract

### External References

- [PEP 544](https://peps.python.org/pep-0544/) — Protocols (structural
  subtyping)
- [PEP 695](https://peps.python.org/pep-0695/) — Type parameter syntax
  (`PolicyRule[T]`)
