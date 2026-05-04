# Ticket Scope — Linear Ticket Scoping Skill (Instructions)

## Overview

This skill creates comprehensive technical scoping documents for Linear tickets. It extends the base `scope` skill with Linear-specific workflows.

**Use when:**
- Preparing to implement a Linear ticket
- Need technical design before coding
- Want to document approach for a ticket
- Creating detailed implementation plan

**Do NOT use for:**
- Architectural decisions (use `Dev10x:adr` instead)
- Simple bug fixes with obvious solutions
- Quick tasks under 1 story point

## Orchestration

This skill follows `references/task-orchestration.md` patterns
(Tier: Standard). It extends the base `scope` skill's orchestration
with Linear-specific tasks.

**Auto-advance:** Complete each phase and immediately start the next.
Never pause between phases to ask "should I continue?".

**REQUIRED: Create tasks before ANY work.** Execute these
`TaskCreate` calls at startup:

1. `TaskCreate(subject="Fetch Linear ticket context", activeForm="Fetching ticket")`
2. `TaskCreate(subject="Research technical context", activeForm="Researching codebase")`
3. `TaskCreate(subject="Design solution architecture", activeForm="Designing solution")`
4. `TaskCreate(subject="Estimate complexity and draft Job Story", activeForm="Estimating complexity")`
5. `TaskCreate(subject="Format and present scoping document", activeForm="Formatting scope")`
6. `TaskCreate(subject="Save and update Linear", activeForm="Saving scope")`

Set sequential dependencies: research blocked by fetch, design
blocked by research, estimate blocked by design, format blocked by
estimate, save blocked by format.

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text, call spec: [ask-scope-approval.md](./tool-calls/ask-scope-approval.md)) after
presenting the scope. This blocks execution until the user responds.
Options:
- Approve (Recommended) — Save document and optionally update Linear
- Revise — I have corrections to the scope
- More research needed — Need to explore additional areas
- Run PoC — Validate unverified architectural claims via a live
  proof-of-concept before approving (e.g., `claude -p` subprocesses,
  small scripts, or codebase probes that confirm a claim the scope
  depends on)

