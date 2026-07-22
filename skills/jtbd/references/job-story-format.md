# Job Story Format Reference

Source: https://jtbd.info/replacing-the-user-story-with-the-job-story-af7cdee10c27

## Format

**When** [situation], **[actor] wants to** [motivation], **so [beneficiary] can** [expected outcome].

The actor and beneficiary may be the same or different roles. Always name them
explicitly with a concrete domain role — never first-person ("I", "we") and
never a faceless "the user". Once the actor is named, an anaphoric
back-reference in the outcome clause ("so they can …") is fine.

## Key Principles

### 1. No Personas — Focus on Situation

User stories start with "As a [persona]..." which creates assumptions about
the user. Job stories replace the persona with the **situation** — the context
that creates the need. The same situation can apply to different people.

### 2. Situation Over Implementation

The "When" clause describes the real-world context that triggers the need.
It should be specific enough to be testable but not prescribe a solution.

Good: "When a merchant processes an ACH bank transfer for an order"
Bad:  "When clicking the payment type dropdown"

### 3. Motivation Reveals Anxiety

The "wants to" clause captures what the actor is trying to accomplish.
It often reveals an underlying anxiety or frustration with the current state.

Good: "the cashier wants to select 'ACH' as the payment method"
Bad:  "wants a new enum value"

### 4. Expected Outcome Shows Value

The "so [beneficiary] can" clause describes the measurable benefit or the
problem that goes away. This is what makes the story testable.

Good: "so the merchant can accurately reconcile bank transfer transactions instead of grouping them under 'Other'"
Bad:  "so the system supports ACH"

### 5. Name Actors Explicitly

Always name a concrete domain role ("the merchant", "the billing admin") —
never first-person "I"/"we" and never a faceless "the user". A named role
adds context at a glance. When the actor who triggers the action differs
from the beneficiary who gains the value, name both:

Good: "the billing admin wants to send the customer an SMS, so the customer can pay"
Bad:  "I want to send them an SMS, so they can pay"

### 6. Less Work, Not More Features

The strongest motivations describe an outcome the actor gets with
*less* effort — ideally none. "wants to see / view / check / manage X"
usually describes operating the feature, not the job: seeing is effort
spent on the way to the real outcome. Rewrite toward the end state
("wants X to be obvious at a glance", "wants to be told when…",
"wants the system to handle it").

Exception: in analytics and reporting, insight itself is the
deliverable — "see revenue broken down by channel" is legitimate there,
paired with the decision it enables ("adjust budget allocation").

The same trap hides in **transactional effort verbs** — "wants to
pay / submit / enter / upload X". Nobody wants to *pay* or *submit*;
those name work the actor performs, not the outcome they want. When the
desire reads as an action the actor would gladly skip, name the end
state instead — and re-check whether the role who actually benefits is a
*different* one. A customer paying an invoice is the mechanism; the jobs
are the dealer collecting payment without manual card entry (time saved)
and the vendor capturing the revenue.

Length is a leak detector: one clause each for situation, desire, and
outcome. If the story cannot be read aloud in one breath to a
non-technical stakeholder, it is carrying implementation detail.

## Anti-Patterns

| Anti-Pattern | Problem | Fix |
|---|---|---|
| Technical language | Not understandable by stakeholders | Use business/domain language |
| Solution-focused "When" | Prescribes implementation | Describe the real-world trigger |
| Invented dramatic "When" | A vivid crisis the sources never describe misstates the job | Use the mundane trigger the ticket actually names |
| UI-verb motivation ("wants to see/view/manage") | Describes operating the feature, not the outcome | Name the end state: "wants X to be obvious", "wants to be told" (see Principle 6) |
| Transactional-verb motivation ("wants to pay/submit/enter") | Names work the actor performs, not the outcome — nobody wants to pay; paying is the mechanism | Name the outcome and re-check the actor/beneficiary: "so the dealer can collect payment without manual card entry" (see Principle 6) |
| Capability enumeration (fields, statuses, IDs) | The UI spec wearing a story costume — reader could reconstruct the screen | Collapse the list into the single outcome it buys |
| Naming the replaced artifact ("instead of the old list/panel") | Contrasts with the previous implementation, not the user's pain | Contrast with the pain; prior broken *behavior* is fine, prior *component* is not |
| Vague outcome | Not testable | Be specific about what improves |
| No contrast with current state | Unclear why it matters | Show what's wrong today (an outcome like "keep support calls short" carries it implicitly) |
| First-person "I"/"we", or a faceless "the user" | Hides who is impacted | Name a concrete role: "the cashier", "the customer" (see § Choosing the Actor in `references/git-jtbd.md`) |
| Same actor when roles differ | Hides multi-stakeholder flow | Name both actor and beneficiary when they differ |

## Examples

### Payment Method (e-commerce SaaS)
**When** a merchant processes an ACH bank transfer for an order, **the cashier
wants to** select "ACH" as the payment method, **so the merchant can**
accurately reconcile bank transfer transactions instead of grouping them
under "Other".

### Multi-actor: Invoice SMS (actor ≠ beneficiary)
**When** a merchant sends an invoice for a completed order, **the billing
admin wants to** send the customer an SMS with the payment link, **so the
customer can** pay immediately from their phone without needing email access.

### Performance Fix (SaaS dashboard)
**When** the order list is opened during peak hours, **the support agent
wants to** see results within 2 seconds, **so they can** serve customers
without awkward delays.

### Integration (operations SaaS)
**When** a work item is completed and approved, **the operations manager
wants** the system to automatically sync the record to the accounting system,
**so they can** avoid manual double-entry and reconciliation errors at
month-end.

### Reporting (analytics)
**When** preparing the quarterly business review, **the operations team
wants to** filter revenue by acquisition channel, **so they can** identify
which channels are growing and adjust budget allocation accordingly.
