# ADR-0030: Catalog Entry is the fourth rule archetype

- **Status:** Accepted
- **Date:** 2026-09-26
- **Supersedes:** none
- **Amends:** [ADR-0007](0007-rule-policy-archetype-unification.md)
  (adds a fourth row to its archetype table)
- **Related:** GH-1453, GH-271 / PAP-1 (GH-798), GH-1442

## Context

ADR-0007 (accepted 2026-05-31) promised that a contributor can "pick
an archetype from a documented table instead of copying the nearest
'Rule'" (ADR-0007:213-214). The table names three archetypes:

| Archetype | Canonical type | Shape |
|---|---|---|
| Matching Rule | `domain/rules/validation_rule.py::MatchingRule` (`:297`) | declarative patterns + `matches_*` predicates |
| Policy Rule | `domain/rules/policy_rule.py::PolicyRule[T]` (`:25`) | one I/O-free decision via `apply()` |
| Validator | `validators/base.py::Validator` | `should_run()` + `validate()` hook-chain element |

The same list is restated in the `policy_rule.py` module docstring
(`:9-16`).

Eight days after ADR-0007, GH-271 (`ad0f1dc0`, 2026-06-08) added
`domain/common/policy.py`. Its `Policy` (`:192-274`) fits none of the
three rows:

- It is **not a Policy Rule**. It has no `apply()` and computes no
  decision. It is a frozen record of 14 fields: `rule`, `tier`,
  `source`, `effect`, `sensitivity`, `group`, `id`, `scope`, `owner`,
  `reversible`, `rationale`, `lifecycle`, `enabled`, `assessments`.
- It is **not a Matching Rule**. It *wraps* one: `rule: AllowRule`
  (`:196`), and `Policy.matches()` delegates to it (`:236-238`). What
  it adds is metadata about the rule: provenance (`PolicySource`,
  `:65-84`), a lifecycle (`PolicyLifecycle`, `:111-130`), a data
  class (`PolicySensitivity`, `:87-108`) and recorded judgements
  (`PolicyAssessment`, `:167-189`).
- It is **not a Validator**. No hook chain holds it.

It is **queried and listed** rather than applied. `PolicyCatalog`
parses the grouped YAML into a `list[Policy]` (`:277-337`) and
partitions it by effect (`:339-354`, GH-1442). The decision that uses
these records, `resolve_effect`, is a free function in a separate
module (`policy_resolution.py:48-78`): forbid-wins, then the
highest-precedence source. Eleven modules across
`skills/permission/`, `skills/permission_investigator/` and
`domain/common/` import `Policy` or its value types.

### Problems

1. **The table is incomplete.** A contributor who follows ADR-0007's
   instruction does not find the shape of the permission domain's
   core rule-shaped type.
2. **The name points the wrong way.** `Policy` is one word from
   `PolicyRule` and structurally unrelated to it. A reader who knows
   ADR-0007 will expect `apply()`. This is the confusion ADR-0007 was
   written to remove, recurring one layer down.
3. **`AllowRule` sits unnamed too.** It is a second implementation of
   the Matching Rule archetype (`allow_rule.py:39-128`: a parsed
   `Tool(pattern)` plus `matches` / `matches_prefix`). It fits the
   existing row, but nothing says so.

## Decision

1. **Add a fourth archetype, Catalog Entry.** This is declarative
   rule *data* carrying provenance and lifecycle metadata. It is
   stored, listed, filtered and audited; it is never `apply()`'d.
   Its predicate is delegated to a Matching Rule it wraps. The
   decisions made *over* a set of entries live outside the entry, in
   a resolver function or a Policy Rule.

   | Archetype | Canonical type | Shape | Lifecycle |
   |---|---|---|---|
   | **Catalog Entry** | `domain/common/policy.py::Policy` | Frozen record: a wrapped Matching Rule + provenance (`source`, `owner`, `rationale`), classification (`tier`, `effect`, `sensitivity`, `scope`), lifecycle (`lifecycle`, `enabled`) and `assessments` | Loaded in layers by `PolicyCatalog` / `load_policy_layers`, queried by `resolve_effect` and the doctor/audit/investigator reports |

2. **Distinguishing test.** A reader should ask which question the
   type answers:
   - "Does this input match?" means a **Matching Rule**.
   - "What should happen, once?" means a **Policy Rule**.
   - "Should this hook call proceed?" means a **Validator**.
   - "What do we know about this rule: who owns it, how risky it is,
     whether it is still live?" means a **Catalog Entry**.

3. **`AllowRule` is recorded as a Matching Rule implementation.** No
   new archetype is needed for it.

4. **The name `Policy` stays.** Renaming it would touch 11 importers
   and the PAP-1 vocabulary (`statement`, `lifecycle`, Cedar-style
   `effect`) that the permission design docs use. The confusion is
   fixed by documentation at both ends instead. `policy.py` names its
   archetype and links here, and `policy_rule.py`'s list gains the
   fourth entry together with the warning that `Policy` is not a
   `PolicyRule`.

## Alternatives Considered

### Alternative 1: Classify `Policy` as a Matching Rule

**Pros:** No new archetype.

**Cons:** It stretches "patterns + predicates" to cover a 14-field
record whose predicate is a delegation, and it hides the provenance
and lifecycle that make it useful. The next metadata-bearing record
would get no guidance.

**Verdict:** Rejected.

### Alternative 2: Rename `Policy` to `CatalogEntry`

**Pros:** The name would then state the archetype, and the collision
with `PolicyRule` would disappear.

**Cons:** 11 importing modules plus tests change for a naming benefit
that docstrings deliver at a fraction of the churn. It also breaks
the PAP-1 vocabulary that `policy_resolution.py`, `policy_audit.py`
and the doctor already share.

**Verdict:** Rejected for now. The alias route stays open if the
confusion persists, but it would be a deprecation, and ADR-0028
(Proposed) frames how those should expire.

### Alternative 3 (Selected): A fourth archetype, documented at both ends

**Verdict:** Selected. It restores ADR-0007's completeness promise
with a documentation-only change.

## Consequences

### What Becomes Easier

1. The archetype table is complete again, and the distinguishing test
   classifies a new type by the question it answers.
2. A reader landing in `policy.py` learns immediately that it is not
   a `PolicyRule`.

### What Becomes More Difficult

1. There are four archetypes to know instead of three. That is the
   honest count; the fourth already existed.

### Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| A fifth shape appears undocumented, as this one did | Medium | Low | The distinguishing test gives reviewers a question to ask of any new rule-shaped type |

## Implementation Plan

Shipped with this ADR:

1. `docs/adr/0030-catalog-entry-is-the-fourth-rule-archetype.md`.
2. `docs/adr/0007-rule-policy-archetype-unification.md`: an
   amendment note pointing here.
3. `src/dev10x/domain/rules/policy_rule.py`: the docstring archetype
   list gains Catalog Entry.
4. `src/dev10x/domain/common/policy.py`: the module docstring names
   the archetype and links here.

## References

- [ADR-0007](0007-rule-policy-archetype-unification.md): the
  three-archetype table this amends
- `src/dev10x/domain/common/policy.py:192-274`, `:277-354`:
  `Policy` and `PolicyCatalog`
- `src/dev10x/domain/common/policy_resolution.py:48-78`: the decision
  over catalog entries
- `src/dev10x/domain/common/allow_rule.py:39-128`: the Matching Rule
  it wraps
- `ad0f1dc0`: GH-271, where `Policy` arrived
- [GH-1453](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1453):
  the issue this decides
