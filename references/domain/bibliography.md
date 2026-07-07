# Workshop Bibliography

> Curated, verified references for DDD workshops. Compact format:
> one entry per line — Author, *Title* (Year). Link — what a
> facilitator gets from it. `[Verify]` marks entries whose exact
> citation or availability was not fully confirmed.

## DDD Canon (books)

- Evans, Eric. *Domain-Driven Design* (2003). Addison-Wesley — the foundational text: ubiquitous language, strategic + tactical design.
- Vernon, Vaughn. *Implementing Domain-Driven Design* (2013). Addison-Wesley — the pragmatic companion; aggregate rules, CQRS/ES in practice.
- Vernon, Vaughn. *Domain-Driven Design Distilled* (2016). Addison-Wesley — ~170-page essentials; best first read for participants.
- Millett, Scott & Tune, Nick. *Patterns, Principles, and Practices of DDD* (2015). Wiley — broad pattern catalog with worked examples.
- Khononov, Vlad. *Learning Domain-Driven Design* (2021). O'Reilly — modern heuristics linking strategy to architecture styles.
- Brandolini, Alberto. *Introducing EventStorming* (Leanpub, ongoing). https://leanpub.com/introducing_eventstorming — the method, from its inventor.
- Hofer, Stefan & Schwentner, Henning. *Domain Storytelling* (2022). Addison-Wesley — pictographic narrative modeling; pairs with storming.

## Archetypes & Analysis Patterns

- Fowler, Martin. *Analysis Patterns: Reusable Object Models* (1997). Addison-Wesley — 70+ patterns: Party, Accountability, Observation, Quantity, Money, Posting Rules, Plan. Free UML supplements: https://martinfowler.com/apsupp/
- Coad, Peter; Lefebvre, Eric; De Luca, Jeff. *Java Modeling in Color with UML* (1999). Prentice Hall — Moment-Interval, Role, Description, Party/Place/Thing; the Domain-Neutral Component.
- Arlow, Jim & Neustadt, Ila. *Enterprise Patterns and MDA* (2003). Addison-Wesley — Party, PartyRelationship, CRM, Product, Inventory, Order archetype patterns in full UML.
- Pilimon, Słota, Sobótka. *Software Archetypes* (active). https://www.softwarearchetypes.com/ + https://github.com/Software-Archetypes/archetypes — runnable modern archetypes: Availability, Waitlist, GAP, Configurator, Pricing.
- Piho et al. "Towards Archetypes-Based Software Development" (2010). Springer, DOI 10.1007/978-90-481-9112-3_97 — formalizes archetype-based development. [Verify author list]
- Silverston, Len. *The Data Model Resource Book, Vol. 1* (2001). Wiley — universal data models: Party, Person, Organization, Roles.
- Hay, David C. *Data Model Patterns: Conventions of Thought* (1996). Dorset House — party abstraction and relationship modeling.

## Enterprise & Design Patterns

- Fowler, Martin. *Patterns of Enterprise Application Architecture* (2002). Addison-Wesley — Repository, Unit of Work, Money, Domain Model vs Transaction Script. Catalog: https://martinfowler.com/eaaCatalog/
- Gamma, Helm, Johnson, Vlissides. *Design Patterns* (1994). Addison-Wesley — GoF creational/structural/behavioral catalog. Modern index: https://refactoring.guru/design-patterns/catalog
- Fowler, Martin & Beck, Kent. *Refactoring* (2nd ed., 2018). Addison-Wesley — code smells that signal modeling problems. https://refactoring.com
- Vernon, Vaughn. "Effective Aggregate Design" (2011). https://www.dddcommunity.org/library/vernon_2011/ — the three-part aggregate sizing essay.
- Fowler, Martin. bliki: "BoundedContext", "CQRS", "EventSourcing", "AnemicDomainModel", "MonolithFirst". https://martinfowler.com/bliki/ — canonical short definitions.

## Anti-Patterns

- Brown, Malveau, McCormick, Mowbray. *AntiPatterns* (1998). Wiley — Blob, Lava Flow, Golden Hammer, Design by Committee.
- Foote, Brian & Yoder, Joseph. "Big Ball of Mud" (1997). https://www.laputan.org/mud/ — the original paper.
- Spolsky, Joel. "The Law of Leaky Abstractions" (2002). https://www.joelonsoftware.com/2002/11/11/the-law-of-leaky-abstractions/
- Nygard, Michael. "The Entity Service Antipattern" (2017). https://www.michaelnygard.com/blog/2017/12/the-entity-service-antipattern/
- Newman, Sam. *Monolith to Microservices* (2019). O'Reilly — distributed-monolith avoidance; extraction patterns.
- luzkan. "Code Smells Catalog". https://luzkan.github.io/smells/ — indexed Fowler/Beck smells with examples.

## Workshop Methods & Community

