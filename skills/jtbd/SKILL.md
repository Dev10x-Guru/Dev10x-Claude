---
name: Dev10x:jtbd
invocation-name: Dev10x:jtbd
description: >
  Pure JTBD story drafting skill. Gathers context from issue tracker
  tickets, parent tickets, and PR diffs to craft a situation-driven Job
  Story with explicit actor and beneficiary. Returns the draft string
  with no side effects.
  TRIGGER when: drafting a JTBD Job Story for a ticket, PR, or release.
  DO NOT TRIGGER when: Job Story already exists on the target, or writing
  commit messages (use Dev10x:git-commit).
user-invocable: false
allowed-tools:
  - AskUserQuestion
  - Bash(gh pr view:*)
  - Bash(gh pr diff:*)
  - Bash(gh pr list:*)
  - Bash(git log:*)
  - Bash(git diff:*)
  - mcp__claude_ai_Linear__get_issue
  - mcp__claude_ai_Linear__list_issues
  - mcp__claude_ai_Linear__list_comments
  - Bash(curl:*atlassian.net*)
---

# Dev10x:jtbd — Pure Job Story Drafting

## Orchestration

This skill follows `references/task-orchestration.md` patterns.
Create a task at invocation, mark completed when done:

**REQUIRED: Create a task at invocation.** Execute at startup:

1. `TaskCreate(subject="Draft JTBD Job Story", activeForm="Drafting Job Story")`

Mark completed when done: `TaskUpdate(taskId, status="completed")`

## Overview

This is the **foundational JTBD skill** that provides reusable context
gathering and story drafting. It is NOT directly invocable by users —
instead, it is used as a base by other skills:

- **ticket write layer** — drafts and applies the story to a target (PR,
  Linear ticket, JIRA ticket)
- **PR creation skill** — sources or generates a Job Story for the PR
  description
- **ticket work-on skill** — drafts a story early when starting work on a
  ticket
- **ticket scoping skill** — drafts a story during the architecture phase
- **release-notes skill** — generates missing stories in unattended mode
- **commit skill** — derives outcome-focused titles from the "so X can" clause

## Guiding Principle: Business ROI First

Every Job Story must answer **"where does the money come from, or
where does the money go?"** before "what does the code do?".
Engineering value — cleaner APIs, sortable identifiers, fewer
round-trips, less duplication — is never the lead. It is at best
the *mechanism* that delivers a business outcome.

If a draft cannot point at one of these ROI buckets, the story is
still a description of the diff, not a Job Story:

- **Revenue captured** — sales the business could not make before
- **Cost saved** — fewer support hours, lower infra spend, less rework
- **Retention / churn** — keeps customers from leaving the platform
- **Time-to-value** — customer reaches their first valuable use faster
- **Risk avoided** — compliance, security, data loss, payment failures

Engineering value is always secondary. A refactor or dependency
bump that ships no business outcome should be either (a) the
*first step* in a sequence that does — and named after that
downstream outcome — or (b) not done at all.

### Trace upward for plumbing PRs

Dependency bumps, refactors, and infrastructure changes feel
"actor-less" — there is no user clicking a button. The fix is
**not** to invent "the developer wants to…" as the actor. The fix
is to **trace upward** to the user-facing feature the plumbing
unblocks and frame the story from *that* feature's beneficiary.

Generic worked trace (a library bump that enables client-assigned
record ids in a self-service configurator):

```
ULID library dependency bump          ← the diff
  └─ enables client-assigned record ids
       └─ collapses N row-level CRUD mutations into one atomic save
            └─ makes the self-service configurator UI usable
                 └─ end customers manage their own settings
                      └─ vendor saves support hours + customers
                        ship configuration changes same-day
```

The actor is the **end customer**; the beneficiary is the
**vendor** (support cost saved) and the **end customer** (revenue
/ time saved from same-day configuration). The library is the
mechanism, never the actor.

## Interface Contract

