# Pattern Catalogs

Hardcoded pattern lists used as fallback when WebFetch is
unavailable. These catalogs are passed to Phase 3 agents.

## Fowler PoEAA (Patterns of Enterprise Application Architecture)

Source: https://martinfowler.com/eaaCatalog/

### Domain Logic Patterns
- Transaction Script
- Domain Model
- Table Module
- Service Layer

### Data Source Architectural Patterns
- Table Data Gateway
- Row Data Gateway
- Active Record
- Data Mapper

### Object-Relational Behavioral Patterns
- Unit of Work
- Identity Map
- Lazy Load

### Object-Relational Structural Patterns
- Identity Field
- Foreign Key Mapping
- Association Table Mapping
- Dependent Mapping
- Embedded Value
- Serialized LOB
- Single Table Inheritance
- Class Table Inheritance
- Concrete Table Inheritance
- Inheritance Mappers

### Object-Relational Metadata Mapping Patterns
- Metadata Mapping
- Query Object
- Repository

### Web Presentation Patterns
- Model View Controller
- Page Controller
- Front Controller
- Template View
- Transform View
- Two Step View
- Application Controller

### Distribution Patterns
- Remote Facade
- Data Transfer Object

### Offline Concurrency Patterns
- Optimistic Offline Lock
- Pessimistic Offline Lock
- Coarse-Grained Lock
- Implicit Lock

### Session State Patterns
- Client Session State
- Server Session State
- Database Session State

### Base Patterns
- Gateway
- Mapper
- Layer Supertype
- Separated Interface
- Registry
- Value Object
- Money
- Special Case
- Plugin
- Service Stub
- Record Set

## Refactoring Guru Design Patterns

Source: https://refactoring.guru/design-patterns/catalog

### Creational
- Factory Method
- Abstract Factory
- Builder
- Prototype
- Singleton

### Structural
- Adapter
- Bridge
- Composite
- Decorator
- Facade
- Flyweight
- Proxy

### Behavioral
- Chain of Responsibility
- Command
- Iterator
- Mediator
- Memento
- Observer
- State
- Strategy
- Template Method
- Visitor

## Software Archetypes

Sources: https://www.softwarearchetypes.com/ (Pilimon/Słota/
Sobótka), Fowler *Analysis Patterns*, Coad *Modeling in Color*,
Arlow & Neustadt *Enterprise Patterns and MDA*. Canonical
recognition table: `references/domain/archetypes-catalog.md`.

### Core Archetypes
- **Party / Role** — people and organizations with their roles.
  Examples: customers, dealers, employees.
- **Moment-Interval (Transaction/Event)** — time-bound business
  happenings. Examples: payments, shipments, orders, rentals.
- **Description** — type-instance catalogs. Examples: product
  catalog entries, make/model classifying vehicles.
- **Quantity / Money** — measures with units. Examples: prices,
  weights, dimensions, tire sizes.
- **Rule** — business rules as data. Examples: pricing rules,
  tax rules, discount policies.
- **Product / Inventory / Order** — composite catalog items,
  stock holdings, fulfillment-tracked requests.
- **Availability / Waitlist / GAP** — time-slotted resources,
  fair queues, assignment optimization.
- **Plan / Accounting** — intent-vs-actual tracking; double-entry
  ledgers with posting rules.

### Framework-Specific Pattern Focus

**Django projects — prioritize:**
- Repository vs Active Record usage
- Service Layer vs fat models
- Unit of Work (transaction.atomic patterns)
- Domain Model health (anemic vs rich)
- Value Object candidates (model fields with validators)

**React/Next.js projects — prioritize:**
- Component composition (Composite, Decorator)
- State management patterns (Observer, Mediator)
- Data fetching patterns (Repository, Gateway)
- Error boundary patterns (Chain of Responsibility)

**Go projects — prioritize:**
- Interface segregation (Separated Interface)
- Functional options (Builder variant)
- Middleware chains (Chain of Responsibility)
- Repository implementations
