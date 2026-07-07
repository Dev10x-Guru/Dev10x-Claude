# DDD Design Patterns — Tactical & Strategic

> When-to / when-NOT-to guidance for the patterns most often
> applied (and misapplied) during workshops. Full citations in
> `bibliography.md`. Anti-pattern counterparts in
> `anti-patterns.md`.

## Tactical Patterns

| Pattern | Core rule | Use when | Do NOT use when |
|---|---|---|---|
| **Entity** | Identity + lifecycle; equality by ID | The domain tracks "the same one" over time | Two instances with equal fields are interchangeable (→ value object) |
| **Value Object** | Immutable, equality by value, self-validating | Typed quantities, ranges, descriptors (Money, Ratio, Address) | Identity or independent lifecycle matters |
| **Aggregate** | Transactional consistency boundary around invariants | A rule must hold at every commit ("order total ≤ credit limit") | Grouping for convenience/navigation only — reference by ID instead |
| **Domain Event** | Past-tense fact other parts react to | Cross-aggregate/context reactions; audit trail | Simple intra-aggregate state change nobody listens to |
| **Repository** | Collection illusion per aggregate root | Persisting/rehydrating aggregates | Per-table repositories (that's a DAO) or querying for reports (→ read models) |
| **Factory** | Encapsulate complex creation enforcing invariants | Construction rules exceed a constructor | A constructor suffices |
| **Domain Service** | Stateless domain logic spanning aggregates | Logic belongs to no single aggregate (transfer between accounts) | Logic fits inside one aggregate (keep it there) |
| **Application Service** | Orchestrates use case: load → invoke → persist | Every use-case entry point | It starts containing business rules (push them into the model) |
| **Specification** | Predicate object for rules/queries/validation | Reusable, combinable business criteria | One-off condition — plain code is clearer |
| **Policy / Process Manager (Saga)** | Long-running reaction: events in, commands out | Workflows spanning aggregates/contexts with compensation | A single transaction can do it |
| **Outbox** | Persist events atomically with state, publish async | Events must not be lost between DB commit and broker | In-process, same-DB consumers |
| **CQRS** | Separate write model from read model(s) | Read and write shapes diverge badly; hot read paths | CRUD symmetric data; adds two models to maintain |
| **Event Sourcing** | State = fold(events); events are the source of truth | Audit/replay/temporal queries are first-class domain needs | Team lacks ES operational experience; CRUD domain (see anti-patterns) |

### Aggregate design rules (Vernon)

1. Protect true invariants in one boundary — not "looks related".
2. Keep aggregates small; large aggregates fail under concurrency.
3. Reference other aggregates by ID, never by object graph.
4. Update other aggregates via eventual consistency (events),
   one transaction per aggregate.

Rule of thumb: if two pieces of data can be inconsistent for a few
seconds without a business rule breaking, they belong to different
aggregates.

## Strategic Patterns

**Bounded Context** — the boundary within which a model and its
ubiquitous language are consistent. Contexts are drawn around
language and team ownership, not around entities. The same noun
("Product", "Customer") deliberately has different models in
different contexts.

**Core / Supporting / Generic subdomains** — invest modeling depth
where the business differentiates (core); buy or copy commodity
capability (generic); keep supporting subdomains simple. Workshop
question: "would a competitor pay for this logic?" If no, don't
gold-plate it.

### Context mapping (integration patterns)

| Pattern | Relationship | Use when |
|---|---|---|
| **Partnership** | Two teams succeed/fail together | Mutually dependent deliveries, aligned cadence |
| **Shared Kernel** | Shared subset of the model | Small, stable shared types (Money); high trust; shared CI |
| **Customer–Supplier** | Downstream can negotiate | Upstream prioritizes downstream needs in planning |
| **Conformist** | Downstream adopts upstream model as-is | No leverage over upstream; translation cost exceeds benefit |
| **Anti-Corruption Layer** | Translate at the boundary | Protecting your model from a legacy/external model |
| **Open Host Service** | Upstream publishes a stable protocol | Many downstreams; one-off integrations don't scale |
| **Published Language** | Shared, documented interchange model | Industry standard exists (see `standards-and-references.md`) |
| **Separate Ways** | No integration | Integration cost exceeds the value of sharing |

Direction heuristics: upstream changes propagate downstream; the
ACL is the default defensive stance when integrating anything you
do not control; prefer OHS + Published Language when you are the
one being integrated against.

## Workshop Methods

| Method | Purpose | When in the flow |
|---|---|---|
| **Event Storming (big picture)** | Full-domain discovery with all stakeholders | New domain, kickoff |
| **Event Storming (process level)** | One business process end-to-end | After big picture, per epic |
| **Event Storming (design level)** | Aggregates, commands, policies for implementation | Before coding a context |
| **Domain Storytelling** | Concrete scenarios as pictographic stories | Validating understanding with experts |
| **Example Mapping** | Rules + examples per story (BDD input) | Ticket scoping after modeling |
| **Bounded Context Canvas** | One-page context contract (in/out, language, policies) | Documenting each discovered context |
| **Aggregate Design Canvas** | Invariants, size, concurrency of one aggregate | Design-level sessions |
| **Core Domain Chart** | Plot contexts by differentiation × complexity | Investment/priority decisions |
| **DDD Starter Modelling Process** | Orchestrates the above: business model → storming → canvases → code | New teams; large transformations |

Facilitation guidance: Event Storming works best with 6–15
participants (big picture 2–4h, process level 4–8h, design level
1.5–2 days). Run Domain Storytelling *before* storming to engage
experts; fill canvases *after* storming — they document, they don't
discover. Timebox Example Mapping at 25 minutes per story.

## Enterprise Patterns Bridge (PoEAA)

For persistence and application structure questions that surface
mid-workshop, route to Fowler's PoEAA vocabulary rather than
inventing terms: Domain Model vs Transaction Script vs Table
Module; Repository vs Data Mapper vs Active Record; Unit of Work;
Identity Map; Lazy Load; Money; Special Case. The workshop names
the pattern; the implementation ticket carries the reference.
(Catalog: `skills/project-audit/references/pattern-catalogs.md`
lists the full PoEAA and GoF tables.)

## Pattern Selection Heuristics

1. **Start with the invariant, not the pattern.** List the rules
   that must never break; the aggregate boundaries fall out.
2. **Model the language, not the database.** Tables are an output,
   never an input, of the domain model.
3. **One pattern per problem.** If a pattern doesn't remove a
   named problem (invariant, coupling, translation), it's decor —
   see `anti-patterns.md` § Speculative Generality.
4. **Escalate integration patterns lazily.** Separate Ways →
   Conformist/ACL → Customer-Supplier → Shared Kernel is a ladder
   of increasing coupling and coordination cost; climb only when
   forced.
5. **CQRS and ES are context-local decisions.** Apply per bounded
   context where the trade-off pays, never as an architecture-wide
   mandate.