```
INPUTS:
  ticket_id: str | None      — e.g. FEAT-519, BUG-234, ENG-300
  pr_number: int | None      — GitHub PR number
  context: dict | None       — Pre-gathered context (avoids redundant API calls)
  mode: attended | unattended — attended = user approval; unattended = return draft

OUTPUT:
  story: str — "**When** ... **[actor] wants to** ... **so [beneficiary] can** ..."
               Empty string if user rejects (attended mode)

SIDE EFFECTS: None.
```

Callers pass whatever context they already have via `context` to skip
redundant API calls. If `context` is None, the skill gathers it fresh.

## Workflow

### Step 1: Gather Context

Collect information from available sources in parallel. Skip sources
the caller already provided via the `context` parameter.

**A. PR details (if `pr_number` provided):**
- Call `mcp__plugin_Dev10x_cli__pr_get(number=PR_NUMBER)` for the
  PR title, body, head branch, and metadata
- Call `mcp__plugin_Dev10x_cli__pr_detect(arg=str(PR_NUMBER))` if
  the PR number was supplied without repo context
- Fetch the diff via `Skill(Dev10x:gh-context)` (or the project's
  PR-diff helper) — raw `gh pr diff` is hook-blocked in skill docs

**B. Issue ticket (if `ticket_id` provided):**
Use the available issue tracker tool (Linear MCP, JIRA REST API, etc.)
to get:
- Title and description
- Parent ticket ID (if any)

**C. Parent ticket (if exists):**
Use the issue tracker tool with the parent ID to get:
- The business context and original request
- Who requested it and why
- Linked Slack threads or comments (often contain the real user voice)

The parent ticket is critical — it usually contains the *why* behind
the technical sub-task. The sub-task (linked to the PR) contains the
*how*.

### Step 2: Identify the Situation

From the gathered context, extract:

1. **Who experiences the situation?** (not a persona — a role in context)
   - Look at: parent ticket description, user quotes, who filed it
   - Example: "a merchant", "a billing admin", "the ops team"

2. **Who benefits from the outcome?** (may differ from the actor above)
   - Sometimes the actor who triggers the action and the beneficiary are
     different roles — e.g., the billing admin sends the invoice SMS, but
     the customer is the one who benefits from paying via phone
   - Look at: what changes for whom, who is the downstream beneficiary

3. **What triggers the need?** (the real-world moment)
   - Look at: parent ticket description, user quotes
   - Example: "processes a bank transfer", "runs end-of-month payroll"
   - **Use the mundane situation the sources actually name — never
     invent a more dramatic one.** A vivid crisis ("mid-shift outage")
     reads better than "routine onboarding", but if the ticket doesn't
     describe it, it misstates the job. Check: can you point at the
     sentence in the ticket/parent/PR that names this trigger?

4. **What's wrong today?** (the current pain)
   - Look at: why was the ticket created, what workaround exists
   - Example: "forced to select 'Other'", "calculation times out"

### Step 3: Draft the Job Story

**Format:**
```
**When** [situation], **[actor] wants to** [motivation], **so [beneficiary] can** [expected outcome].
```