**When to surface "Run PoC":** Whenever the scope contains claims
the agent could not verify by reading the codebase alone (e.g.,
"approach X loads the plugin in a child session", "tool Y
propagates env vars to subprocesses"). Listing the option
short-circuits the manual escalation pattern observed in audit
session 1d53f6ec — the user otherwise has to invent the PoC step
themselves under "More research needed" (GH-33).

## Prerequisites

**Required:**
- Linear ticket ID (e.g., PAY-329)

**Optional:**
- External documentation URLs to research
- Specific areas of codebase to explore

## Workflow

### Phase 1: Gather Ticket Context

#### 1.1 Fetch Ticket Details

```
Use Linear MCP to get ticket:
- Title
- Description
- Labels
- Assignee
- Related tickets
- Comments
```

#### 1.2 Check for Existing Context

Look for:
- Related tickets (blocks, blocked by, related to)
- Existing scoping documents
- Previous comments with context
- Attachments or links

### Phase 2: Technical Research (Uses base scope skill)

Follow the base `scope` skill for:

1. **Research external resources** (if provided)
2. **Explore existing codebase**
   - Find related patterns
   - Identify reusable components
3. **Identify components** (existing vs. new)

**Tool routing rules during research (GH-55 F6, F7, F8):**

| Goal | Use | Do NOT use |
|------|-----|-----------|
| Search code by pattern/keyword | `Grep` tool with `output_mode: count` or `head_limit` | Bash `grep -rn ... \| head` or `grep \| wc -l` |
| Read a file or excerpt | `Read` tool (with `offset`/`limit` for excerpts) | Bash `cat`, `head`, `tail` |
| Combine setup + search | Two separate Bash calls | `cat ... && grep ...` or `;`-chained shells |
| Create a temp file path | `mcp__plugin_Dev10x_cli__mktmp` | `/tmp/Dev10x/bin/mktmp.sh` (bash fallback) |

The bash forms are blocked by security hooks (heredoc/redirect
checks, chained commands) or trip Claude's prefix-matching allow
rules. The Grep/Read tools are also faster — they stream results
without spawning a shell. The audit caught six bash `grep`
invocations and three `cat`-based commands hitting the hook
across one ticket-scope research phase; CLAUDE.md §2 already
prohibits these but the rule needs to live next to the work,
not only at the global level.

### Phase 3: Design Solution

#### 3.1 Determine Task Type

**Business Feature** - User-facing functionality
- Requires acceptance criteria
- May need release notes

**Technical Task** - Infrastructure/refactoring
- Technical depth only
- No user-facing changes

**Bug Fix** - Fixing broken behavior
- Root cause analysis
- Resolution summary

#### 3.2 Apply Design Principles

From base `scope` skill:
- YAGNI
- Follow existing patterns
- Clean Architecture

#### 3.3 Create Implementation Plan

Order steps by dependencies:
1. Types/DTOs
2. Client/Repository layer
3. Service layer
4. API layer
5. Tests

### Phase 4: Estimate Complexity

#### Story Points (Fibonacci)

| Points | Complexity | Duration |
|--------|------------|----------|
| 1 | Trivial | Hours |
| 2 | Small | < 1 day |
| 3 | Medium | 1-2 days |
| 5 | Large | 2-3 days |
| 8 | Complex | 3-5 days |
| 13 | Epic-sized | Should be split |

#### Estimation Factors

- New patterns vs. following existing
- Database migrations
- External dependencies
- Test complexity
- Review/iteration cycles

### Phase 4b: Draft Job Story

After estimating complexity, draft a Job Story for the ticket using the JTBD framework. This captures the business "why" early — before implementation begins — and will later be used in the PR description and release notes.

**REQUIRED: Call `Skill(Dev10x:jtbd)` in attended mode** (do NOT
draft the Job Story inline as prose inside the scope document).
Inline drafting bypasses jtbd's own context-gathering and
approval gate and breaks reusable orchestration (GH-27).

1. Pass the ticket context already gathered in Phase 1 (ticket
   details, parent ticket, related tickets) via the `context`
   parameter to avoid redundant API calls
2. The `Dev10x:jtbd` skill handles: situation identification,
   drafting, and user approval
3. Include the approved Job Story (the string returned by the
   skill) in the scoping document under a `## Job Story` section
   right after the title

**Anti-pattern (GH-27):** Writing a Job Story sentence directly
into the scope document Write call without a preceding
`Skill(Dev10x:jtbd)` invocation. Even when the resulting story
reads correctly, the skipped delegation is a compliance
violation — the jtbd skill's own attended-mode approval gate
must fire.

**Do NOT update the Linear ticket description at this point** — the story is saved in the scoping document and will be applied to the PR later via `Dev10x:ticket-jtbd` or `Dev10x:gh-pr-create`.

### Phase 5: Format Scoping Document

#### 5.1 Select Template

**REQUIRED: Read one of the three templates and use its
section structure.** Do NOT hand-craft the scope document
without consulting a template — different sessions produce
different shapes, breaking downstream consumers (PR creation,
project audit) that expect template-stable section names
(GH-28).

Pick by task type and `Read` the corresponding file before
writing the scope document:

- Business Feature → `references/business-feature-template.md`
- Technical Task → `references/technical-task-template.md`
- Bug Fix → `references/bug-fix-template.md`

**Verification:** Before the Phase 5.2 Write call that creates
the scope document, confirm the section headings match the
template's headings exactly (Job Story, Objective, Technical
Approach, Architecture, …). If a heading is missing or
renamed, you skipped the template — go back and read it.

**Anti-pattern (GH-28):** Writing
`/tmp/Dev10x/ticket-scope/<ID>-scope.md` with custom section
names ("Findings", "Approach Notes", etc.) instead of the
template's section names. Even when the content is correct,
the diverged structure breaks audits and PR generation.

#### 5.2 Complete All Sections

**Required sections:**
- Objective/Problem Statement
- Technical Approach
- Architecture (components, dependencies)
- Implementation Steps (with file paths)
- Code References
- Dependencies (tickets)
- Risks and Mitigations
- Acceptance Criteria
- Story Points

### Phase 6: User Review

**Critical:** Present scoping to user before saving.

Ask for feedback on:
- Architecture decisions
- Missing considerations
- Complexity estimate
- Implementation order

### Phase 7: Save and Update

#### 7.1 Save Scoping Document

Generate the scope-document path via the mktmp MCP tool, then
write the rendered template to it:

```
mcp__plugin_Dev10x_cli__mktmp(namespace="ticket-scope",
    prefix="<TICKET-ID>-scope", ext=".md")
```

