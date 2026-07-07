# Stress Test Protocol

## When to Run a Stress Test

- Before committing to a structural model change
- When a new feature area is proposed ("add tax support")
- When evaluating trade-offs between design options
- When someone says "what if we need to support X in the future?"

## The Protocol

### Step 1: Define the Extension

State clearly:
- What capability is being added?
- What product types, rule types, or calculation stages are involved?
- What external context is needed (location, date, user role)?

### Step 2: Trace Through the Pipeline

For each stage in the calculation pipeline, state one of:

| Verdict | Meaning |
|---|---|
| **ZERO changes** | Existing code is completely untouched |
| **Additive** | New code alongside existing; existing untouched |
| **Breaking** | Existing code must be modified |

Breaking changes are the red flag. They indicate the architecture
seam is in the wrong place or needs to be widened.

### Step 3: Check the Stable Core

Every project maintains its own **Stable Core** list — the
components that should NEVER change — in the "Stable Core" section
of `docs/domain/stress-tests.md`. It is established after the first
archetype application and grows as seams are validated.

A stable core typically names:
- Core data structures (tree/graph shapes, aggregate roots)
- The universal pipeline stages below each archetype seam
- Value object types (Money, Quantity, Ratio)
- Aggregation and derived-value math
- Persistence and serialization contracts

Example (an estimation tool's stable core):

```
STABLE CORE (check each one):
□ Tree structure (EstimateNode parentId/childIds)
□ applyModifiers() — universal modifier stage
□ Money / Effort value objects
□ Group aggregation (Σ prices, √Σσ² confidence bands)
□ Persistence (localStorage / shareable links)
```

Verify each listed component against the proposed extension. If ANY
of these would need modification, the extension is signaling a
deeper architectural problem. Investigate before proceeding.

### Step 4: Identify Seams

If the extension needs a hook that doesn't exist, document:

| Question | Answer |
|---|---|
| What field/type/function is needed? | (describe) |
| What does it cost to add NOW? | (should be zero or near-zero) |
| What does it cost to add LATER? | (data migration? refactor?) |
| Recommendation? | Add now / defer |

### Step 5: Check Against Prior Decisions

Review `decisions.md` for conflicts:
- Does this extension contradict any active decision?
- Does it render any decision obsolete (should be superseded)?
- Does it validate a decision's foresight (the seam was correctly placed)?

### Step 6: Produce the Scorecard

```markdown
## Scenario N: [Title] (date, workshop NNN)

**Extensions tested:** [list]

**Pipeline trace:**
| Stage | Verdict | Detail |
|---|---|---|
| ① Strategy | Additive | New `GoodsStrategy` function |
| ② Allocation | ZERO | Not applicable to goods |
| ③ Pricing | ZERO | `priceEffort` unchanged |
| ④ Modifiers | ZERO | `applyModifiers` unchanged |
| Aggregation | ZERO | `calculateGroup` unchanged |

**Stable core check:** All components stable / [list exceptions]

**Seams required:** [list with cost analysis]

**Decision conflicts:** None / [list with proposed resolutions]
```

### Step 7: Append to stress-tests.md

Add the scorecard as a new scenario section. Never modify or
remove existing scenarios — they document validated seams.

## The Endgame Scale Test

The architecture's ultimate target is NOT the current use case.
It's the most demanding scenario the product could eventually serve.

**Define the endgame per project** during the first workshop and
record it in `stress-tests.md`. Scale every dimension of the current
use case by 2-3 orders of magnitude and add the structural stressors
the domain implies: multi-tenancy, hierarchy depth, mixed entity
types, multi-currency/locale, versioning and branching, concurrent
collaboration, access control.

Example (an estimation tool's endgame):
- **10-year infrastructure project** (not a 3-month software sprint)
- **Thousands of work packages** (not 20 line items)
- **Dozens of contributing departments/vendors** (not a single team)
- **Mixed product types** (labor + goods + services + equipment)
- **Hierarchical policy inheritance** (per-department pricing)
- **Multi-currency aggregation** at boundaries
- **Versioning and branching** for what-if scenarios

Any proposal that works at today's scale but structurally cannot
reach the endgame must be flagged and either redesigned or
explicitly documented as a known future migration.

## When to Stop

A stress test passes when:
1. The stable core has ZERO changes
2. All new functionality is additive (no breaking changes)
3. Seams are identified and cost-assessed
4. No active decisions are violated
5. The endgame scale test doesn't reveal structural blockers
