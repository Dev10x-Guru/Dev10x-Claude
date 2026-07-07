# Job Story Examples

Worked examples covering the most common Job Story shapes. The
gating guidance — Guiding Principle (Business ROI First), Trace
upward, Subject Selection by PR Type, and the Anti-pattern
table — lives inline in `SKILL.md`.

## Example 1: Feature with parent ticket context

**Domain:** E-commerce SaaS

**Context found:**
- FEAT-401 (sub-task): "Add ACH to PaymentMethod enum"
- FEAT-398 (parent): "Support ACH bank transfer payments"
- User quote in parent: "@sarah said: enterprise clients all pay via ACH,
  they keep asking for it"

**Output:**
> **When** a merchant processes an ACH bank transfer for an order, **the
> cashier wants to** select "ACH" as the payment method, **so the merchant
> can** accurately reconcile bank transfer transactions instead of grouping
> them under "Other".

## Example 2: Feature with different actor and beneficiary

**Domain:** SaaS billing

**Context found:**
- BILL-230: "Send invoice link via SMS after invoice is created"
- The billing admin initiates the invoice; the customer receives and pays

**Output:**
> **When** a merchant sends an invoice for a completed order, **the billing
> admin wants to** send the customer an SMS with the payment link, **so the
> customer can** pay immediately from their phone without needing email
> access.

Note: Actor (billing admin) and beneficiary (customer) are explicitly named
because they differ — this immediately communicates who does what and who
gains.

## Example 3: Bug fix

**Domain:** HR / Payroll SaaS

**Context found:**
- BUG-500: "Payroll calculation times out during month-end run"
- Parent: "Payroll failures at month-end closing"

**Output:**
> **When** running payroll during month-end closing, **the payroll manager
> wants** the calculation to complete reliably, **so the finance team can**
> avoid missed pay dates and manual correction workflows.

## Example 4: Internal tooling

**Domain:** Analytics / Operations

**Context found:**
- OPS-300: "Add revenue breakdown by channel to admin dashboard"
- No parent ticket

**Output:**
> **When** preparing the quarterly business review, **the operations team
> wants to** see revenue broken down by acquisition channel and region,
> **so they can** identify underperforming channels and adjust budget
> allocation without exporting to spreadsheets.

## Example 5: Refactoring / preparatory work (trace upward)

**Domain:** SaaS notifications

**Context found:**
- FEAT-230 (sub-task): "Move notification dispatch to shared infrastructure"
- Parent: roadmap item to ship SMS billing reminders so unpaid invoices
  clear faster
- PR diff: extracts email sender into a generic outbox, promotes to a
  standalone module

**Output:**
> **When** a customer has an unpaid invoice nearing its due date, **the
> billing admin wants to** reach the customer through whichever channel
> they actually monitor — email, SMS, or push — **so the vendor can**
> shorten days-sales-outstanding and customers can settle invoices before
> late fees apply.

Note: The actor is not the engineer extracting the outbox. It is the
billing admin whose collection workflow benefits once SMS lands. The
refactor PR's story names *that* outcome, even though the SMS feature
ships in a later PR. This is the trace-upward principle (see *Trace
upward for plumbing PRs* in the *Guiding Principle* section of
`SKILL.md`).

## Example 6: Pure dependency-bump PR (trace upward)

**Domain:** Multi-tenant configurator (any SaaS where customers manage
their own templates / forms / menus)

**Context found:**
- Library upgrade ticket: adopt ULIDs to enable client-assigned record ids
- Linked architecture decision: collapse a row-level CRUD GraphQL surface
  into a single atomic-save document mutation; client-side id generation
  is a prerequisite

**Output:**
> **When** an end customer reconfigures their template — adding a new
> option, repricing an item, or renaming a field — **the end customer
> wants to** save the whole document in one atomic action and see it live
> immediately, **so the vendor can** stop absorbing support hours on
> customer-driven configuration edits and customers can roll out changes
> same-day.

Note: The dep bump itself does not ship the feature. The Job Story names
the *downstream* business outcome the library unblocks. The library is
the mechanism, never the actor.

## Example 7: UI-consolidation PR — a real correction spiral

**Domain:** Any SaaS where staff pair/configure hardware or accounts
for a customer site

**Context found:**
- Follow-up ticket to a merged PR: retire an old inline device list in
  favor of a newer summary + details view
- Parent context: devices are configured during customer onboarding;
  support also fields orientation calls about the current setup

This case took four drafts because each round fixed one leak and
sprang another. The spiral, draft by draft:

**Draft 1 — rejected (UI verb + replaced-artifact contrast):**
> …**staff want to** see and manage every paired device through the
> single summary + details view **instead of** a second, redundant
> inline list, **so they can** confirm each device's live status in
> one consistent place…

An ROI tail ("cutting support time") was tacked on, but the spine of
the sentence was the UI. Actors don't want to *see and manage* —
they want less work.

**Draft 2 — rejected (invented drama):**
> **When** a payment device won't take payments mid-shift…

Overcorrecting toward "vivid" fabricated a crisis the ticket never
described. The real situation was mundane: routine onboarding and
support-call orientation.

**Draft 3 — rejected (capability enumeration, artifact contrast again):**
> …**staff want** one diagnostic view that lays out each device's
> status, pairing code, and location… **instead of** piecing the
> picture together **from a redundant second list**…

Right situation now, but enumerating the surfaced fields is the UI
spec wearing a story costume — and the replaced artifact crept back
in as the contrast.

**Accepted:**
> **When** onboarding a store's payment devices — or helping a
> customer who calls in about them — **staff want** the setup to be
> obvious at a glance, **so the vendor can** get the store live sooner
> and keep support calls short.

Note: The accepted draft dropped every mechanism noun, dropped the
what-we-replaced contrast entirely, and shortened to one clause per
slot — situation / effort-free desire / two ROI outcomes. The
contrast with the old pain survives *implicitly* in "keep support
calls short". Each rejected draft maps to a red-flag row in the
*Anti-pattern: Pseudo-Business Value* table in `SKILL.md`.
