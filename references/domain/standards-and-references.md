# Industry Standards & Reference Models

> Standards are pre-validated domain models. Before inventing a
> vocabulary in a workshop, check whether an industry standard has
> already settled it — then *steal the vocabulary, not the schema*.
> Entries marked `[Verify]` were confirmed via secondary sources
> only (the standards body blocks automated access); open the
> official page before quoting a version to participants.

## How to Use Standards in a Workshop

1. **Published Language candidates** — when two contexts integrate
   and an industry standard covers the exchange, prefer it over an
   invented contract (`design-patterns.md` § Published Language).
2. **Vocabulary seeding** — a standard's entity names are a
   ready-made glossary starter for that domain's context.
3. **Boundary inspiration** — several standards decompose their
   industry into modules that map almost 1:1 to bounded contexts.
4. **Never adopt wholesale** — standards are integration models,
   not domain models. Model your core domain in your language and
   translate at the boundary (ACL); conforming your internals to a
   standard is the Conformist pattern chosen by accident.

## Architecture & Documentation

| Standard | What to steal |
|---|---|
| ISO/IEC/IEEE 42010:2022 | Stakeholder → concern → viewpoint → view chain to justify context boundaries; recorded rationale for aggregate decisions |
| C4 model (c4model.com) | Level-2 Containers ≈ bounded contexts; Level-3 Components ≈ aggregates; System Landscape ≈ context map |
| arc42 (arc42.org) | §3 Context = domain boundaries; §5 Building blocks = aggregates; §12 Glossary = ubiquitous language |
| ISO/IEC 25010:2023 `[Verify]` | Quality characteristics as a per-context cross-cutting checklist |

## Modeling Grammar (cross-domain)

| Standard | What to steal |
|---|---|
| UML 2.5.1 (OMG) | Class/package/state/sequence vocabulary; composition = aggregate boundary; state machines = aggregate lifecycles |
| BPMN 2.0.2 (OMG) | Pools/lanes = context ownership; message flows between pools = integration contracts; gateways reveal sagas |
| DMN 1.5 (OMG) | Decision tables externalize domain rules into testable policies (pairs with the Rule archetype) |
| SBVR 1.5 (OMG) | Noun/verb concepts + structured-English "it is obligatory that…" for glossaries and invariants |
| schema.org (v30+) | Thing-rooted type hierarchy as a starter ontology; Action types as event/command naming |
| REA (McCarthy 1982) | Resource–Event–Agent triad + duality (give ↔ take counter-events) for ANY economic exchange; ledgers as projections |

## Per-Domain Reference Models

| Domain | Steal from | The move |
|---|---|---|
| Banking | BIAN Service Landscape | Service Domains map ~1:1 to candidate bounded contexts; Behavior Qualifiers → aggregate operations |
| Payments | ISO 20022; ISO 4217 `[Verify]`; EMV `[Verify]`; PCI DSS `[Verify]` | Message families (pain/pacs/camt) → context contracts; 4217 settles the Money VO (code + minor-unit exponent); CDE = isolated sensitive context |
| Healthcare | HL7 FHIR (R4 = production norm) | Resources (Patient, Encounter, Observation) are near-perfect aggregate roots; reference graph = context relationships |
| Retail | ARTS ODM v7.3 (OMG/NRF); GS1 GTIN | Subject areas (Transaction, Item/SKU, Tender, Loyalty) as candidate contexts; GTIN class-identity vs SSCC instance-identity teaches entity-identity design |
| Insurance | ACORD Reference Architecture `[Verify]` | Policy / Party / Insurable Object / Claim / Coverage vocabulary; capability model → context boundaries |
| Telecom | TM Forum SID (GB922) `[Verify]` | Customer/Product/Service/Resource layering; ABEs → bounded contexts |
| Logistics / supply chain | GS1 EPCIS 2.0; UN/EDIFACT `[Verify]` | EPCIS 5 event types + What/When/Where/Why/How = canonical domain-event shapes; EDIFACT message types = document/command vocab |
| Enterprise integration | OAGIS connectSpec | BOD noun+verb grammar: noun ≈ aggregate root, verb+noun ≈ command/event; envelope pattern |
| HR | HR Open Standards (ex HR-XML) `[Verify]` | Entity taxonomy (Candidate, Assignment, TimeCard); JDX skills modeling |
| Time & scheduling | RFC 5545; IANA tz | RRULE as the reference recurrence VO; store the tz ID, resolve the offset at read time |
| Identity & access | OAuth 2.0 (RFC 6749); OpenID Connect Core | Roles as context actors; grants as strategy VOs; ID Token as a signed identity VO |
| Authorization | XACML 3.0 (OASIS); NIST SP 800-162 (ABAC); INCITS 359 (RBAC) `[Verify]`; Zanzibar (ReBAC) | PEP/PDP/PIP/PRP/PAP architecture roles; RBAC/ABAC/ReBAC decision guide in `authz-patterns.md` |
| Units & measures | UCUM 2.2; ISO 80000 `[Verify]` | Composable machine-parseable Unit/Quantity VO; ISQ 7 base quantities as the dimension model |
| Master data | ISO 8000 `[Verify]` | Master-vs-transactional split; quality dimensions as aggregate invariants |
| Product/web entities | GS1 General Specifications; schema.org | Identification keys (GTIN/GLN/SSCC) as value objects and event-correlation IDs |

## Workshop Quick Answers

- **"How should we model money?"** → ISO 4217 currency code +
  minor-unit exponent inside a Money VO (Quantity archetype).
- **"How do we model recurring appointments?"** → RFC 5545 RRULE
  semantics; don't invent recurrence flags.
- **"What timezone field?"** → IANA tz identifier, never a raw
  offset.
- **"What unit type?"** → UCUM expression string, parsed to a
  Quantity VO.
- **"What events should the supply chain emit?"** → EPCIS event
  types with What/When/Where/Why/How dimensions.
- **"Is our context decomposition sane for a bank/telecom/
  hospital?"** → diff it against BIAN / TM Forum SID / FHIR — a
  large mismatch is either your differentiator or your mistake;
  find out which.

Full citations with versions and verification status:
`bibliography.md` § Industry Standards.