Take the returned `path` and `Write` the document there. Do NOT
hardcode `/tmp/Dev10x/ticket-scope/<TICKET-ID>-scope.md` and do
NOT shell out to `/tmp/Dev10x/bin/mktmp.sh` — the MCP tool is the
preferred path (GH-55 F8).

#### 7.2 Update Linear Ticket (Optional)

If user approves, update ticket with:
- Story point estimate
- Comment with architecture summary
- Links to related resources

**IMPORTANT:** Never modify ticket description without explicit user approval.

## Scoping Document Format

### Business Feature

```markdown
# [TICKET-ID]: [Title]

## Job Story
**When** [situation], **I want to** [motivation], **so I can** [expected outcome].

## Objective
[Business value and user impact]

## Technical Approach
[High-level solution]

## Architecture

### Components
**Repositories:** [list]
**Services:** [list]
**DTOs:** [list]
**Models:** [list]

### Database Changes
[Migrations, new tables, columns]

### GraphQL Changes
[New queries/mutations]

## Implementation Steps

1. **[Step name]**
   - File: `src/path/file.py`
   - Pattern: [reference to similar code]
   - Changes: [what to do]

## Code References
- `src/path/file.py` - [description]

## Dependencies
**Depends on:** [tickets]
**Related to:** [tickets]
**Blocks:** [tickets]

## Risks

**Risk: [Name]**
- Scenario: [what could go wrong]
- Mitigation: [how to prevent/handle]

## Acceptance Criteria
- [ ] Criterion 1
- [ ] Criterion 2

## Out of Scope
- [What we're NOT doing]

## Story Points
**[N] points**

Rationale:
- [Breakdown of estimate]
```

### Technical Task

```markdown
# [TICKET-ID]: [Title]

## Job Story
**When** [situation], **I want to** [motivation], **so I can** [expected outcome].

## Objective
[Technical goal]

## Technical Approach
[Solution design]

## Architecture
[Components affected]

## Implementation Steps
[Ordered steps with file paths]

## Code References
[Files to reference]

## Dependencies
[Related tickets]

## Risks
[Technical risks]

## Acceptance Criteria
- [ ] Technical criterion 1

## Story Points
**[N] points**
```

### Bug Fix

```markdown
# [TICKET-ID]: [Title]

## Job Story
**When** [situation], **I want to** [motivation], **so I can** [expected outcome].

## Problem Statement
[What's broken]

## Root Cause Analysis
[Why it's broken]

## Resolution
[How to fix]

## Implementation Steps
[Fix steps]

## Code References
[Affected files]

## Risks
[Regression risks]

## Acceptance Criteria
- [ ] Bug no longer occurs
- [ ] No regressions

## Story Points
**[N] points**
```

## Quality Checklist

Before finalizing, verify:

### Context
- [ ] Ticket details fetched
- [ ] Related tickets identified
- [ ] External resources reviewed

### Design
- [ ] Follows existing patterns
- [ ] YAGNI applied
- [ ] Dependencies clear

### Documentation
- [ ] All sections complete
- [ ] File paths specific
- [ ] Code references included
- [ ] Risks identified

### Estimation
- [ ] Story points justified
- [ ] Complexity factors considered

### Review
- [ ] User approved scoping
- [ ] Linear updated (if requested)

## Integration with Other Skills

```
Dev10x:ticket-scope
├── Extends: scope (base scoping workflow)
├── Uses: Linear MCP (ticket data)
├── Uses: Dev10x:jtbd (JTBD story drafting in Phase 4b)
├── May lead to: Dev10x:work-on (start implementation)
├── Alternative: Dev10x:adr (for architectural decisions)
└── Saves to: /tmp/Dev10x/ticket-scope/TICKET-ID-scope.md
```

## Example Usage

### User Request
```
/Dev10x:ticket-scope PAY-329
```

### Workflow
1. Fetch PAY-329 from Linear
2. Read ticket description and comments
3. Research external docs (if provided)
4. Explore codebase for patterns
5. Design solution following patterns
6. Apply YAGNI
7. Create implementation plan
8. Estimate story points
9. Draft Job Story (using Dev10x:jtbd base skill)
10. Present to user for review
11. Incorporate feedback
12. Save scoping document
13. Update Linear (if approved)

## References

### Templates
- `references/business-feature-template.md`
- `references/technical-task-template.md`
- `references/bug-fix-template.md`
- `references/scoping-checklist.md`

### Related Skills
- `scope` - Base scoping skill
- `Dev10x:adr` - For architectural decisions
- `Dev10x:work-on` - Start implementation
