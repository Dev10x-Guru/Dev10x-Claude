# Authorization Patterns — RBAC / ABAC / ReBAC and the Policy Architecture

> Nearly every domain eventually asks "who may issue this command,
> and why?". Authorization is a recurring workshop theme, so it
> gets its own guided section instead of ad-hoc treatment. Run it
> during event storming when actors and commands are on the board.

## When This Section Fires

- Actors multiply beyond "User" and "Admin"
- A command's validity depends on WHO issues it, not just state
- Sharing, delegation, tenancy, or hierarchies appear
- The words "role", "permission", "visibility", "owner" enter the
  ubiquitous language

## Step 1: Classify the Access Questions

For each guarded command, ask which sentence shape grants access:

| Grant sentence shape | Model | Example |
|---|---|---|
| "Because of their position/function" | **RBAC** | "Accountants can post journal entries" |
| "Because of properties of subject, resource, action, or context" | **ABAC** | "Managers may approve expenses < 5000 in their own cost center during business hours" |
| "Because of a relationship chain to the resource" | **ReBAC** | "You can edit this doc because it's in a folder owned by a team you belong to" |
| "Because they hold this invitation/link/token" | **Capability** | "Anyone with this invitation may book one conference slot" |

Most real systems are **hybrid**: RBAC for coarse workforce
access, ABAC conditions on top (tenancy, amount limits, time),
ReBAC where sharing/hierarchy graphs drive access, capabilities
where accountless outsiders need one scoped action. Classify per
command cluster, not once per system.

## Step 2: Decision Guide

| Question | Leans toward |
|---|---|
| Is access derived from a stable org structure? | RBAC |
| Do users create/share resources with each other? | ReBAC |
| Do rules reference context (time, location, amount, tenant)? | ABAC |
| Is delegation ("act on my behalf") required? | ReBAC (+ time-boxed ABAC condition) |
| Multi-tenant with per-tenant roles? | RBAC scoped by tenant attribute (hybrid) |
| Will non-engineers author the rules? | ABAC/policy-engine with a PAP UI |
| Are permission checks needed in list queries ("show only what I can see")? | ReBAC engines (filtering APIs) or ABAC partial evaluation |
| Must people WITHOUT accounts get scoped access? | Capability (bearer invitation) |
| Should a grant be forwardable to someone the system never met? | Capability with explicit transfer rules |

**Detection smells:**
- Role explosion (`editor_projectA_readonly_eu`) → relationships
  or attributes are hiding inside role names → ABAC/ReBAC
- `isAdmin` booleans sprinkled on entities → boolean blindness;
  model the actual grant sentence
- Permission checks inside aggregates → invariants and permissions
  conflated (see Step 4)

## Step 2b: Capability / Bearer-Invitation Access

The model the account-centric trio misses: **possession of an
unforgeable token IS the authorization.** Canonical case (a
school-reservation system): a parent receives an invitation link
to book a parent-teacher conference; the parent forwards it to a
grandparent; the grandparent — who has no account — opens the
link and books a slot. The system authorized the *bearer*, not an
identity.

Fires when: actors will never have accounts; sharing/forwarding
is a feature, not a leak; the granted action is narrow (book one
slot, view one document, upload to one folder).

**Probe questions to ask in the workshop** (each answer becomes a
`[D-NNN]` decision):

| Probe | Decision it forces |
|---|---|
| Who needs access but will never have an account? | Capability vs forced registration |
| What EXACTLY does possession authorize? | Scope — one command cluster, never "the page" |
| May the holder forward it? To anyone, or constrained? | Transferable vs bound; forwarding is a FEATURE to design, not an accident to tolerate |
| Can the forwarder narrow what they pass on? | Attenuation (macaroon-style caveats) vs all-or-nothing |
| What happens when the link leaks publicly? | Blast radius → expiry, single-use, revocation list |
| Does redemption create an identity (guest party) or stay anonymous? | Audit trail + later account-linking seam |
| Does the bearer act as THEMSELVES or on behalf of the inviter? | Delegation semantics — who appears in the domain events? |
| Can the original grantor revoke after forwarding? | Revocation authority chain |

**Design rules:**

- A capability converges on the **same PEP** as the account path —
  redemption presents the token's claims as subject attributes to
  the PDP; do not build a parallel "link access" side door.
- Model the invitation as a first-class aggregate (issued →
  forwarded? → redeemed → expired/revoked) — its lifecycle events
  ARE the audit trail the bearer's anonymity would otherwise lose.
- Party archetype: redemption may create a lightweight Party with
  a role (e.g., `ConferenceBooker`) rather than a full account —
  the account-linking seam stays open at zero cost.
- OAuth scopes are NOT this: scopes bound a client app; a
  capability grants an action to whoever holds it.

## Step 3: The Policy Architecture (XACML/NIST vocabulary)