- DDD Crew. Starter Modelling Process / Bounded Context Canvas / Aggregate Design Canvas / Context Mapping cheat sheet / free learning resources. https://github.com/ddd-crew — printable tools for every stage.
- Cucumber. "Example Mapping". https://cucumber.io/docs/bdd/example-mapping/ — 25-minute story refinement.
- Virtual DDD community. https://virtualddd.com/ — meetups, recorded sessions.
- DDD community library. https://www.dddcommunity.org/ — Evans' post-2003 writings and essays.
- Kalele (Vernon). https://kalele.io/ — training + CC-licensed essays.
- AWS Prescriptive Guidance — saga & transactional outbox. https://docs.aws.amazon.com/prescriptive-guidance/
- Microsoft Learn — tactical DDD for microservices. https://learn.microsoft.com/en-us/azure/architecture/

## Domain References

### Party / identity / organization
- Fowler. *Analysis Patterns* ch. 2 (Accountability). Free diagrams: https://martinfowler.com/apsupp/apchap2.pdf
- Silverston Vol. 1 Party chapter — the universal Party/Role decomposition (~2h facilitator ramp).

### Money / ledgers / accounting
- Fowler. "Accounting Narrative" (dev patterns). https://martinfowler.com/eaaDev/AccountingNarrative.html — Account/Entry/Transaction.
- Kleppmann, Martin. "Accounting for Computer Scientists" (2011). https://martin.kleppmann.com/2011/03/07/accounting-for-computer-scientists.html — ledger as a graph.
- McCarthy, William E. "The REA Accounting Model" (1982). The Accounting Review — Resource-Event-Agent ontology. [Verify original URL]
- Stripe Engineering. "Ledger" (2024). https://stripe.dev/blog/ledger-stripe-system-for-tracking-and-validating-money-movement — production immutable ledger at 5B events/day.

### Pricing / billing / subscriptions
- Stripe Engineering. "Scalable metered billing" (2024). https://stripe.dev/blog/implementing-scalable-metered-billing-with-stripe-how-edgee-handles-billions-of-events
- Chargebee Engineering. "Fastest usage-based billing engine" (2024). https://www.chargebee.com/blog/fastest-usage-engine/
- `pricing-pipeline.md` (this directory) — the worked Pricing-archetype example.

### Inventory / catalog / ordering
- Silverston, Len. *The Data Model Resource Book, Vol. 2* (2001). Wiley — industry-specific models incl. ordering. [Verify availability]
- Shopify dev docs. "Orders & fulfillment". https://shopify.dev/docs/apps/build/orders-fulfillment — FulfillmentOrder state machine.

### Scheduling / calendars / temporal
- RFC 5545 iCalendar (IETF, 2009). https://datatracker.ietf.org/doc/html/rfc5545 — RRULE recurrence model; settles calendar vocabulary.
- Fowler. "Recurring Events for Calendars" (1997). https://martinfowler.com/apsupp/recurring.pdf — temporal expressions.
- Allen, James F. "Maintaining Knowledge about Temporal Intervals" (CACM, 1983) — the 13 interval relations. [Verify canonical URL]
- Snodgrass, Richard. *Developing Time-Oriented Database Applications in SQL* (2000). Free PDF: https://www2.cs.arizona.edu/~rts/tdbbook.pdf — bitemporal modeling.

### Workflow / state machines
- van der Aalst et al. Workflow Patterns. http://www.workflowpatterns.com/ — 43 control-flow patterns.
- Harel, David. "Statecharts: A Visual Formalism for Complex Systems". Science of Computer Programming 8(3) (1987), 231–274 — hierarchy + concurrency for FSMs.

### Integration & topology
- Hohpe, Gregor & Woolf, Bobby. *Enterprise Integration Patterns* (2003). Addison-Wesley. https://www.enterpriseintegrationpatterns.com/ — the messaging pattern canon.
- Richardson, Chris. *Microservices Patterns* (2018). Manning. https://microservices.io/ — saga, API composition, decomposition trade-offs.
- Newman, Sam. *Building Microservices* (2nd ed., 2021). O'Reilly — service design and integration end to end.
- Skelton, Matthew & Pais, Manuel. *Team Topologies* (2019). IT Revolution — team boundaries ↔ context boundaries (Conway alignment).
- Fowler. "Tolerant Reader" (2011); "What do you mean by Event-Driven?" (2017). https://martinfowler.com/ — contract evolution; event payload styles.
- Pact (consumer-driven contract testing). https://pact.io/ · AsyncAPI. https://www.asyncapi.com/

### Collaboration / offline-first
- Shapiro, Preguiça, Baquero, Zawirski. "Conflict-free Replicated Data Types" (SSS 2011). Springer LNCS 6976 — CRDT foundations; free preprints via INRIA HAL.
- Kleppmann, Wiggins, van Hardenberg, McGranaghan. "Local-First Software" (Onward! 2019). https://www.inkandswitch.com/essay/local-first/ — data ownership + CRDTs in practice.

