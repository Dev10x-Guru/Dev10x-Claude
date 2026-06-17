# 8. Context boundary protocol (domain ⟂ hooks ⟂ audit ⟂ skills)

Date: 2026-05-31

## Status

Accepted

## Context

The architecture audit (`docs/memos/005-2026-05-18-architecture-audit.md`
§ 3, cross-phase convergence #3) found that the same root cause —
**no stable protocol demarcating context boundaries** — surfaced in
five findings spanning four packages. Outer layers reach sideways into
each other's internals, and one cycle is papered over with deferred
imports.

### Current State

`src/dev10x/` is organised in concentric layers, but the dependency
direction is only enforced by convention:

| Layer | Packages | Role |
|-------|----------|------|
| Core | `domain/` | Pure data, value objects, policies, Protocols |
| Adapters | `hooks/`, `audit/`, `session/`, `skills/` | I/O, Claude Code event handlers, CLI shims |

The boundary inversions found:

| Finding | Coupling | Direction |
|---------|----------|-----------|
| **D1** | `domain/session_document` → `hooks.task_plan_sync` | core → adapter (inverted) |
| **I1** | `audit/analyze.py` → `skills.audit.analyze_permissions` internals | adapter → adapter |
| **I6** | `hooks/audit_emit.py` → `audit.log_reader` internals | adapter → adapter |
| **I2 + I10** | `session/queries.py` defers `hooks.session_policy` imports | adapter ⇄ adapter cycle |

Cumulative chain: `hooks → audit → skills`. The `session.queries`
case is the most telling — it imports `ReadFrictionLevelRule` and
`DecisionGuidanceRule` *inside function bodies* (four deferred
imports) purely to break the import cycle
`hooks.session_dispatch → session.queries → hooks.session_policy`.
A deferred import is a cycle made invisible, not a cycle removed.

### Problems

1. **No declared direction (I1, I6).** Nothing states that an adapter
   may depend on `domain/` but never on another adapter's internals.
   `audit/analyze.py` and `hooks/audit_emit.py` each reach directly
   into a sibling package's implementation, so refactoring either
   side silently breaks the other.
2. **Cycles hidden behind lazy imports (I2 + I10).** Module-scope
   imports would raise `ImportError`; moving them into function
   bodies suppresses the symptom while the architectural cycle
   remains. The coupling is invisible to static tooling and to
   readers scanning the import block.
3. **Policy logic stranded in the adapter layer (I2 + I10).**
   `ReadFrictionLevelRule` and `DecisionGuidanceRule` are pure
   policies (they already depend only on `domain/`), yet they live in
   `hooks/session_policy.py`, forcing every non-hook consumer to
   reach *up* into `hooks/`.

### Prerequisites

This ADR must be accepted **before** the I2/I10 and I6 implementations
land — both relocate symbols across package boundaries, which is
import-path-breaking for any external caller. Tracked by GH-244
(Audit-2026-05-18 Milestone 5). Source:
`docs/memos/005-2026-05-18-architecture-audit.md` § 3 and §
"Proposed Milestones" → M5.

## Decision

We adopt an explicit **dependency-direction rule** and a single
mechanism for crossing it.

### The Rule

1. `domain/` is the stable core. It depends on nothing outside
   `domain/` and the standard library.
2. Adapter packages (`hooks/`, `audit/`, `session/`, `skills/`) may
   depend **inward** on `domain/`. They MUST NOT import another
   adapter package's internals.
3. When one adapter needs a capability another adapter provides,
   the contract is declared as a **`Protocol` in `domain/`** and the
   concrete implementation is **injected** (Dependency Inversion).
   The depending adapter imports the Protocol from `domain/`, never
   the providing adapter's module.
4. Pure policies — classes whose only dependency is `domain/` —
   belong in `domain/`, not in an adapter package.

### Per-Finding Application

| Finding | Resolution |
|---------|------------|
| **D1** | Already resolved. `read_plan_summary` now imports `domain.documents.plan` directly (core → core). No further work. |
| **I2 + I10** | Move `ReadFrictionLevelRule` and `DecisionGuidanceRule` into `domain/session_rules.py`. `session/queries.py` and `hooks/session_policy.py` both import inward from `domain/`; the deferred imports become module-scope. Cycle removed (rule #4). |
| **I6** | Define `AuditWriter(Protocol)` in `domain/audit_writer.py`. `audit/log_reader` provides the concrete writer; `hooks/audit_emit` depends on the domain Protocol and resolves the concrete impl through a single injection seam (rule #3). |
| **I1** | **Deferred to M7.** Sealing `audit → skills` cleanly requires moving the analysis logic out of `skills/audit/analyze_permissions.py`, but that file is a standalone `uv run --script` with `dependencies = []` and cannot import `dev10x`. Choosing between duplication and a `dev10x` dependency is the **ADR-0010** decision (uv-script vs importable module), scoped to M7. See "Known Exceptions". |

### New Components

| Component | Location | Responsibility |
|-----------|----------|----------------|
| `AuditWriter` | `src/dev10x/domain/audit_writer.py` | `@runtime_checkable` Protocol declaring the audit write surface (`append_record`, `audit_enabled`) the hooks layer consumes |
| `ReadFrictionLevelRule`, `DecisionGuidanceRule` | `src/dev10x/domain/session_rules.py` | Pure session policies relocated from `hooks/session_policy.py` |

`hooks/session_policy.py` keeps `MigratePluginPermissionsRule` and
`BuildAutonomyReassuranceRule` (genuine hook-layer policies) and
re-exports the two moved rules so existing callers keep working
during transition.

> **Follow-up (GH-515 / GH-513 / GH-524):** `ReadFrictionLevelRule` was
> later removed entirely — its read moved to `SessionYamlDocument`
> (`domain/documents/session_yaml.py`) and callers invoke
> `read_friction_level()` directly. `BuildAutonomyReassuranceRule`, once
> made I/O-free (GH-513), was relocated from `hooks/` to
> `domain/session_rules.py` and is re-exported from
> `hooks/session_policy.py` during transition (GH-524).

### Code Examples

```python
# src/dev10x/domain/audit_writer.py
@runtime_checkable
class AuditWriter(Protocol):
    def audit_enabled(self) -> bool: ...
    def append_record(self, *, record: dict[str, Any]) -> None: ...
```

```python
# src/dev10x/session/queries.py — before
def gather_reload(cls, *, toplevel: str):
    from dev10x.hooks.session_policy import ReadFrictionLevelRule  # cycle break
    ...

# after
from dev10x.domain.session_rules import ReadFrictionLevelRule  # module scope
```

## Alternatives Considered

### Alternative 1: Keep deferred imports (status quo for I2/I10)

Leave the function-body imports in place.

**Pros:**
- Zero migration.

**Cons:**
- The finding itself: the cycle is hidden, not removed. Static
  import-graph tooling cannot see it; a reader scanning the import
  block is misled. Policy logic stays stranded in `hooks/`.

**Verdict:** Rejected — this is the problem being solved.

### Alternative 2: Merge the coupled adapters

Fold `audit_emit`'s write side into `audit/`, and the session rules
into `session/`.

**Pros:**
- Removes the cross-package import directly.

**Cons:**
- `audit_emit` provides the `@audit_hook` decorator the *hooks* layer
  applies to hook bodies — it cannot live in `audit/`. Merging
  adapters trades a direction problem for a cohesion problem and does
  not generalise to the next boundary.

**Verdict:** Rejected — addresses the symptom, not the direction.

### Alternative 3 (Selected): Domain-owned Protocols + relocate pure policies

**Pros:**
- One rule covers every current and future boundary: depend inward on
  `domain/`, cross via a `domain/` Protocol.
- Removes the cycle outright (module-scope imports), so static tooling
  can enforce it.
- Pure policies land where they belong; consumers stop reaching up
  into `hooks/`.

**Cons:**
- Relocating symbols is import-path-breaking — mitigated by
  re-export shims and a one-PR atomic migration.

**Verdict:** Selected — generalises, removes (not hides) the cycle,
and aligns layer membership with dependency direction.

## Consequences

### What Becomes Easier

1. New cross-adapter needs have one obvious answer: declare a
   `Protocol` in `domain/` and inject. No new sideways imports.
2. The import graph becomes acyclic and statically checkable; a
   future lint rule can forbid `hooks → audit`, `audit → skills`,
   etc.
3. Session policies are reusable from any layer without importing
   `hooks/`.

### What Becomes More Difficult

1. Adding a capability that one adapter needs from another now costs
   a Protocol declaration plus an injection seam, rather than a bare
   import. This is the deliberate cost of an enforced boundary.

### Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| A moved-symbol import site is missed and breaks at runtime | Medium | Medium | Re-export shims in `hooks/session_policy.py`; grep every import site before merge; full test suite must pass |
| `@runtime_checkable` Protocol checks method presence, not signature | Low | Low | Documented limitation; the injection seam is internal, exercised by unit tests |
| I1 deferral leaves one inversion live | Certain | Low | Explicitly recorded below and in the PR; `audit → skills` is read-only and stable until ADR-0010 |

### Known Exceptions

`audit/analyze.py → skills.audit.analyze_permissions` (I1) remains
until **ADR-0010** decides the uv-script question. This is a recorded,
bounded exception — not an oversight.

## Implementation Plan

Shipped together under GH-244 (one PR, atomic commits per finding):

### Phase 1: Boundary Protocols (this ADR)

1. `src/dev10x/domain/audit_writer.py` — add `@runtime_checkable
   AuditWriter` Protocol (I6 contract).
2. `src/dev10x/domain/session_rules.py` — relocate
   `ReadFrictionLevelRule` + `DecisionGuidanceRule` (I2 + I10).

### Phase 2: Adapter rewiring

3. `hooks/audit_emit.py` — depend on `AuditWriter`; resolve the
   concrete `log_reader` impl through one injection seam (I6).
4. `session/queries.py`, `hooks/session.py`,
   `hooks/session_dispatch.py` — switch to module-scope imports from
   `domain.session_rules`; `hooks/session_policy.py` re-exports the
   moved rules (I2 + I10).

### Deferred

5. I1 (`audit → skills`) — tracked for M7 under ADR-0010.

## References

### Internal References

- [GH-244](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/244) —
  Audit-2026-05-18 M5: Context Boundary Sealing
- Audit memo: `docs/memos/005-2026-05-18-architecture-audit.md` § 3
- [ADR-0007](0007-rule-policy-archetype-unification.md) —
  Rule/Policy archetype unification (sibling M5 ADR)
- CWD discipline: `.claude/rules/cwd-discipline.md` (the same
  "domain owns the contract, adapters inject" shape)

### External References

- [The Clean Architecture](https://8thlight.com/blog/uncle-bob/2012/08/13/the-clean-architecture.html)
  — dependency rule (dependencies point inward)
- [PEP 544](https://peps.python.org/pep-0544/) — Protocols (structural
  subtyping)