Name the moving parts explicitly — they map cleanly to DDD:

| Role | Job | DDD mapping |
|---|---|---|
| **PEP** — Policy Enforcement Point | Intercepts the action, asks for a decision, enforces it | Context boundary: application service / API middleware. Never inside aggregates |
| **PDP** — Policy Decision Point | Evaluates policies against the request | Its own supporting/generic subdomain — usually an adopted engine (OPA, Cedar, OpenFGA/SpiceDB) |
| **PIP** — Policy Information Point | Supplies attributes/relationships the PDP needs | Read models / projections fed by domain events |
| **PRP** — Policy Retrieval Point | Stores and serves the policies themselves | Policy repository (versioned; git is legitimate) |
| **PAP** — Policy Administration Point | Where policies are authored and managed | An admin bounded context with its own UI and audit trail |

Workshop move: draw these five as boxes on the context map and
ask "who owns each?" — that conversation surfaces the real
integration contracts (decision request/response = published
language; attribute feeds = PIP contracts).

## Step 4: DDD Rules of Engagement

1. **Invariants ≠ permissions.** Aggregates protect business
   consistency ("order total ≤ credit limit"); the PDP decides
   allowed actions ("this clerk may not approve orders"). Keep
   permission checks OUT of aggregates — enforce at the PEP
   before the command reaches the domain.
2. **Authz is usually a generic subdomain.** Adopt an engine
   (OPA/Rego, AWS Cedar, OpenFGA, SpiceDB) unless authorization
   IS the product's differentiator. Core-domain effort spent on a
   bespoke policy engine is the Golden Hammer in reverse.
3. **Grants belong to the ubiquitous language.** "Approver",
   "Owner", "Delegate" are domain terms — put them in the
   glossary with their grant sentences.
4. **Decisions are domain events.** `AccessGranted`/`AccessDenied`
   (with policy version) are auditable facts — valuable in
   regulated domains; cheap to emit from the PEP.
5. **Model Role with the Party archetype.** Party + Role from
   `archetypes-catalog.md` is the structural home for RBAC; ReBAC
   relations are typed party–resource relationships.

## Anti-Patterns (authz-specific)

| Anti-pattern | Signal | Remedy |
|---|---|---|
| Authz in the UI only | Buttons hidden, API wide open | PEP at the context boundary; UI reads the same decisions |
| Role explosion | Compound role names encode attributes | Factor attributes/relations out of role names (ABAC/ReBAC) |
| Aggregate-embedded checks | `if (!user.canEdit) throw` inside domain code | Move to PEP; pass identity as command metadata, not domain state |
| Scattered policy | Same rule re-implemented per endpoint | Single PDP; policies in the PRP, versioned |
| Scopes-as-permissions | OAuth scopes model fine-grained authz | Scopes bound the CLIENT; user permissions come from the PDP |
| Capability side door | Link access bypasses the PDP ("it's just a share link") | Redeem token → claims → same PEP/PDP as account traffic |
| Unbounded bearer token | Invitation grants "the page" forever, to anyone | Scope to a command cluster + expiry + single-use/revocation |

## Step 5: Record the Decision

Capture as a normal `[D-NNN]` entry: chosen model(s) per command
cluster, engine adopt/build choice, PEP placement, and the PIP
attribute contracts. Stress-test with: "add a new tenant type /
a delegation feature / an external collaborator — which of the
five boxes changes?"

## Sources

- OASIS. *XACML 3.0 Core Specification* (2013) — PEP/PDP/PIP/PAP
  reference architecture. https://docs.oasis-open.org/xacml/3.0/xacml-3.0-core-spec-os-en.html
- Ferraiolo & Kuhn. "Role-Based Access Controls" (1992) + ANSI
  INCITS 359 RBAC standard — the RBAC model. [Verify canonical URL]
- NIST SP 800-162. *Guide to ABAC Definition and Considerations*
  (2014). https://csrc.nist.gov/pubs/sp/800/162/upd2/final
- Pang et al. "Zanzibar: Google's Consistent, Global Authorization
  System" (USENIX ATC 2019) — the ReBAC reference design.
  https://www.usenix.org/conference/atc19/presentation/pang
- W3C TAG. "Good Practices for Capability URLs" (2014 draft) —
  capability-link design guidance. https://www.w3.org/TR/capability-urls/
- Birgisson et al. "Macaroons: Cookies with Contextual Caveats for
  Decentralized Authorization in the Cloud" (NDSS 2014) —
  attenuable bearer tokens. [Verify canonical URL]
- Engines: OPA/Rego https://www.openpolicyagent.org/ · AWS Cedar
  https://www.cedarpolicy.com/ · OpenFGA https://openfga.dev/ ·
  SpiceDB https://authzed.com/
- OAuth 2.0 / OIDC (see `standards-and-references.md`) — identity
  and delegated client access; NOT a permission model.
