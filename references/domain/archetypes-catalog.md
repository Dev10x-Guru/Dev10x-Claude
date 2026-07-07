# Software Archetypes Catalog

> Archetypes are NOT frameworks. They are recurring structural
> patterns that appear across domains. Recognizing them prevents
> reinventing solved problems. Sources and cross-source naming
> notes at the bottom; full citations in `bibliography.md`.

## Pattern Recognition Table

| Signal in the domain | Archetype | Core idea |
|---|---|---|
| A time-bound happening with business/legal weight (order, rental, payment, hire) | **Moment-Interval** | Model the event/interval itself as a first-class object — it owns the data both sides need |
| Entity that is sometimes a person, sometimes a company or department | **Party** | Universal Party with assigned Roles — one model for all organizational entities |
| Same party behaves differently per context (buyer here, approver there) | **Role** | Way of participating in an activity; parties collect roles, roles carry the behavior |
| "Who reports to whom" / authority and responsibility chains | **Accountability** | Typed party-to-party relationships forming validated hierarchies |
| Catalog "type" data duplicated on every instance | **Description** | Type-instance split: a Description classifies many things (make/model vs the car) |
| Raw `number` used for money, duration, weight, or ratios | **Quantity** | Typed value objects with units; **Money** is its most-used specialization |
| Metrics, readings, diagnoses attached to entities over time | **Observation & Measurement** | Observations as objects with protocol, time, and rejection/correction |
| Flat config struct with N fields of mixed semantics (rates + fractions + percentages) | **Pricing** | Price is the result of a pipeline of composable rules, not a property of a thing |
| Items arranged in a hierarchy with composition and pricing | **Product** | Composite tree of configurable items priced through a pipeline |
| Stock levels, holdings, "how many do we have where" | **Inventory** | Inventory entries per item/location, movements as Moment-Intervals |
| Request for goods/services with fulfillment tracking | **Order** | Composition: Party + Product + Moment-Interval + Quantity |
| Complex conditional business rules that vary by context | **Rule** | Condition trees evaluated against a context, returning actions — rules as data |
| "Choose valid combinations" / "this option requires that one" | **Configurator** | Constraint satisfaction — SAT-like validation of option combinations |
| "What resources are available when?" | **Availability** | Time-slotted resource management with capacity, blocking, overlaps |
| "Queue this work" / "first come, first served" | **Waitlist** | Priority queue with fairness rules and capacity constraints |
| "Assign N tasks to M workers optimally" | **GAP** | Generalized Assignment Problem — optimization under constraints |
| "Plan says X, reality says Y" | **Plan** | Parallel structures for intended vs actual, with variance tracking |
| "Who/what is assigned to this activity or period" | **Resource Allocation** | Capacity claims against availability, budget, or schedule |
| Tracking debits/credits, balances, financial flows | **Accounting** | Double-entry ledger, immutable transactions, **Posting Rules** automate entries |
| Bounded intervals or sets of valid values | **Range** | Explicit range objects instead of min/max field pairs |
| Bloated entity with mixed semantics | (step back) | Which archetype decomposition applies? Usually Party+Role+Description |

**Composition:** archetypes compose into archetype *patterns* —
an Order is Party + Product + Moment-Interval + Quantity; a
pricing engine is Configurator + Quantity + Party + Moment-
Interval. Recognize the atoms first, then the molecule.

**Exploration order (solo/workshop):** Moment-Interval (concrete
events) → Party → Role → Description → Quantity/Money → Rule →
Accountability → Plan → Resource Allocation → then DDD aggregate
and context boundaries.

## How to Apply an Archetype

### Step 1: Recognize the pattern

Don't look for the archetype name in the domain language. Look for
the **structural shape**. The domain expert says "rate card"; you
recognize "composable pricing pipeline."

### Step 2: Map domain concepts to archetype concepts

| Archetype concept | Domain concept |
|---|---|
| PricingRule | EffortAllocationRule, DayRate, PriceModifier |
| Product | EstimateNode |
| Money | Money { amount, currency } |
| Pipeline Stage | PERT → Effort → Rates → Modifiers |

### Step 3: Validate the mapping preserves semantics

- Does every domain behavior map to an archetype operation?
- Does the archetype introduce unnecessary concepts?
- Is the pipeline/composition order explicit and correct?

### Step 4: Identify the seam

Every archetype has a natural **seam** — the point where the
archetype's generic structure meets domain-specific logic.

For Pricing: the seam is at `basePrice`. Everything above is
strategy-specific. Everything below (modifiers, tax, aggregation)
is universal. See `pricing-pipeline.md` for the full worked
example — use it as the depth template for any archetype.

### Step 5: Stress-test the seam

Ask: "If I add a new product type / rule type / calculation stage,
does the seam hold?" If yes, the archetype is correctly applied.
If not, the seam is in the wrong place.

## Quantity — the cheapest win

**Never use raw `number` where a unit is implied.**

```typescript
// BAD: what unit is amount? dollars? days? percent?
function calculate(amount: number): number

// GOOD: types enforce semantics
function calculate(effort: Effort): Money
```

Domain model uses `Ratio` (0..1) internally; UI converts to percent
at the boundary. Prevents "is 5 five percent or five dollars?",
currency mix-ups, and days-vs-hours bugs. Apply this archetype
by default — it costs one type definition.

## When NOT to Apply an Archetype

- When the problem is genuinely unique to the domain (rare)
- When the archetype adds more complexity than it solves
- When the team doesn't understand the archetype (training first)
- When applying it would require rewriting stable, working code
  that isn't blocking any extension (if it ain't broke...)

The test: **"Does recognizing this archetype simplify the model,
or complicate it?"** If it simplifies — apply. If it complicates —
the match is wrong; look for a different archetype or accept that
this is domain-specific. See also `anti-patterns.md` § Golden
Hammer and § Speculative Generality.

## Source Landscape & Naming Notes

| Source | Contributes | Character |
|---|---|---|
| Fowler, *Analysis Patterns* (1997) | Party, Accountability, Observation & Measurement, Quantity, Money, Posting Rules, Range, Plan, Resource Allocation | Deepest catalog (70+ patterns); pre-DDD vocabulary |
| Coad/Lefebvre/De Luca, *Modeling in Color* (1999) | Moment-Interval, Role, Description, Party/Place/Thing; Domain-Neutral Component | Visual, memorable four-archetype system |
| Arlow & Neustadt, *Enterprise Patterns and MDA* (2003) | Party, PartyRelationship, CRM, Product, Inventory, Order | Full UML archetype patterns; MDA-era |
| Software-Archetypes repo (Pilimon/Słota/Sobótka, active) | Party, Availability, Waitlist, GAP, Configurator, Product, Pricing | Modern, code-forward, runnable examples |

Naming reconciliation used here: "Party" unified across all
sources; Coad's Moment-Interval is the umbrella for transaction-
like things (Order, Posting, Waitlist are specializations);
"Description" covers type-instance catalogs; Quantity is the
supertype of Money; Plan (intent vs actual) is orthogonal to
Availability (supply). Known gaps in all sources: no event-stream
archetype, no archetype↔aggregate mapping, no saga/FSM
formalization — treat those as DDD-pattern territory
(`design-patterns.md`).
