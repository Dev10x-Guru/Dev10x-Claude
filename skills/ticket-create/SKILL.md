---
name: dev10x:ticket-create
description: >
  Create an issue tracker ticket (GitHub issue, Linear, or JIRA) with
  proper formatting, description structure, and labels. Accepts title,
  description content, and optional labels. Automatically formats the
  description with Root Cause, Solution, and Files Changed sections.
  Returns the created ticket ID.
  TRIGGER when: a new ticket needs to be created for tracking work.
  DO NOT TRIGGER when: ticket already exists (use dev10x:ticket-scope
  to enrich it), or user wants to update an existing ticket.
user-invocable: true
invocation-name: dev10x:ticket-create
allowed-tools:
  - AskUserQuestion
  - Read(${CLAUDE_PLUGIN_ROOT}/skills/ticket-create/references/*)
  - Bash(${CLAUDE_PLUGIN_ROOT}/skills/gh-context/scripts/:*)
  - Bash(${CLAUDE_PLUGIN_ROOT}/skills/ticket-create/scripts/:*)
  - Bash(gh issue create:*)
  - Bash(/tmp/Dev10x/bin/mktmp.sh:*)
  - mcp__claude_ai_Linear__save_issue
  - mcp__claude_ai_Linear__get_issue
  - mcp__claude_ai_Linear__list_projects
  - Bash(secret-tool lookup:*)
  - Bash(curl:*atlassian.net*)
  - mcp__plugin_dev10x_cli__detect_tracker
  - mcp__plugin_dev10x_cli__triage_roster
---

# Create Issue Tracker Ticket

## Overview

This skill creates a well-structured ticket in GitHub Issues, Linear, or JIRA with proper formatting, comprehensive description, and appropriate labels. It ensures consistent ticket quality across all creation contexts.

> **[OVERRIDE DETECTED]** — over the 200-line SKILL.md budget
> (GH-1705). Title patterns, label signals and per-tracker creation
> recipes live in `references/tracker-creation.md`. What remains gates
> execution: mode detection, the Step 4 never-file-bare triage, the
> Step 4e confirmation gate, and the Step 5 dispatch contract with its
> inline-creation exceptions. **Split plan:** if it passes ~380 lines,
> move the GH-156 anti-pattern history and the Step 5 exceptions to
> `references/`.

## Orchestration

This skill follows `references/task-orchestration.md` patterns.
Create a task at invocation, mark completed when done:

**REQUIRED: Create a task at invocation.** Execute at startup:

1. `TaskCreate(subject="Create issue tracker ticket", activeForm="Creating ticket")`

Mark completed when done: `TaskUpdate(taskId, status="completed")`

## Execution Mode (GH-1704)

Detected the same way `dev10x:git-commit` detects it. **Unattended**
mode applies only when **both** hold:

1. The skill was invoked via `Skill(dev10x:ticket-create)` by another
   skill or agent, not typed by the user as `/dev10x:ticket-create`.
2. The caller is executing a plan step with an active task list
   (an orchestrator such as `dev10x:work-on`, `dev10x:audit-file`,
   or a `dev10x:foreman` crew).

When either is absent — including any direct `/dev10x:ticket-create`
— run **attended**. When in doubt, run attended. Only the Step 4e
gate differs between the two modes.

## Prerequisites Check

Determine which tracker to use. Priority:

1. **Explicit argument** — user specifies `--github`, `--linear`, or `--jira`
2. **detect_tracker MCP tool** — if a ticket prefix is available (from branch
   name), call `mcp__plugin_dev10x_cli__detect_tracker` to match the project's
   tracker
3. **Repo default** — if no prefix, check autolinks to determine project's
   primary tracker. GitHub Issues if no autolinks exist.

**Fast-fail rule:** Make ONE attempt at the `detect_tracker` MCP call.
If the tool is unavailable, returns an error, or `ToolSearch` does not
surface it on the first lookup, fall through to step 3 (repo default)
immediately. Do NOT retry `ToolSearch` for Linear, JIRA, or
`detect_tracker` MCP names. Repeated retries block the skill for
many minutes and produce no new information — the absence of a tool
on the first lookup means it is not registered in this session.

| Tracker | Required | Creation method |
|---------|----------|----------------|
| GitHub | `gh` CLI | `gh issue create` |
| Linear | Linear MCP | `mcp__claude_ai_Linear__save_issue` |
| JIRA | Atlassian MCP | `mcp__claude_ai_Atlassian__createJiraIssue` |

## When to Use This Skill

Use this skill when:
- Creating a ticket for tech debt that needs tracking
- Converting an untracked change into a formal ticket
- Creating a bug report ticket
- Documenting an improvement or enhancement
- Need a properly structured ticket with consistent formatting

### Anti-pattern: Bypassing the wrapper (GH-156)

**Do NOT call `mcp__plugin_dev10x_cli__issue_create` (or any
tracker MCP `save_issue` / `gh issue create`) directly when
creating a new ticket.** Audit GH-156 caught 5 follow-up tickets
created via raw `issue_create` calls; the resulting tickets
lacked the Root Cause / Solution / Files Changed scaffolding
that this skill enforces.

The raw MCP tool is a low-level primitive — this skill is the
project wrapper that adds structured description formatting,
milestone/label triage, and tracker-detection. Always reach for
`Skill(dev10x:ticket-create)` first; the skill's Step 5 will
dispatch the appropriate MCP tool internally.

**This binds every filing path (GH-1102).** `dev10x:audit-file`,
`dev10x:work-on` follow-up filing, `dev10x:diag-friction` upstream
filing, and `dev10x:foreman` crew filing all route here rather than
calling `issue_create` bare — otherwise each one re-invents (or
skips) Step 4 and the backlog goes back to needing sweeps. A caller
that already knows the milestone and labels still routes through
this skill and passes them; it does not become its own filing path.

## Input Requirements

This skill requires:
1. **Context** - Information about the problem/improvement (can be from a commit, code analysis, or user description)
2. **Optional: Title** - If not provided, generate from context.
   When `--body-file` is used without `--title`, the first line
   of the file is used as the title (separated from the body by
   a blank line). This avoids permission friction from special
   characters in args strings.
3. **Optional: Labels** - If not provided, infer from context

## Workflow

### Step 1: Analyze Context

Understand what the ticket is about from the provided context:

**Context can come from:**
- Git commit diff and message (`git show <commit-hash>`)
- Code files that need improvement
- User description of the problem
- Bug report or issue description

**Extract:**
- What problem is being solved?
- Why did the issue exist?
- What changes were/will be made?
- What files are affected?

### Step 2: Generate Ticket Title

Create a descriptive, concise title. Per-context patterns are in
[`references/tracker-creation.md`](references/tracker-creation.md)
§ Title Format Patterns.

**Title Rules:**
- Keep concise but descriptive (aim for < 80 characters)
- Start with action verb (Fix, Improve, Add, Refactor, etc.)
- Be specific about the component/area affected
- Avoid vague terms like "issue" or "problem" without context
- **Describe the user-facing outcome, not the implementation detail.** E.g., `Enable automatic terminal discovery` not `Add DEVICES_READ to Square OAuth scopes`

### Step 3: Generate Description

Create a comprehensive description using this structure:

**Structure:**
```markdown
<Brief 1-2 sentence summary of the problem/improvement>

## Root Cause
- <Primary reason the issue existed>
- <Contributing factors>
- <Technical details about why this happened>

## Solution
- <First key change or improvement>
- <Second key change or improvement>
- <Third key change or improvement>
- <Additional changes as needed>

## Files Changed
- <file path 1> - <what changed>
- <file path 2> - <what changed>
- <file path 3> - <what changed>
```

### Step 4: Triage Milestone and Labels (GH-1102)

**REQUIRED — never file bare.** The filing tools accept `milestone`
and `labels`, but until GH-1102 no filing flow populated them: a
2026-08-30 sweep found 11 of 16 open issues unmilestoned and 10 of 13
unlabeled, every one filed through these wrappers. The taxonomy and
the milestone convention both exist; filing simply ignored them, and
the cost landed on periodic manual restructure sweeps.

**Step 4a — read the live roster.** Call
`mcp__plugin_dev10x_cli__triage_roster(repo="$REPO")`. It returns
`milestones` (open only, with descriptions) and `labels` (name +
description). Do NOT work from a hardcoded list — a stale table is
how the taxonomy drifted out of use in the first place.

**Step 4b — propose labels.** Match the ticket's title and body
against the returned roster using the signal table in
[`references/tracker-creation.md`](references/tracker-creation.md)
§ Label Signals. Propose every label whose signal is present; when
the roster holds a label the table does not mention, prefer the
roster's own description.

**Step 4c — propose a milestone.** Match the ticket's theme against
the open milestones' titles and descriptions, respecting the
initiative prefixes (no sequence numbers — older `<INIT>-M<n>` titles
are legacy, not a pattern to copy) and close-at-zero lifecycle in
[`references/milestone-naming.md`](../../references/milestone-naming.md).
A milestone whose description already names this ticket's theme is a
direct hit.

**Step 4d — when nothing fits, say so explicitly.** If no open
milestone is a confident match, file with the `needs-triage` label
rather than silently unmilestoned, so a later sweep can find strays
with one query instead of reading every bare issue. Never leave BOTH
milestone and labels empty — that is the state this step exists to
prevent.

**Step 4e — confirm the proposal (attended mode only).** Before
dispatching Step 5, show the proposed title, milestone and labels.

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text). This
blocks until the user responds. Options:

- **Create as proposed (Recommended)** — file with this title,
  milestone and labels
- **Edit title, milestone or labels** — the user states the change;
  apply it and show the gate again
- **Abort** — file nothing

**Unattended mode** (see § Execution Mode): skip the gate, apply the
best match and proceed — filing bare is not the safe default here,
it is the defect.

### Step 5: Create the Ticket

**REQUIRED: Dispatch a background haiku agent to create the ticket.**
Execute this `Agent` call (do NOT inline ticket creation in the main
session). This prevents raw API responses (full issue JSON, project
lookups) from consuming main session context — the agent returns only
the ticket ID and URL.

1. `Agent(subagent_type="general-purpose", model="haiku", description="Create {tracker} ticket: {short_title}", prompt="<see template below>", run_in_background=true)`

The agent prompt template (substitute placeholders before dispatching):

```
Create a ticket with the following details:

Tracker: {tracker_type}
Title: {title}
Description: {description}
Labels: {labels}
Milestone: {milestone}
{tracker-specific config: team UUID, project UUID, repo}

The Labels and Milestone above come from the Step 4 triage and are
part of the creation call — do NOT file without them and leave
triage to a later sweep (GH-1102).

{include the tracker-specific instructions below}

Return ONLY:
- Tracker: {GitHub Issues | Linear | JIRA}
- ID: {ticket ID}
- URL: {ticket URL}
Do NOT return full API response bodies.
```

The main session waits for the agent result and passes it to
Step 6. The tracker-specific instructions below describe what
the agent executes — include the relevant section in the agent's
prompt (the fenced blocks under each tracker are reference material
for the dispatched agent, not instructions for the main session).

**Exception — inline creation is acceptable** when follow-on calls
need the returned ticket key immediately (e.g. a small batch where
`createIssueLink` needs the just-created issues' keys). Create the
ticket directly in the main session instead of dispatching the
background agent, so the key is available for the next call without
a round trip.

**Secondary fallback:** if JIRA writes are prompting for approval
because the `mcp-atlassian-write` baseline group has not synced to
your `settings.json` (see the troubleshooting note under the JIRA
section below), create inline too — a background agent cannot
answer that prompt. Prefer fixing the sync gap via
`dev10x:plugin-maintenance` over leaning on this fallback long-term.

**Nested invocation:** When invoked from a background agent
(e.g., from `project-scope`'s Phase 3 agent), skip the
delegation wrapper and execute creation directly. Detection:
if the skill is running as a Skill() call within an Agent()
prompt (vs. in main session), this SKILL.md is your read
context — your caller (the agent prompt) already optimizes
the session context, so you execute creation directly per
tracker-specific instructions below without wrapping in
Agent().

**Tracker-specific creation instructions:** read
[`references/tracker-creation.md`](references/tracker-creation.md)
§ Tracker-Specific Creation and include the detected tracker's
section in the agent prompt. GitHub Issues writes the body to a
mktmp file and passes `--milestone` unless Step 4d found no match;
Linear resolves a project UUID before `save_issue`; JIRA creates via
the Atlassian MCP `createJiraIssue` (the `dev10x:jira` skill has no
create path, GH-631).

### Step 6: Return Ticket Information

Extract and return the ticket details:

```
Ticket Created

Tracker: {GitHub Issues | Linear | JIRA}
ID: {GH-42 | PAY-519 | JIRA-1234}
Title: {title}
URL: {tracker-specific URL}
```

## Important Notes

- Keep titles concise but descriptive
- Always include Root Cause, Solution, and Files Changed sections
- Apply relevant labels to improve discoverability
- Return the ticket ID for use in subsequent workflows
- Don't modify ticket after creation unless explicitly asked

## Integration with Other Skills

This skill is designed to be used by other skills:

- **commit:to-new-ticket**: Uses this skill in Step 3 to create ticket from commit
- **test:fix-flaky**: Uses this skill in Step 3 to create tech debt ticket
- **Standalone usage**: User manually creates ticket with provided context