## Industry Standards

Domain-to-standard map with "what to steal" guidance:
`standards-and-references.md`. `[Verify]` = confirmed via
secondary sources only (standards body blocks automated access).

- ISO/IEC/IEEE 42010:2022. Architecture description. https://www.iso.org/standard/74393.html
- Brown, Simon. C4 model. https://c4model.com/ — containers ≈ contexts, components ≈ aggregates.
- Starke & Hruschka. arc42 template. https://arc42.org/overview
- ISO/IEC 25010:2023. Product quality model. https://www.iso.org/standard/78176.html [Verify]
- McCarthy, W.E. "The REA Accounting Model". The Accounting Review 57(3):554–578 (1982). https://www.williamemccarthy.com — Resource–Event–Agent + duality.
- ISO 20022. Financial messaging. https://www.iso20022.org/iso-20022-standard — message families as context contracts.
- ISO 4217. Currency codes. https://www.iso.org/iso-4217-currency-codes.html [Verify] — the Money VO's currency field.
- OMG UML 2.5.1 / BPMN 2.0.2 / DMN 1.5 / SBVR 1.5. https://www.omg.org/spec/ — modeling grammar for aggregates, processes, rules, vocabulary.
- schema.org v30+. https://schema.org/version/latest — starter entity ontology.
- GS1 General Specifications v26 + EPCIS 2.0. https://www.gs1.org/ + https://ref.gs1.org/standards/epcis/ — identification keys as VOs; 5 event types as domain-event shapes.
- OAGIS connectSpec v10.12. https://oagi.org/ — BOD noun+verb grammar.
- ISO 8000. Data quality & master data. https://www.iso.org/standard/81745.html [Verify]
- ARTS ODM v7.3 (OMG/NRF). https://www.omg.org/retail-depository/arts-odm-73/ — retail contexts + glossary.
- ACORD Reference Architecture v2.11. https://www.acord.org/standards-architecture/reference-architecture [Verify] — insurance vocabulary.
- HL7 FHIR (R4 production norm; R5 current). https://hl7.org/fhir/R5/ — Resources as aggregate roots.
- TM Forum SID (GB922). https://www.tmforum.org [Verify] — telecom C/P/S/R layering.
- BIAN Service Landscape 14.0. https://bian.org/servicelandscape-14-0/ — Service Domains ≈ bounded contexts.
- EMVCo Specifications. https://www.emvco.com/specifications/ [Verify] — card-present payment context.
- PCI DSS v4.0.1. https://www.pcisecuritystandards.org/ [Verify] — CDE as isolated context.
- UN/EDIFACT (UNECE; ISO 9735). https://unece.org/trade/uncefact/introducing-unedifact [Verify] — EDI document vocabulary.
- HR Open Standards (ex HR-XML). https://www.hropenstandards.org/ [Verify] — HR entity taxonomy.
- IETF RFC 6749 OAuth 2.0 + OpenID Connect Core 1.0. https://datatracker.ietf.org/doc/html/rfc6749 + https://openid.net/specs/openid-connect-core-1_0.html — identity/access VOs.
- OASIS XACML 3.0 Core (2013). https://docs.oasis-open.org/xacml/3.0/xacml-3.0-core-spec-os-en.html — PEP/PDP/PIP/PAP reference architecture.
- NIST SP 800-162. Guide to ABAC (2014). https://csrc.nist.gov/pubs/sp/800/162/upd2/final
- Ferraiolo & Kuhn. "Role-Based Access Controls" (1992); ANSI INCITS 359 RBAC. [Verify canonical URL]
- Pang et al. "Zanzibar: Google's Consistent, Global Authorization System" (USENIX ATC 2019). https://www.usenix.org/conference/atc19/presentation/pang — the ReBAC reference design.
- Policy engines: OPA https://www.openpolicyagent.org/ · Cedar https://www.cedarpolicy.com/ · OpenFGA https://openfga.dev/ · SpiceDB https://authzed.com/
- IANA Time Zone Database. https://www.iana.org/time-zones — tz identifiers as VOs.
- UCUM 2.2. https://ucum.org/ucum — machine-parseable units for Quantity VOs.
- ISO 80000. Quantities and units (ISQ). https://www.iso.org/standard/76921.html [Verify]

## Facilitator Ramp — read before a workshop in the domain

1. RFC 5545 (~30 min) — scheduling vocabulary
2. Fowler Accounting Narrative (~45 min) — ledger architecture
3. Workflow Patterns overview (~1 h) — process vocabulary
4. Kleppmann "Local-First" (~1.5 h) — collaboration mental model
5. Silverston Vol. 1 Party chapter (~2 h) — universal archetypes