**Rules:**
- Use **business language**, not technical language
- The "When" describes a real-world moment, not a UI interaction
- Always name the actor explicitly — never use "I", "we", or "they"
- The actor ("wants to") and beneficiary ("so X can") may be **different
  roles** — name both explicitly when they differ (e.g., "the billing admin
  wants to send the customer an SMS, so the customer can pay immediately")
- The "so [beneficiary] can" should contrast with the current broken state
- One sentence. No bullet points. No implementation details.
- The motivation names an **outcome with less effort**, not a UI action —
  actors don't want to "see / view / manage" anything; ideally they want
  to do nothing. "wants the setup to be obvious at a glance", not
  "wants to see every device's status in the new view"
- **One clause each** for situation, desire, and outcome. If you cannot
  read the draft aloud in one breath to a non-technical stakeholder,
  it is leaking implementation — length correlates with leakage
- See `references/job-story-format.md` for detailed guidance

### Subject Selection by PR Type

The actor in "wants to" varies depending on the type of change:

| PR Type | Actor | Notes |
|---------|-------|-------|
| User-facing feature | End user role: merchant, customer, admin | "the cashier wants to select 'ACH' as the payment method..." |
| Refactoring / preparatory | Downstream feature's actor | Trace upward to the user-facing feature this unblocks — never name the developer as actor |
| Bug fix | Role whose business activity is broken | Not "developer fixing the bug" — name the role whose work failed |
| Internal tooling | Ops/engineering team member | Reserve for changes that ship *operator* value (dashboards, alerting, runbooks) |
| Infrastructure | Downstream feature's actor (or ops team for true ops tooling) | If the change ships no operator value, trace upward to the user-facing feature it unblocks |

**Actor ≠ Beneficiary:** When the person taking the action differs from the
person who gains the benefit, name both explicitly:
> "the billing admin wants to send the customer an SMS with the payment link,
> so the customer can pay immediately from their phone"

**Anti-pattern for plumbing PRs:** Do not name "the developer" as
actor for refactoring, dependency bumps, or infrastructure
changes. These PRs are not actor-less — they have a real actor
one or two levels up the dependency chain. Trace upward (see
*Trace upward for plumbing PRs* above) and frame the story from
the user-facing feature's actor and beneficiary, even when the
feature ships in a later PR.

**Bug fix stories**: Focus on the specific broken entity (e.g., "stale
background job"), not the monitoring symptom that surfaced it (e.g.,
"error alerts in Sentry"). The "When" should describe the real-world
situation where the bug manifests, not the developer's experience of
discovering it.

### Anti-pattern: Pseudo-Business Value

The biggest risk with JTBD stories is writing something that *sounds*
business-y but is really technical dress-up. If the story doesn't
answer "why is this worth spending money on?", it's friction — not
value.

**Red flags in a draft:**

| Red flag | Why it's wrong | Fix |
|----------|---------------|-----|
| Technical scheduling as "When" | "When upgrading EKS" — business doesn't care about infrastructure timelines | Use the recurring business activity: "When releasing new features" |
| Technical mechanism as motivation | "configure probes with the right semantics" | Name what actually changes: "detect failed deployments" |
| Over-specific role when a generic term works | "merchants" when the check protects all users equally | Use "user experience" — don't narrow without reason |
| Implementation detail as benefit | "avoid misrouted traffic during restarts" | State the real outcome: "prevent broken releases from degrading UX" |
| `I want to` when the actor is ambiguous | "I" doesn't identify the stakeholder | Prefer a named role ("the merchant", "the DevOps team"); `I want to` is fine as a fallback when the actor is clear from context |
| "the developer wants to…" for refactoring / infra / dep bumps | Substitutes the engineer for the real beneficiary; the developer's convenience is not a business outcome | Trace upward to the user-facing feature this plumbing unblocks; use that feature's actor and beneficiary |
| "wants to **see / view / check / manage** X" as the desire | UI verbs describe operating the feature, not the job. Seeing is usually effort spent reaching the real outcome — actors want less work, ideally none. (Exception: analytics/reporting, where insight *is* the deliverable — then pair the verb with the decision it enables) | Name the end state: "wants X to be obvious at a glance", "wants to be told when…", "wants the system to handle it" |
| Naming the **replaced artifact** as the contrast ("instead of the old/redundant list/panel/dialog") | What-we-replaced is diff-framing — it describes the previous implementation, not the user's pain. (Naming the prior broken *behavior* is fine; naming the prior *component* is not) | Contrast with the pain itself: time lost, confusion, escalations. An outcome like "keep support calls short" carries the contrast implicitly |
| **Enumerating capabilities** the feature surfaces (fields, statuses, IDs) | A capability list is the UI spec wearing a story costume. If a reader could reconstruct the screen from the story, it is too concrete | Collapse the list into the single outcome it buys |
| **Invented dramatic situation** ("won't take payments mid-shift" when the ticket says "during onboarding") | A vivid failure the sources never describe misstates the job and erodes stakeholder trust | Anchor "When" on the mundane trigger the ticket actually names (see Step 2) |

**The "why spend money" test:** Read the draft aloud. If a non-technical
stakeholder would respond "so what?" or "why do I care?", the story
is still too technical. Keep peeling layers until you hit something
that connects to user impact, revenue risk, or operational cost.

**Example — infrastructure PR (before and after):**

Before (technical dress-up):
> **When** deploying the app to Kubernetes, **I want to** have dedicated
> liveness, readiness, and startup endpoints, **so I can** configure
> probes with the right semantics and avoid misrouted traffic.

After (real business value):
> **When** releasing new features, **the DevOps team wants to**
> detect failed deployments through substantive health checks rather
> than superficial ones, **so they can** prevent broken releases from
> degrading the user experience.

The first version describes *what* the code does. The second explains
*why anyone should care*. The difference: substantive vs superficial
checks (the real improvement), and preventing UX degradation (the
real cost of not doing it).

**Example — UI-consolidation PR (before and after):**

Before (three red flags at once — UI verb, capability list,
replaced-artifact contrast):
> **When** setting up a store's payment devices, **staff want to** see
> and manage every paired device — status, pairing code, location —
> in the new summary view, **instead of** a second, redundant inline
> list.

After (mundane trigger, effort-free desire, ROI outcome):
> **When** onboarding a store's payment devices — or fielding a
> customer's call about them — **staff want** the setup to be obvious
> at a glance, **so the vendor can** get the store live sooner and
> keep support calls short.

Note what the fix did: dropped every mechanism noun, dropped the
what-we-replaced contrast, and shortened to one clause per slot. See
`references/examples.md` Example 7 for the full draft-by-draft
correction spiral behind this case.

### Step 4: Present or Return

**Attended mode** — present the draft and ask for approval.

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text)
with the draft and these options:
- **Accept** — use this story
- **Edit** — describe what to change
- **Reject** — discard and return empty

