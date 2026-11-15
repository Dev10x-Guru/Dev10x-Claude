# Phase-Specific Agent Prompts

Instructions for each audit phase agent. The orchestrator injects
project context and passes the relevant section to each agent.

## Phase A: Pattern Catalog

Search the codebase for instances of established design patterns.
Match against three catalogs:

**Fowler PoEAA patterns to look for:**
Repository, Unit of Work, Data Mapper, Active Record, Table Data
Gateway, Row Data Gateway, Identity Map, Lazy Load, Query Object,
Service Layer, Domain Model, Transaction Script, Table Module,
Registry, Plugin, Separated Interface, Gateway, Mapper, Layer
Supertype, Special Case, Money.

**Refactoring Guru patterns to look for:**
Factory Method, Abstract Factory, Builder, Prototype, Singleton,
Adapter, Bridge, Composite, Decorator, Facade, Flyweight, Proxy,
Chain of Responsibility, Command, Iterator, Mediator, Memento,
Observer, State, Strategy, Template Method, Visitor.

**Software Archetypes to look for:**
Catalog/Inventory, Document/Record, Transaction/Event, Party/Role,
Place/Location, Thing/Item, Quantity/Measurement, Rule/Policy.

For each pattern found, classify as:
- **Adopted** — explicitly implemented and named
- **Implicit** — pattern is present but not named or documented
- **Applicable** — codebase would benefit but pattern is absent
- **Missing** — pattern is expected for this architecture but absent

**Search strategy:**
1. Glob for `*repository*`, `*factory*`, `*service*`, `*gateway*`
2. Grep for class definitions with pattern-like names
3. Check `__init__.py` re-exports for public API patterns
4. Look at DI container registrations for service patterns

## Phase B: Domain Model Health

Classify every model/entity in the codebase:

1. **List all models** — glob for model definitions
2. **Count behavioral methods** per model (exclude boilerplate)
3. **Classify**: Active Record (has behavior) vs Anemic (no behavior)
4. **Find Tell Don't Ask violations** — services that read model
   state then mutate externally
5. **Find module-level orchestration** — services iterating over
   related objects and mutating each one

See `references/detection-heuristics.md` for grep patterns.

**Output:** Table of models with classification + list of
Tell Don't Ask violations with file:line locations.

## Phase C: Value Object Discovery

Find primitives that should be encapsulated as Value Objects:

1. **Scan model fields** for `CharField` / `str` fields with
   validators or format constraints
2. **Find repeated validation** — same regex or check in 2+ places
3. **Find normalize/format helpers** — functions that transform
   the same concept in multiple modules
4. **Propose Value Objects** — group related fields and validation
   into candidate VOs

**Common candidates:** email addresses, phone numbers, money/currency,
postal codes, tax IDs, SKUs, measurement units.

## Phase D: Archetype Stress Test

Map codebase modules against Software Archetypes:

1. **Identify archetype instances** — which modules correspond to
   Catalog, Transaction, Party, Document, etc.
2. **Check structural alignment** — does each module have the
   expected substructure for its archetype?
3. **Find archetype violations** — modules mixing concerns from
   different archetypes
4. **Propose corrections** — where archetype boundaries should shift

## Phase E: Concurrency Audit

For each mutating operation in the codebase:

1. **Find all write paths** — `.save()`, `.update()`, `.delete()`,
   `.create()`, bulk operations
2. **Check transaction wrapping** — is the operation inside
   `transaction.atomic`?
3. **Check locking** — does it use `select_for_update()` where
   needed?
4. **Check constraints** — are business-critical uniqueness
   invariants enforced at DB level?
5. **Check error mapping** — are `IntegrityError` exceptions
   caught and mapped to domain exceptions?

See `references/detection-heuristics.md` for grep patterns.

## Phase F: Behavioral Pattern Fit

Evaluate opportunities for behavioral design patterns:

1. **Strategy** — find `if/elif` chains or `match/case` blocks
   that dispatch based on type. These are Strategy candidates.
2. **Chain of Responsibility** — find sequential validation or
   processing steps that could be chained.
3. **Template Method** — find similar methods across subclasses
   with minor variations.
4. **Observer** — find manual notification patterns (signal-like
   calls scattered in service code).
5. **Command** — find operations that need undo, logging, or
   queueing.

**Grep patterns:**
- `if.*type.*==` or `match.*type` (Strategy candidates)
- Sequential `if` blocks in validation functions (CoR candidates)
- Subclasses overriding same-named methods (Template Method)

## Phase G: JTBD Coverage Matrix

Map delivered features against test coverage:

1. **Extract JTBD** from PR titles and bodies (data from Phase 1)
2. **Group by feature area** — cluster similar JTBDs
3. **Find test files** for each feature area
4. **Measure coverage** — which JTBDs have e2e tests, unit tests,
   both, or neither?
5. **Identify gaps** — features with zero or minimal test coverage

**Output:** Matrix with JTBD on rows, test types on columns,
coverage status in cells.

## Phase H: Cross-Cutting Consistency

Check for inconsistent patterns across modules:

1. **Error handling** — do all modules raise exceptions consistently?
   Or do some return None while others raise?
2. **Naming conventions** — `get_by_id` vs `find_by_pk` vs
   `retrieve` across modules
3. **DI usage** — some modules use container, others instantiate
   directly
4. **Pagination** — cursor vs offset vs none
5. **Logging** — structured vs unstructured, consistent log levels
6. **DTOs** — pydantic dataclasses everywhere vs mixed approaches

**Output:** List of inconsistencies with module pairs showing the
divergence and a recommended standard.

## Phase I: Cross-Context Query Use Cases

Detect functions that resolve multiple DI protocols from different
bounded contexts — candidates for extraction into query use cases.

1. **Find multi-protocol resolvers** — scan for functions that
   inject or resolve 3+ protocols from the DI container, especially
   from different bounded contexts
2. **Find data assembly hotspots** — functions with 20+ lines
   assembling data from multiple protocol return values
3. **Find N+1 patterns** — `get_by_id()` or similar single-item
   lookups called inside loops where batch methods exist
4. **Find API type leakage** — modules outside `api/` importing
   from `api/types.py` (framework types in domain layer)

See `references/detection-heuristics.md` § Cross-Context Query
Use Case Candidates for grep patterns.

**Guidance per finding:**
- Extract into `<bc>/queries.py` query use case class
- Return domain DTOs (`<bc>/dtos.py`), not API framework types
- Replace N+1 lookups with batch protocol methods

**Output:** Table of candidate functions with location, protocol
count, estimated assembly lines, and recommended extraction.
