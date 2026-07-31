# DDD Exploration Methodology

## Event Storming

Event storming is the primary technique for domain discovery. Work
through these layers in order, each building on the previous.

### Layer 1: Domain Events (orange sticky notes)

**Ask:** "What happens in the system?" — past tense verb phrases.

- `SessionCreated`, `NodeAdded`, `EstimateUpdated`
- Focus on BUSINESS events, not technical ones
- Chronological timeline: left to right
- Duplicates are fine — they reveal patterns

**Tip:** Start with the "happy path" then explore failures and
edge cases.

### Layer 2: Commands (blue sticky notes)

**Ask:** "What triggers each event?" — imperative verb phrases.

- `CreateSession`, `AddNode`, `UpdateEstimate`
- Each command produces one or more events
- Some events are produced by policies (automated), not commands

### Layer 3: Actors (yellow sticky notes)

**Ask:** "Who issues each command?"

- Named roles, not specific people: "Estimator", "Reviewer", "System"
- "System" is a valid actor for automated policies
- Multiple actors can issue the same command

### Layer 4: Policies (lilac sticky notes)

**Ask:** "What rules fire after an event?"

- `RecalculateAncestors`, `ValidateDAG`, `AskAboutDependents`
- Policies listen to events and issue new commands
- They encode business rules: "When X happens, always do Y"

### Layer 5: Aggregates

**Ask:** "What data must be consistent together?"

- Group commands and events that operate on the same data cluster
- The aggregate root is the entry point for all modifications
- Within an aggregate: strong consistency (invariants enforced)
- Between aggregates: eventual consistency (events + policies)

### Layer 6: Bounded Contexts

**Ask:** "Where are the natural seams in the system?"

- Different teams, different vocabularies, different models
- A "Product" in Pricing Context ≠ "Product" in Inventory Context
- Context map: which contexts communicate and how?

### Layer 7: Value Objects

**Ask:** "What typed quantities appear repeatedly?"

- Money (amount + currency), Effort (amount + unit), Ratio (0..1)
- Immutable, compared by value, no identity
- If two things with the same fields are interchangeable → value object

## Aggregate Design Heuristics

1. **Protect invariants** — what rules must NEVER be violated?
2. **Minimize aggregate size** — only include what's needed for consistency
3. **Reference by ID** — aggregates reference other aggregates by ID, not containment
4. **Design for eventual consistency** between aggregates
5. **One transaction per aggregate** — don't update two aggregates in one operation

## Bounded Context Integration Patterns

| Pattern | When to use |
|---|---|
| **Shared Kernel** | Two contexts share types (e.g., Money) |
| **Customer-Supplier** | One context depends on another's output |
| **Published Language** | Contexts communicate via well-defined messages |
| **Anti-Corruption Layer** | Protect your model from external system's model |
| **Separate Ways** | No integration needed — contexts are independent |

## Identifying Hidden Domains

Watch for these signals during exploration:

- **Vocabulary clash** — same word means different things → separate contexts
- **Rule explosion** — one entity with dozens of conditional rules → decompose
- **God object** — one type with 10+ fields of mixed semantics → apply archetype
- **Copy-paste logic** — same calculation in multiple places → extract to shared kernel
- **"It depends"** — when the answer to "how does X work?" is always "it depends on Y" → Y is a configurable rule, not a hardcoded property

## Design Philosophy

These principles govern all proposals made during exploration:

**"Don't make me think" (Krug)** — Prefer implicit automatic
behavior (auto-grouping on child add) over manual workflows. But
never auto-delete or auto-restructure — creation can be magic,
destruction requires intent.

**Configuration vs. Estimation** — Keep pricing configuration
cleanly separated from the estimation workspace. Users change
rules without touching estimates, and vice versa.

**Foundation-ready, not prematurely built** — Bake hooks into the
foundation (like i18n) so future capabilities are data extensions,
not refactors. **Rule of thumb:** nullable field or open union now
at zero runtime cost vs. data migration later → do it now.
Actual code/abstractions not yet used → defer.

**Plan but defer server dependencies** — Features requiring servers
(short URLs, cloud accounts) are scoped and designed but not built
until the client-side foundation is solid.
