# Integration & Topology — Deploying and Connecting Bounded Contexts

> Context boundaries are a modeling decision; deployment topology
> and integration contracts are separate decisions layered on top.
> Run this section once contexts are named and someone asks "so…
> separate services?". Relationship *patterns* (ACL, OHS, shared
> kernel…) live in `design-patterns.md` § Context mapping — this
> file covers topology, leak prevention, and interface mechanics.

## Step 1: Topology Decision — Modular Monolith vs Split

**Default: modular monolith first** (Fowler, MonolithFirst).
Bounded contexts are enforced as in-process modules; extraction
is earned, not assumed. Decide *per context*, not once globally.

| Question | Points toward split | Points toward staying modular |
|---|---|---|
| Do separate teams own the contexts with different deploy cadences? | Split | Same team, same cadence → modular |
| Does one context need independent scaling (10–100× load)? | Split that context | Uniform load → modular |
| Does a context need a different runtime/stack/data store? | Split | Shared stack fits → modular |
| Must a fault in one context not take down another (regulatory/SLA)? | Split | Shared fate acceptable → modular |
| Are the boundaries stable (6+ months without redrawing)? | Split is safe | Boundaries still moving → NEVER split yet |
| Org maturity: CI/CD, observability, on-call for N services? | Split affordable | Missing platform → modular |

Granularity bounds (Khononov): a service must not be smaller than
an aggregate, and not larger than a bounded context. When in
doubt, deploy multiple contexts together and keep the modules
honest — a modular monolith with clean seams extracts cheaply;
a distributed system with wrong seams merges expensively
(`anti-patterns.md` § Distributed Monolith, § Premature
Microservices).

**Modular-monolith enforcement checklist** (the seams must be
real, not aspirational):

- One module per bounded context; module = the unit you could
  extract
- Schema-per-context (separate schemas or table-name prefixes;
  NO cross-context joins or foreign keys)
- Cross-module calls only through each module's published
  interface; internals not importable (enforce with
  import-linter / ArchUnit / eslint boundaries as a CI fitness
  function)
- Each module owns its migrations, fixtures, and tests

## Step 2: Leak Prevention Between Contexts

What counts as domain leakage:

| Leak | Why it hurts | Fix |
|---|---|---|
| Internal entities / ORM models crossing the boundary | Consumers couple to your schema; refactoring freezes | Translate to published-language DTOs at the boundary |
| Shared database access | Invisible contract; schema drift breaks neighbors | Schema-per-context; integrate via interface, not tables |
| "Shared domain" library with business logic | One model to rule them all, by the back door | Shared kernel ONLY for tiny stable types (Money, IDs); duplicate the rest deliberately |
| Foreign concepts adopted verbatim ("their `Account` is our `Account`") | Ubiquitous-language bleed; Conformist by accident | ACL translates their model into yours at ingestion |
| Fat events carrying another context's internals | Event consumers couple to producer internals | Design event payloads as published language too |
| Leaking IDs with embedded semantics (`ORD-EU-2024-…` parsed downstream) | Hidden coupling to an encoding | Opaque IDs; expose attributes explicitly |

Litmus test per boundary: *"Could the other side change its
internal model without us noticing?"* If no — name the leak and
fix the contract.

## Step 3: Interface Design Between Components

**Choose the interaction style per conversation, not per system:**

| Style | Use when | Contract artifact |
|---|---|---|
| **Query (sync)** | Caller needs an answer now; read-only | OpenAPI / GraphQL schema / gRPC proto |
| **Command (sync or queued)** | Caller requires the action and cares about the outcome | Same + explicit error contract |
| **Event (async)** | Producer announces a fact; consumers react independently | AsyncAPI / event schema registry |

Event payload spectrum: **notification** (ID only, consumer calls
back) → **event-carried state transfer** (fat event, consumer
autonomy, bigger contract surface). Pick per event; document the
choice.

**Contract rules of engagement:**

1. **Contract-first** — the schema (OpenAPI/AsyncAPI/proto) is
   the published language artifact; generate code from it, not
   the reverse.
2. **Versioning: additive only** — new optional fields yes;
   renames/removals are a new version. Consumers follow the
   Tolerant Reader pattern (read what you know, ignore the rest).
3. **Idempotency + correlation** — commands carry idempotency
   keys; every message carries a correlation ID end-to-end.
4. **Consumer-driven contract tests** (e.g., Pact) — each
   consumer's expectations run in the producer's CI; the contract
   is enforced, not documented.
5. **Ownership** — every interface has exactly one producing
   context and a named owner; "shared" interfaces are how shared
   kernels metastasize.

**Workshop move:** for each context-map edge, fill one line:
`<producer> —(style: query/command/event, contract: <artifact>,
pattern: <OHS/ACL/…>)→ <consumer>` — then stress-test: "producer
swaps its database; which consumers notice?" (correct answer:
none).

## Step 4: Record and Stress-Test

Capture per-edge decisions as `[D-NNN]` entries (topology choice,
interaction style, contract artifact, versioning policy). Add a
stress-test scenario: "extract context X to its own deployment —
what breaks?" A clean modular monolith answers: nothing but
infrastructure.

## Sources

- Fowler. "MonolithFirst" (2015) + "Tolerant Reader" (2011) +
  "What do you mean by Event-Driven?" (2017). https://martinfowler.com/
- Newman. *Monolith to Microservices* (2019) — extraction
  patterns; *Building Microservices* 2e (2021).
- Khononov. *Learning DDD* (2021) — granularity bounds, contexts
  vs services.
- Hohpe & Woolf. *Enterprise Integration Patterns* (2003).
  https://www.enterpriseintegrationpatterns.com/ — the messaging
  pattern canon.
- Richardson. *Microservices Patterns* (2018) + https://microservices.io/
  — saga, API composition, CQRS trade-offs.
- Skelton & Pais. *Team Topologies* (2019) — team boundaries ↔
  context boundaries (Conway alignment).
- Pact (consumer-driven contracts). https://pact.io/ · AsyncAPI
  https://www.asyncapi.com/ · import-linter / ArchUnit for
  boundary fitness functions.
