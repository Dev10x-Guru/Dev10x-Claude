# PlantUML Patterns for ADRs

Common PlantUML patterns for architecture diagrams.

## Setup

Render one file per call through the shared script. It syntax-checks
first, writes the PNG beside the source, and runs PlantUML under the
SANDBOX security profile, so a local `!include` is refused — keep every
pattern self-contained (see
`${CLAUDE_PLUGIN_ROOT}/references/diagrams/rendering.md`):

```bash
${CLAUDE_PLUGIN_ROOT}/skills/diagram-sequence/scripts/render.sh docs/adr/diagrams/NNNN/component.puml
```

## Component Architecture

Shows system boundaries and component relationships.

```plantuml
@startuml component-architecture
!theme plain
skinparam backgroundColor #FEFEFE
skinparam componentStyle rectangle

title [Feature Name] - Component Architecture

package "External System" {
    [External Component] as Ext
}

package "Frontend" #E3F2FD {
    [UI Component] as UI
    [Client] as Client
    note bottom of UI
      Key responsibility
      described here
    end note
}

package "Backend" {
    package "api (NEW)" #E3F2FD {
        [Mutation/Query] as API
    }

    package "service (NEW)" #E3F2FD {
        [Service Layer] as Service
        [Business Logic] as Logic
    }

    package "client (NEW)" #E3F2FD {
        [External Client] as ExtClient
    }

    package "existing" {
        [Existing Component] as Existing
    }

    package "DEPRECATED" #FFE0E0 {
        [Old Component] as Old
    }
}

cloud "External Service" {
    [API] as ExtAPI
}

database "Database" {
    [table_name] as Table
}

' Connections
UI --> Client : uses
Client --> API : GraphQL
API --> Service
Service --> Logic
Logic --> ExtClient
ExtClient --> ExtAPI : HTTP
Service --> Table : read/write

@enduml
```

**Color conventions:**
- `#E3F2FD` - New components (light blue)
- `#E8F5E9` - Dependencies/utilities (light green)
- `#FFE0E0` - Deprecated (light red)
- No color - Existing components

## Sequence Diagram

Shows flow of operations over time.

```plantuml
@startuml flow-name
!theme plain
skinparam backgroundColor #FEFEFE
skinparam sequenceMessageAlign center

title [Flow Name]

actor "User" as User
participant "Frontend" as FE
participant "Backend\nAPI" as API
participant "Service" as Svc
participant "External\nAPI" as Ext
database "Database" as DB

User -> FE : User action
activate FE

FE -> API : Request
activate API

note over API, Svc
  Important note about
  the interaction
end note

API -> Svc : Process
activate Svc

Svc -> Ext : External call
activate Ext
Ext --> Svc : Response
deactivate Ext

Svc -> DB : Save data
DB --> Svc : OK

Svc --> API : Result
deactivate Svc

API --> FE : Response
deactivate API

FE --> User : Show result
deactivate FE

@enduml
```

## Box Grouping

Group related participants.

```plantuml
@startuml grouped-flow
!theme plain
skinparam backgroundColor #FEFEFE
skinparam sequenceMessageAlign center

title [Flow with Groups]

actor "User" as User

box "Frontend" #E3F2FD
    participant "Page" as Page
    participant "SDK" as SDK
end box

participant "Backend" as BE

box "External" #FFF3E0
    participant "API" as API
    participant "Webhook" as WH
end box

User -> Page : action
Page -> SDK : tokenize
SDK -> API : secure data
API --> SDK : token
SDK --> Page : result

Page -> BE : process(token)
BE -> API : charge
API --> BE : success

' Async webhook
API ->> WH : event
WH ->> BE : notification

@enduml
```

## Activity Diagram

Shows decision flows and processes.

```plantuml
@startuml activity-flow
!theme plain
skinparam backgroundColor #FEFEFE

title [Process Name]

start

:Receive request;

if (Valid?) then (yes)
    :Process data;

    fork
        :Task A;
    fork again
        :Task B;
    end fork

    :Combine results;
else (no)
    :Return error;
    stop
endif

:Return success;

stop

@enduml
```

## State Diagram

Shows state transitions.

```plantuml
@startuml state-diagram
!theme plain
skinparam backgroundColor #FEFEFE

title [Entity] State Transitions

[*] --> Draft

Draft --> Pending : submit()
Draft --> Cancelled : cancel()

Pending --> Approved : approve()
Pending --> Rejected : reject()
Pending --> Cancelled : cancel()

Approved --> Completed : process()
Approved --> Cancelled : cancel()

Rejected --> Draft : revise()

Completed --> [*]
Cancelled --> [*]

@enduml
```

## Tips

### Naming Files

```
component-architecture.puml  → Overview of components
customer-payment-flow.puml   → Specific flow name
invoice-creation-flow.puml   → Another flow
tokenization-flow.puml       → Technical detail flow
webhook-confirmation-flow.puml → Async flow
```

### Notes and Comments

```plantuml
' This is a comment (not rendered)

note over A, B
  Multi-line note
  spanning participants
end note

note left of A
  Note on left
end note

note right of B
  Note on right
end note

note bottom of Component
  Note on component
end note
```

### Arrows

```plantuml
A -> B : sync call
A --> B : sync return
A ->> B : async call (no wait)
A -->> B : async return
A -[#red]> B : colored arrow
A -[#green]-> B : colored return
```

### Activation

```plantuml
A -> B : call
activate B
B -> C : nested call
activate C
C --> B : return
deactivate C
B --> A : return
deactivate B
```