If **Edit**: ask what to change and iterate.
If **Reject**: return empty string.
If **Accept**: return the story string.

**Unattended mode** — return the draft directly without user
interaction. The caller decides what to do with it.

## Context Gathering Strategy

The quality of a Job Story depends on finding the **business voice** —
the original request that motivated the technical work. Follow this
hierarchy:

```
Best context sources (in priority order):
1. User quotes in parent ticket ("@sarah said: enterprise clients all pay via ACH")
2. Parent ticket description (business request)
3. Sub-task ticket description (technical scope)
4. PR diff (what actually changed)
5. PR title (last resort)
```

**If no parent ticket exists**, the ticket description itself is the
source. Look for user quotes, Slack links, or "requested by" mentions.

**If no ticket exists** (branch without ticket ID), use the PR diff
and title to infer the situation. Ask the user for business context
if unclear (attended mode) or make best effort (unattended mode).

## Integration Points

This skill is designed to be composed by other skills:

### Ticket write layer
The write layer. Invokes `Dev10x:jtbd` in attended mode, then writes the
approved story to a target (PR description, issue tracker ticket).

### PR creation skill
Sources an existing story or invokes `Dev10x:jtbd` to generate one. The
story becomes the first paragraph of the PR body.

### Ticket work-on skill
Invokes `Dev10x:jtbd` in attended mode using ticket context already
gathered. If approved, prepends the story to the ticket description.

### Ticket scoping skill
Invokes `Dev10x:jtbd` in attended mode. The approved story is included
in the scoping document under a `## Job Story` section.

### Release-notes skill
Invokes `Dev10x:jtbd` in **unattended** mode for PRs missing a story.
The caller batches multiple drafts and presents them all for approval.

### Commit skill
Invokes `Dev10x:jtbd` in **unattended** mode to derive an outcome-focused
commit title from the "so X can" clause. Only for first commits on
feature/bug branches.

### PR monitor skill
Delegates to the ticket write layer when a PR is missing its Job Story.

## Examples

See [`references/examples.md`](references/examples.md) for worked
walkthroughs covering: feature with parent ticket context (Ex 1),
feature with different actor and beneficiary (Ex 2), bug fix
(Ex 3), internal tooling (Ex 4), refactor with trace-upward (Ex 5),
a pure dependency-bump PR with trace-upward (Ex 6), and a
UI-consolidation PR's four-draft correction spiral (Ex 7).
