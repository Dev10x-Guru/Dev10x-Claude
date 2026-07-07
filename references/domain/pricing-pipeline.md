# Pricing Pipeline Pattern (Worked Example)

> The Pricing Archetype applied to estimation and costing domains —
> a complete worked example of taking one archetype from recognition
> through seam identification to stress-testable structure. Use it
> as the template for depth when applying ANY archetype from
> `archetypes-catalog.md`; the TypeScript shapes are illustrative,
> not prescriptive.

## The Core Principle

**A price is not a property of a thing. It's the result of running
a pipeline of composable policies over that thing.**

Instead of one struct with N named fields:
```typescript
// ❌ Bloated, rigid, closed for extension
interface RateCard {
  devDayRate: number;         // a rate
  testingFraction: number;    // a ratio
  riskBuffer: number;         // a percentage
  // ... 8 more fields of mixed semantics
}
```

You have an ordered collection of small, typed, independently
testable rules:
```typescript
// ✅ Composable, extensible, each rule independently typed
interface PricingPolicy {
  effortAllocations: EffortAllocationRule[];   // stage ②
  dayRates: DayRate[];                         // stage ③
  priceModifiers: PriceModifier[];             // stage ④
}
```

Adding a new pricing factor (rush fee, volume discount) = add a
rule instance. Zero code changes, zero type changes.

## The Pipeline

```
┌────────────────────────────────────────────────────┐
│  PRICING STRATEGY (varies by product type)         │
│                                                    │
│  Labor:    ① PERT → ② Allocate → ③ Rate  ──┐      │
│  Goods:    ① Cost → ② Qty → ③ Markup    ──┤      │
│  Fixed:    ① → amount                    ──┤      │
│  External: ① → vendor API                ──┤      │
│                                            │      │
│                              basePrice ◄───┘      │
└────────────────────┬───────────────────────────────┘
                     │
┌────────────────────▼───────────────────────────────┐
│  ④ MODIFIER CHAIN (universal, shared)               │
│  PriceModifier[] → preTaxPrice                      │
│  (discounts, surcharges, risk buffers, IP markup)   │
└────────────────────┬───────────────────────────────┘
                     │
┌────────────────────▼───────────────────────────────┐
│  ⑤ TAX CHAIN (conditional, future)                  │
│  TaxRule[] → finalPrice + taxBreakdown              │
└────────────────────┬───────────────────────────────┘
                     │
┌────────────────────▼───────────────────────────────┐
│  AGGREGATION (tree-walk, universal)                 │
│  leaf finalPrices → group sums                      │
│  leaf sigmas → group √(Σσ²)                        │
└─────────────────────────────────────────────────────┘
```

## The Sacred Seam: `basePrice`

Everything above `basePrice` varies by product type. Everything
below is universal and shared. `applyModifiers()` (Stage ④) must
remain a standalone pure function that never knows or cares how
the base price was produced.

**This is the invariant that makes the architecture extensible.**

When stress-testing any extension, check: "Does `applyModifiers()`
need to change?" If yes, the seam is violated — redesign the
extension. If no, the architecture holds.

## Rule Type Hierarchy

```typescript
// Base — all rules share these fields
interface PricingRule {
  id: string;
  name: string;
  enabled: boolean;
  order: number;       // position in pipeline stage
}

// Stage ② — effort allocation (labor-specific)
interface EffortAllocationRule extends PricingRule {
  kind: 'effortAllocation';
  role: string;        // open set (WorkRole)
  fraction: Ratio;     // 0..1
}

// Stage ③ — day rates (labor-specific)
interface DayRate extends PricingRule {
  kind: 'dayRate';
  role: string;
  rate: Money;
}

// Stage ④ — price modifiers (universal)
interface PriceModifier extends PricingRule {
  kind: 'priceModifier';
  operation: 'addPercent' | 'subtractPercent' | 'addFixed' | 'subtractFixed';
  value: Ratio;
  appliesTo: 'basePrice' | 'runningTotal';
}
```

## Modifier Chain Semantics

```
running = basePrice.amount
for each enabled modifier (sorted by order):
  reference = (appliesTo == 'basePrice') ? base : running
  delta = operation(reference, value)
  running += delta
  trace.push({ rule, input, delta, output })
```

**`appliesTo: 'basePrice'`** — the modifier always references the
original base price, regardless of what previous modifiers did.
Use for: risk buffer, hidden costs (independent surcharges).

**`appliesTo: 'runningTotal'`** — the modifier references the
current running total after all prior modifiers. Use for: IP
markup (stacks on buffered price), discount (reduces everything).

**Order matters.** Reordering modifiers changes the result. This
is correct — business rules about which surcharges and discounts
apply in what order are intentional, not accidental.

## PolicyOverlay — Rule-Level Overrides

Instead of `Partial<RateCard>` with N optional fields, overrides
operate at rule granularity:

```typescript
interface PolicyOverlay {
  addedRules: AnyPricingRule[];      // session-specific rules
  removedRuleIds: string[];          // suppress global rules
  ruleOverrides: RuleOverride[];     // tweak specific rule fields
}
```

- **Toggle a surcharge off:** `removedRuleIds: ['pm-1']`
- **Change dev rate:** `ruleOverrides: [{ ruleId: 'dr-1', changes: { rate: 1500 } }]`
- **Add rush fee:** `addedRules: [{ kind: 'priceModifier', name: 'Rush', ... }]`
- **Reorder discount before IP:** override `order` fields

## The Modifier Trace

Every calculation produces a `ModifierTrace[]` showing each rule's
contribution. This is essential for:
- UI transparency (user sees how price was composed)
- Debugging (which rule caused the unexpected result?)
- Client communication (line-item breakdown in offers)

```typescript
interface ModifierTrace {
  rule: PriceModifier;
  inputAmount: Money;      // running total before this rule
  delta: Money;            // how much was added/subtracted
  outputAmount: Money;     // running total after this rule
}
```

## Confidence Bands

Uncertainty propagates through the pipeline:

- Per-item: σ = (P - O) / 6 (in days), converted to money via effective rate
- Per-group: σ_group = √(Σ σᵢ²) — root-sum-of-squares for independent items
- Bands: ±1σ (68% confidence), ±2σ (95% confidence)

This works for any product type that has uncertain input costs
(three-point estimates for labor, min/max/likely for goods).
Fixed-price items contribute σ = 0.
