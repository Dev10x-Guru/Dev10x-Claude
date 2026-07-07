# Anti-Patterns to Avoid

> Named failure modes with detection signals and remedies, mapped
> to the workshop stage where each is caught. Sources in
> `bibliography.md`.

## Modeling Anti-Patterns

| Anti-pattern | Detection signals | Remedy |
|---|---|---|
| **Anemic Domain Model** (Fowler) | Entities are getters/setters; all logic in "services" | Move invariants and behavior into aggregates; services orchestrate only |
| **Smart UI** (Evans) | Business rules in UI handlers/components | Extract a domain layer; UI renders and dispatches commands |
| **God Object / Blob** | One entity with 10+ mixed-semantics fields; every feature touches it | Decompose by archetype (`archetypes-catalog.md`); split contexts |
| **Primitive Obsession** | Raw `number`/`string` for money, ratios, IDs, units | Value objects (Quantity archetype) |
| **One Model to Rule Them All** | Same "Customer"/"Product" class serves every department | Split by bounded context; map translations explicitly |
| **CRUD-Driven Design** | Requirements phrased as create/update/delete on records | Event-storm the actual behavior; find the verbs and invariants |
| **Ubiquitous Language Drift** | Code names ≠ expert vocabulary; glossary stale | Rename toward the language; glossary is part of done |
| **Feature Envy** | Logic in one object constantly reads another's data | Move behavior to the data it envies (often into the aggregate) |

## Aggregate & Consistency Anti-Patterns

| Anti-pattern | Detection signals | Remedy |
|---|---|---|
| **Aggregate Cluster** | One aggregate loads half the object graph; lock contention | Vernon's rules: small aggregates, reference by ID |
| **Cross-Aggregate Transaction** | One use case commits 2+ aggregates atomically | Domain events + eventual consistency; re-examine boundaries |
| **Repository-per-Table** | Repositories mirror the schema, not aggregate roots | One repository per aggregate root; read models for queries |
| **Leaky Aggregate** | Callers reach through the root to mutate children | All mutations via root methods enforcing invariants |
| **Invariant by Convention** | "Everyone knows you must call recalc() after edit" | Make illegal states unrepresentable; enforce in the aggregate |

## Architecture Anti-Patterns

| Anti-pattern | Detection signals | Remedy |
|---|---|---|
| **Big Ball of Mud** (Foote & Yoder) | No discernible boundaries; everything imports everything | Identify seams via event storming; strangler-fig extraction |
| **Distributed Monolith** | Microservices that deploy/fail together; chatty sync calls | Merge back or re-cut along context boundaries (Monolith First) |
| **Premature Microservices** | Services split before context boundaries are stable | Modular monolith first; extract when boundaries prove stable |
| **Event Sourcing Everywhere** | ES mandated architecture-wide, incl. CRUD contexts | ES per context where audit/replay is a domain need |
| **Premature CQRS** | Two models maintained where reads = writes | Collapse until read/write shapes actually diverge |
| **Shared Database Integration** | Contexts integrate by reading each other's tables | Published language / OHS / events; own your data |
| **Entity Service** (Nygard) | Services named after nouns (CustomerService) owning no process | Services around capabilities/processes, not table rows |
| **Golden Hammer** | Same pattern applied to every problem ("everything is a saga") | Match pattern to named problem; see selection heuristics |
| **Leaky Abstraction** (Spolsky) | Consumers must understand internals to use the API safely | Redesign the boundary; make escape hatches explicit |
| **Lava Flow** | Dead code and obsolete decisions frozen in place, feared | Tests as safety net; delete with git as the archive |

## Process Anti-Patterns (workshop-time)

| Anti-pattern | Detection signals | Remedy |
|---|---|---|
| **Over-Detailing** | Capturing attributes/validations during big-picture storming | Events only at discovery; details at design level |
| **Implementation-First Focus** | "How do we build it?" before "what happens?" | Park tech talk; return to domain events and language |
| **Analysis Paralysis** | Modeling rounds without a decision recorded | Timebox; record D-NNN with "good enough" + revisit trigger |
| **Design by Committee** | Every voice averaged into a shapeless model | Facilitator decides after hearing; alternatives into decision log |
| **Architecture Astronauts** (Spolsky) | Abstractions nobody asked for; meta-models | Anchor to concrete domain events from the storming board |
| **Speculative Generality** (Fowler) | Hooks/parameters "for later" with no trigger | Foundation-ready rule: zero-cost seams yes, unused code no |
| **Decision Amnesia** | Re-debating settled questions each session | Append-only `decisions.md`; supersede explicitly ([D-NNN]) |
| **Proprietary Leak** | Client names/figures in model docs | Genericize per process-rules.md Rule 3 |

## Stage Mapping — where each gets caught

| Workshop stage | Watch for |
|---|---|
| Event storming | CRUD-driven design, one-model-to-rule-them-all, smart UI, over-detailing, implementation-first focus |
| Aggregate design | Aggregate cluster, cross-aggregate transactions, anemic model, primitive obsession |
| Context mapping | Shared database, distributed monolith, conformist-by-accident, language drift |
| Stress testing | Speculative generality, golden hammer, premature CQRS/ES/microservices |
| Decision capture | Analysis paralysis, design by committee, decision amnesia |

## The Tension to Manage

**Foundation-ready vs YAGNI.** The skill's own rule (process-rules
Rule 4) permits zero-runtime-cost seams (nullable field, open
union) and forbids unused abstractions. Every stress-test "add the
seam now?" question is adjudicated against that rule — seams are
cheap options, abstractions are inventory. When in doubt: data
extensions now, code extensions later.
