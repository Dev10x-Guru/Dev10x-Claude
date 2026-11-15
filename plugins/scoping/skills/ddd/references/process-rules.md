# Process Rules for Domain Workshops

These rules govern how Claude works during DDD workshop sessions.
They are distilled from real workshop experience and are non-negotiable.

## Rule 1: Minimize Interruptions, Maximize Progress

**Try to go as long as possible without asking questions.** Make
reasonable assumptions, note the alternatives you considered, and
store unresolved choices as a running list.

Only stop to ask when:
- The choice is genuinely arbitrary (no reasonable default)
- The choice is high-stakes and could go either way
- You've exhausted all possibilities for independent progress

When you DO need input:
- **Batch ALL questions into a single comprehensive set**
- Present as a structured decision menu with options to choose from
- Group related decisions together
- Provide your recommended option with rationale
- Never ask one question, wait, then ask another

## Rule 2: Protect Accumulated Decisions

The `decisions.md` file is the institutional memory. Every entry
represents a real discussion that already happened.

**Never re-derive or silently override existing decisions.** Even if
you think a prior decision was wrong, the user chose it for reasons
that may not be apparent from the document alone.

**To change a decision:**
1. Propose a NEW decision entry (D-NNN)
2. State `supersedes: D-MMM` with the old decision ID
3. Explain why the old one no longer holds
4. Describe downstream impacts of the change
5. Update the old entry's status to `Superseded by D-NNN`

**Always reference decisions by ID** (e.g., [D-014]) when building
on them. This creates a traceable chain of reasoning.

## Rule 3: Genericize Proprietary Data

Reference materials (spreadsheets, specs, client documents) are
behavioral models only. Extract the patterns and calculations.
Replace proprietary specifics with closely related generic examples.

The domain model, workshop records, and all documentation must
never contain:
- Client or company names from reference materials
- Specific financial figures from real projects
- Product names or service names from client systems
- Internal terminology that identifies the client

Use the reference as a source of truth for BEHAVIOR (formulas,
workflows, data structure). Replace IDENTITY (names, amounts,
terminology) with generic equivalents.

## Rule 4: Foundation-Ready, Not Prematurely Built

Design hooks into the foundation so future capabilities arrive as
data extensions, not refactors. Like i18n: bake the type system
support in from day one, activate the features later.

**The rule of thumb:** If adding a nullable field, opening a type
union, or using `string` instead of a closed union costs zero runtime
but saves a data migration later → do it now. If it requires actual
code, abstractions, or infrastructure that aren't used yet → defer.

Examples of good seams:
- `Money { amount, currency }` instead of raw `number` (costs nothing,
  enables multi-currency later)
- `WorkRole = string` instead of `'dev' | 'testing'` (costs nothing,
  enables ResourceCatalog later)
- `node.policyOverlay?: PolicyOverlay` optional field (costs nothing,
  enables hierarchical pricing later)

Examples of premature abstractions to avoid:
- Building a ResourceCatalog when you have 4 fixed roles
- Building dirty-flag recalculation for a 20-item tree
- Building a currency conversion engine for a single-currency app
- Building session versioning for a tool used for 3-month projects

## Rule 5: Plan but Defer Server Dependencies

Features requiring server infrastructure should be:
1. **Scoped** — define what they'd look like
2. **Designed** — document the API/protocol
3. **Deferred** — don't implement until client-side foundation is solid

This applies to: short URL services, cloud accounts, centralized
collaboration, real-time data feeds, webhook integrations.

The MVP is fully serverless. Client-side persistence and P2P
collaboration come first.

## Rule 6: Divide Features into Configuration and Estimation

Keep pricing configuration (PricingPolicy, rules, templates) cleanly
separated from the estimation workspace (nodes, tree, calculations).

Users should be able to:
- Change pricing rules without touching the estimate
- Change estimates without touching pricing rules
- Apply the same pricing policy to different estimates
- Override pricing per-session without affecting the global policy

This separation is the Pricing Archetype's core contribution: the
policy is the "how to price" and the nodes are the "what to price."
