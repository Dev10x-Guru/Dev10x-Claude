# Dev10x:work-on — Adaptive Work Orchestrator (Instructions)

## Overview

This skill turns any combination of inputs into a structured,
supervisor-approved work plan. It runs in four phases:

1. **Parse & Classify** — identify what each input is
2. **Gather** — fetch context from all sources in parallel
3. **Plan** — build a task list for supervisor approval
4. **Execute** — work through tasks, expanding epics on demand

The supervisor sees progress via `TaskList`, can approve/edit
the plan, and can pause at any point with `Dev10x:session-wrap-up`.

**Rule: ALWAYS use `TaskCreate`** — even for single-task work.
The visible task list is the supervisor's interface for adding
new tasks mid-session. Skipping it removes that capability.

**REQUIRED: Create phase tasks before ANY work.** At session
start, create exactly 4 top-level tasks — one per phase:

1. `TaskCreate(subject="Phase 1: Parse & Classify inputs", activeForm="Classifying inputs")`
2. `TaskCreate(subject="Phase 2: Gather context", activeForm="Gathering context")`
3. `TaskCreate(subject="Phase 3: Build work plan", activeForm="Building plan")`
4. `TaskCreate(subject="Phase 4: Execute plan", activeForm="Executing")`

Set sequential dependencies (each phase blocked by the previous).
During each phase, create subtasks for the concrete work items
discovered — e.g., Phase 2 creates one subtask per source being
fetched, Phase 4 creates subtasks per plan step.

## Phase 0: Session Friction Level (GH-689)

**At the very start** — before Phase 1 — prompt the user to set
the session friction level. This controls how aggressively the
skill auto-advances vs pauses for confirmation.

**Skip this prompt when:**
- Running as a nested invocation from `Dev10x:fanout` (fanout
  sets friction level once for the entire session)
- Session config already exists at `.claude/Dev10x/session.yaml`
  with a valid `friction_level` value (loaded after compaction
  or from a prior invocation). When skipping, also skip the
  write — the existing file is authoritative.

**REQUIRED: Call `AskUserQuestion`** (ALWAYS_ASK — fires at all
friction levels, including adaptive).

Options:
- Guided (Recommended) — Gates fire with recommendations,
  user can override. Default for attended sessions.
- Adaptive (AFK) — Auto-select recommended options at all
  gates. No `AskUserQuestion` interruptions except
  `ALWAYS_ASK` gates. Best for walk-away sessions.
- Strict — All gates fire, no auto-selection. Every
  decision requires explicit user input.

**Persist the choice** to `.claude/Dev10x/session.yaml`:

```yaml
friction_level: guided  # strict | guided | adaptive
active_modes: []        # e.g., [solo-maintainer]
```

Also persist `active_modes` from the project playbook file
(`memory/playbooks/work-on.yaml`) if present — copy them into
session.yaml so skills can read modes without loading the full
playbook. If the project file declares `active_modes`, merge
them into the session config.

**Read-before-write (GH-846):** Before writing `session.yaml`,
read the existing file (if present) and compare the desired
`friction_level` and `active_modes` with what is already on
disk. **Skip the write entirely** if both values already match.
This avoids unnecessary permission prompts and prevents
overwriting existing `active_modes` with empty defaults.

Resolution order for `active_modes`:
1. Existing `active_modes` in `session.yaml` (preserve)
2. `active_modes` from project playbook file (merge new entries)
3. Empty `[]` only if neither source provides modes

Never overwrite a non-empty `active_modes` list with `[]`.

Write this file using the Write tool only when the content
actually needs to change. The PreCompact hook reads it to
inject friction context into recovery summaries.

**How skills consume the level:**
- Gates marked `(Recommended)` auto-select at `adaptive`
- Gates marked `ALWAYS_ASK` always fire regardless of level
- The `references/friction-levels.md` document defines the
  full behavior matrix
- Playbook steps may override with `friction_level:` per step

## Prerequisites

| Capability | Required for | Tool |
|------------|-------------|------|
| GitHub CLI | GitHub issues, PRs | `gh` CLI |
| Linear MCP | Linear tickets | `mcp__claude_ai_Linear__*` |
| JIRA | JIRA tickets | `Dev10x:jira` plugin + `JIRA_TENANT` env var + keyring |
| Sentry MCP | Sentry issues | `mcp__sentry__*` |
| Slack MCP | Slack threads | `mcp__claude_ai_Slack__*` |

Not all are required — only those matching the input types.

## When to Use

- User provides any combination of: ticket URL/ID, PR link, Slack
  thread, Sentry link, or free text description
- User wants to start structured work with progress tracking
- User wants comprehensive context before starting

---

## Phase 1: Parse & Classify

Accept the user's arguments as a space-separated list. Each
argument is classified independently:

| Pattern | Type | Action |
|---------|------|--------|
| `https://github.com/.../issues/N` | `github-issue` | Extract repo + issue number |
| `https://github.com/.../pull/N` | `github-pr` | Extract repo + PR number |
| `https://linear.app/.../issue/XXX-N/...` | `linear-ticket` | Extract ticket ID (e.g., `TEAM-133`) |
| `https://.*slack.com/archives/C.../p...` | `slack-thread` | Store channel + timestamp |
| `https://sentry.io/.../issues/N` | `sentry-issue` | Extract issue ID |
| `https://*.sentry.io/issues/N` | `sentry-issue` | Extract issue ID |
| `https://...atlassian.net/browse/XX-N` | `jira-ticket` | Extract ticket ID |
| `GH-N` | `github-issue` | Route to `mcp__plugin_Dev10x_cli__detect_tracker` |
| `TEAM-N` (Linear prefix) | `linear-ticket` | Route to `mcp__plugin_Dev10x_cli__detect_tracker` |
| `JIRA-N` | `jira-ticket` | Route to `mcp__plugin_Dev10x_cli__detect_tracker` |
| `#N` (bare number) | `github-pr` | Resolve against current repo |
| Anything else | `note` | Store as free-text context |

For ticket IDs, call the tracker detector MCP tool:
`mcp__plugin_Dev10x_cli__detect_tracker(ticket_id="$TICKET_ID")`
Parse `tracker`, `ticket_number`, and `fixes_url` from the response.

Each classified input becomes a **source** entry with its type and
extracted identifiers. Collect all sources into a list for Phase 2.

### Ambiguous Input Fallback (GH-886)

When ALL inputs classify as `note` (no URLs, ticket IDs, or PR
numbers matched), the user likely provided natural language
(e.g., "fix the retry logic", "add dark mode support"). This
is a valid entry point — do not reject it.

**Fallback path:**

1. **Search for matching tickets** — use
   `mcp__plugin_Dev10x_cli__detect_tracker` with keywords
   extracted from the input. If a matching open ticket is found,
   reclassify the input as that ticket type.
2. **If no ticket found** — present options via
   `AskUserQuestion`:
   - **Work without a ticket (Recommended)** — proceed as
     `local-only` work type with the note as context
   - **Create a ticket first** — delegate to
     `Dev10x:ticket-create` and re-classify
   - **Search again with different terms** — user provides
     refined search terms

3. **If ticket found** — confirm with the user:
   "Found ticket [ID]: [title]. Use this?" and reclassify
   on confirmation.

**Skip this fallback** when at least one input classified as
a recognized type (URL, ticket ID, PR number). Mixed inputs
(ticket + notes) are handled normally — the notes provide
additional context.

### Early Workspace Decision

After classification, determine whether a branch is needed and
what workspace state we're in. This decision happens early because
it affects Phase 3 planning.

**Decision matrix:**

| Work type | Branch required? | Why |
|-----------|-----------------|-----|
| Ticket (feature/bugfix) | Yes | PR is the goal |
| PR continuation | No | Branch already exists |
| Local-only (free text) | Deferred | Decided in Phase 4 |
| Investigation only | No | No code changes expected |

**Detect current workspace state** using git directly:
- If `.git` is a **file** (not directory) → worktree
- If `.git` is a **directory** → main repo
- Current branch: `git symbolic-ref --short HEAD`

**Worktree branch check:** If the CWD is a worktree and the
current branch is a generic worktree branch (e.g., `wt/<name>`
or matches the worktree directory name but has no ticket ID),
flag it for replacement. A work-specific branch must be created
before any commits:

| Workspace state | Branch pattern | Action |
|----------------|---------------|--------|
| Main repo, on develop | Any ticket | Create branch (Phase 4.1) |
| Main repo, on feature branch | Matching ticket | Reuse branch |
| Worktree, generic WT branch | Any ticket | Create work-specific branch (Phase 4.1) |
| Worktree, matching feature branch | Same ticket | Reuse branch |

Store the workspace decision in the Phase 1 output so Phase 3
can include or skip the workspace setup subtask.

### Self-Check Before Phase 2

**REQUIRED:** Before proceeding to Phase 2, call `TaskList` and
verify that all 4 phase tasks exist. If they are missing, create
them NOW before proceeding. If `TaskCreate` is unavailable (e.g.,
`ToolSearch` returned it but calling fails), STOP and inform the
user — do NOT proceed without the task list.

---

## Phase 2: Gather (Quick & Parallel via Subagents)

**Same-session continuity:** If the user already provided rich
context in the current session (e.g., prior investigation, code
exploration, or a detailed description that covers the same
sources), skip redundant API fetches. Re-use context that is
already in the conversation window. Only fetch sources whose
data is not yet available in the session.

Fetch context from all sources in parallel using subagents.
Each subagent receives only its source identifiers and returns
a structured summary — keeping the main session lean.

See `references/task-orchestration.md` Pattern 4 (Subagent
Dispatch) for the full pattern.

### Subtask Creation

Before dispatching, create one subtask per source under the
Phase 2 parent task:

```
TaskCreate(subject="Fetch linear-ticket DEV-42",
    parentTaskId=phase2TaskId)
TaskCreate(subject="Fetch sentry-issue #5201839452",
    parentTaskId=phase2TaskId)
TaskCreate(subject="Fetch slack-thread #channel",
    parentTaskId=phase2TaskId)
```

Mark each subtask `completed` as its subagent returns.
After cross-reference expansion, create additional subtasks
for newly discovered sources.

### Subagent Dispatch

Dispatch one subagent per source in a single tool-call block.
Choose the agent type based on the source's tool requirements:

| Source type | Agent type | Why |
|-------------|-----------|-----|
| `github-issue` | `general-purpose` | Needs Bash for `gh` CLI |
| `github-pr` | `general-purpose` | Needs Bash for `gh` CLI |
| `linear-ticket` | `general-purpose` | Needs Linear MCP tools |
| `jira-ticket` | `general-purpose` | Needs Bash for `Dev10x:jira` skill |
| `slack-thread` | `general-purpose` | Needs Slack MCP tools |
| `sentry-issue` | `general-purpose` | Needs Sentry MCP tools |
| `note` | (none) | Pass through as-is |

**Do NOT use Explore agents for source fetches.** Explore agents
lack access to Bash, MCP tools, and `WebFetch`. Since `gh` CLI
requires Bash and Linear/Slack/Sentry require MCP tools, all
source fetches must use `general-purpose` agents.

```
# Single tool-call block — all launch concurrently
Agent(subagent_type=source_agent_type,  # see table above
    model="haiku",                      # Gather tier — context fetch only
    description=f"Fetch {source.type} {source.id}",
    prompt=f"""Fetch context for {source.type}: {source.id}
    {source_specific_instructions}
    Return a structured summary:
    - Title/subject
    - Status (open/closed/merged)
    - Key details (2-3 sentences)
    - Cross-references found (URLs, ticket IDs)
    Do NOT return full body text — summarize.""",
    run_in_background=true)
```

**Web URLs** (documentation, reference pages) should be fetched
in the main session via `WebFetch`, not dispatched to subagents.

### Source-Specific Instructions

| Source type | Agent type | Subagent instructions |
|-------------|-----------|----------------------|
| `github-issue` | general-purpose | Call `mcp__plugin_Dev10x_cli__issue_get(issue_number=$NUMBER, repo="$REPO")`. Return title, status, labels, body summary, linked PRs. |
| `github-pr` | general-purpose | Run `gh pr view --json title,body,headRefName,state,mergedAt,reviews`. Return title, status, branch, review comment count. |
| `linear-ticket` | general-purpose | Call `mcp__claude_ai_Linear__get_issue(issueId)`. Return title, status, parent ID, relations, comment summaries. |
| `jira-ticket` | general-purpose | Use `Dev10x:jira` skill to fetch ticket. Return title, status, assignee, linked issues. |
| `slack-thread` | general-purpose | Call `mcp__claude_ai_Slack__slack_read_thread(channelId, threadTs)`. Return message count, key decisions, action items. |
| `sentry-issue` | general-purpose | Call `mcp__sentry__get_issue_details(issueId)`. Return error type, frequency, first/last seen, top stack frame. |
| `note` | (none) | No subagent needed — pass through as-is. |

### Cross-Reference Expansion (One Level)

After the initial fetch, scan all gathered text for references
to other sources. Add them to the sources list and fetch:

- **PR body** mentions `Fixes: GH-N` or `Fixes: TEAM-N` → fetch that ticket
- **Ticket body** contains Sentry URL → fetch that Sentry issue
- **Ticket body** mentions PR `#N` or branch name → fetch that PR
- **Linear ticket** has parent or relations → fetch related tickets
- **Ticket comments** contain any of the above patterns → fetch

Do NOT expand beyond one level — keep the gathering phase fast.

### Output: Context Summary

Present a structured summary of everything gathered:

```markdown
## Context Summary

### Sources (N gathered)
- [github-issue] GH-15: Title here (OPEN)
- [slack-thread] #channel-name: 5 messages
- [sentry-issue] #12345: ErrorType — 145 events in 7 days
- [note] "check the retry logic"

### Cross-References Found
- [sentry-issue] #67890 (from ticket body)
- [github-pr] #42: PR title (merged)

### Key Details
[Brief synthesis: what the work is about, who reported it,
severity if applicable, related context from Slack/Sentry]
```

---

## Phase 3: Plan (Lightweight Steps)

**Phase 3 is a MECHANICAL step, not a creative step.** Read the
playbook YAML, find the matching play, and convert each step to a
`TaskCreate` call. Do NOT generate a custom plan. Do NOT use
`Agent(Plan)` subagents. The playbook IS the plan — your job is
to instantiate it as tasks.

**REQUIRED: Create exactly one `TaskCreate` per play step.** Do
not collapse, merge, or abbreviate steps. Each step in the
approved play template becomes one task — this is the supervisor's
interface for tracking progress and adding work. Collapsing 14
steps into 5 makes the remaining 9 invisible and unexecuted.

**This applies at Phase 3 (task creation), not Phase 4
(execution).** The bugfix play's "Investigate root cause" epic
prompt says "skip sub-steps if root cause is obvious" — that
guidance applies when *expanding* the epic in Phase 4. In Phase
3, ALL play steps MUST become `TaskCreate` calls regardless of
how obvious the fix seems. The task list is created first; the
agent adapts during execution.

**Anti-pattern (GH-729, GH-928):** A session collapsed
"Reproduce the issue", "Investigate root cause", and "Implement
fix" into a single task "Investigate and implement fix" because
the root cause seemed obvious. Session `da0d9c73` repeated
this — creating 12 tasks instead of 14 and skipping the
TaskList self-check entirely. This is a Phase 3 violation.
All play steps MUST become tasks even if Phase 4 execution
skips sub-steps.

The task list is the supervisor's interface for tracking progress
and adding new tasks during the session.

### Step Types

- **Detailed** — small, immediately executable (2-5 min).
  Created with `metadata: {"type": "detailed"}`.
- **Epic** — placeholder for a phase expanded when reached.
  Created with `metadata: {"type": "epic"}`. Description says
  what the phase accomplishes, not how.

### Generating the Plan

Play templates are loaded from the `Dev10x:playbook` system.
Each work type has a default play with parent-child steps
that can be overridden per project.

**Play source** (resolved in order — see `references/config-resolution.md`):
1. `.claude/Dev10x/playbooks/work-on.yaml` — project-local override
2. `~/.claude/memory/Dev10x/playbooks/work-on.yaml` — global with
   repo matching (get repo via `git remote get-url origin`, walk
   `projects[].match` globs, use first hit's `overrides`/`fragments`)
3. `${CLAUDE_PLUGIN_ROOT}/skills/playbook/references/playbook.yaml`

**Playbook schema:** See the `Dev10x:playbook` skill's
`references/playbook.yaml` for the full schema with all 5 plays.
Users can customize plays interactively via
`/Dev10x:playbook edit work-on <play>`.

Each play has:
- `prompt` — heuristic guidance for when this play applies and
  how to adapt it based on gathered context (optional)
- `steps` — ordered list of play steps

Each step in the play has:
- `subject` — task title (required)
- `type` — `detailed` or `epic` (required)
- `prompt` — expansion guidance for the agent executing this
  step; describes what to do, what to look for, or how to
  adapt the step based on context (optional)
- `agent` — agent name to invoke when executing this step (optional)
- `skills` — list of skills to delegate to (optional)
- `steps` — child steps for pre-templated epic expansion (optional)
- `condition` — hint for conditional execution (optional)

### Self-Check Before Plan Generation

**REQUIRED:** Before generating any tasks, you MUST have read
a playbook file. Call `Read` on the playbook path and verify
you received YAML content with a `defaults:` key containing
play definitions. If you cannot confirm this, STOP.

**Loading the play:**
1. Determine the `work_type` from gathered context (see table below)
2. Resolve the playbook using the 3-tier resolution order above:
   a. Try `.claude/Dev10x/playbooks/work-on.yaml` (project-local)
   b. Try `~/.claude/memory/Dev10x/playbooks/work-on.yaml` (global)
      — if found, get repo via `git remote get-url origin`, walk
      `projects[].match` globs; use first matching entry's config.
      Top-level `fragments` are shared across all matched projects.
   c. Fall back to `${CLAUDE_PLUGIN_ROOT}/skills/playbook/references/playbook.yaml`
3. **VERIFY: Confirm the playbook loaded successfully.** Check that
   the read returned YAML with play steps present (either under
   `defaults.<work_type>.steps`, `overrides[].steps`, or
   `projects[].overrides[].steps`).
   If ALL paths fail (file missing or unreadable), STOP and report
   the error to the user. Do NOT fall back to generating an ad-hoc
   plan. The playbook IS the plan — without it, Phase 3 cannot
   produce a correct task list.
   **Unmatched play fallback:** If the playbook loaded successfully
   but no play matches the detected `work_type`, fall back to the
   `feature` play (which has the most complete shipping pipeline).
   Do NOT generate an ad-hoc plan — ad-hoc plans lack `skills:`
   fields on steps, causing agents to bypass skill wrappers and
   miss guardrails (gitmoji, JTBD, Fixes links, CI monitoring).
   Log the mismatch: "No play for work_type='{type}', falling
   back to 'feature' play."
4. Resolve: overrides first (same as acceptance-criteria), then
   defaults, then schema fallback
5. **Resolve fragment references:** Walk the step list. When a
   step has `fragment: <name>`, look up the name first in the
   user override file's `fragments` map, then in the default
   playbook's `fragments` map (user fragments shadow defaults).
   Replace the reference with the fragment's steps, applying
   any `condition` override from the reference to each expanded
   step. Error on missing fragments; detect circular refs
   (max depth 3).
6. **Apply active modes:** Read `active_modes` from
   `.claude/Dev10x/session.yaml` (session) and the project
   playbook file. For each step with a `modes:` mapping:
   - If any active mode says `skip`, remove the step
   - Otherwise merge field overrides from active modes
     (last-listed mode wins on conflicts)
   - Apply `mode_extensions` from project file on top
   See `references/execution-modes.md` for precedence rules.
7. **Apply friction-level adaptations:** Read `friction_level`
   from `.claude/Dev10x/session.yaml`. For each step with a
   `friction:` mapping matching the current level:
   - If `skip: true`, remove the step
   - Otherwise merge field overrides (prompt, subject, etc.)
   See `references/friction-levels.md` § Playbook Integration.
8. For each remaining step, create a `TaskCreate` with the
   step's `subject`, `type` in metadata, and `agent`/`skills`
   in metadata if present
9. If a step has child `steps`, store them in metadata for
   expansion when the epic is reached (Phase 4)
10. **VERIFY: Call `TaskList` and count Phase 4 subtasks.** The
    count must match the number of steps after mode/friction
    resolution (not the raw play step count). If fewer tasks
    exist than resolved steps, go back and create the missing
    ones. **DO NOT mark Phase 3 complete until this count
    matches.** The VERIFY is not optional — skipping it is a
    Phase 3 compliance violation (GH-729, GH-928). Example: the
    bugfix
    play with `shipping-pipeline-solo` fragment produces 14
    steps. If `TaskList` shows fewer than 14 Phase 4 subtasks,
    you skipped or collapsed steps — create them now.

**Work type classification:**

| Context | Work type |
|---------|-----------|
| Ticket with implementation | `feature` |
| Sentry/bug ticket | `bugfix` |
| PR with review comments | `pr-continuation` |
| No ticket, no PR | `local-only` |
| Sentry/Slack only, no fix planned | `investigation` |

**Workspace step adjustment:** If Phase 1 detected a matching
feature branch already exists, skip the "Set up workspace" step.
If running in a worktree with a generic branch, keep it.

These plan steps become subtasks of the Phase 4 top-level task.
The last subtask is always acceptance criteria verification.

### Acceptance Criteria Verification

The **last task** in every plan verifies the work is shippable
or ready for handover.

**REQUIRED:** Delegate to `Dev10x:verify-acc-dod` skill:

1. `Skill(skill="Dev10x:verify-acc-dod", args="<work_type>")`

The skill handles criteria resolution (YAML file, defaults,
overrides), automated state checks (CI, PR, working copy),
and user confirmation. See the `Dev10x:verify-acc-dod` skill
for the full criteria schema and verification protocol.

**Playbook override note:** Solo-maintainer or project-specific
playbook overrides may substitute an inline acceptance prompt
for this delegation. When a playbook step replaces the
`verify-acc-dod` delegation with its own `prompt:`, the inline
prompt is a valid substitution — not a compliance violation.
Skill audits should classify this as COMPLIANT (playbook
substitution), not SKIPPED_STEP.

### Example Plays (Defaults)

These are the built-in default plays. Full YAML definitions
with pre-templated epic children live in the `Dev10x:playbook`
skill. Users can customize these via
`/Dev10x:playbook edit work-on <play>`.

**Feature from ticket** (subtasks of Phase 4):
```
4.1  [detailed] Set up workspace          → Dev10x:ticket-branch
4.2  [detailed] Draft Job Story           → Dev10x:jtbd
4.3  [epic]     Design implementation approach
       ├─ Read relevant code
       ├─ Identify affected components
       └─ Propose approach
4.4  [epic]     Implement changes
4.5  [epic]     Verify
       ├─ Run tests                       → test
       └─ Run lint
4.6  [detailed] Code review               → Dev10x:review + Dev10x:review-fix
4.7  [detailed] Commit outstanding changes → Dev10x:git-commit
4.8  [detailed] Create draft PR           → Dev10x:gh-pr-create (--unattended)
4.9  [detailed] Monitor CI                → Dev10x:gh-pr-monitor
4.10 [epic]     Apply fixups              → Dev10x:gh-pr-respond
4.11 [detailed] Groom commit history      → Dev10x:git-groom
4.12 [detailed] Update PR description     → Dev10x:gh-pr-create (update mode)
4.13 [detailed] Request review            → Dev10x:gh-pr-request-review
4.14 [detailed] Verify acceptance criteria
```

**Bug fix from Sentry + ticket:**

**Evidence-first rule:** Before selecting files to edit, review
all gathered evidence (Sentry stack traces, Linear comments,
Slack context). The error location in the stack trace identifies
the failing code path — do NOT skip to implementation based on
the ticket title alone. If Sentry or Linear evidence names a
specific file/line, that is the starting point for investigation.

```
4.1  [detailed] Set up workspace          → Dev10x:ticket-branch
4.2  [detailed] Reproduce the issue
4.3  [epic]     Investigate root cause
       ├─ Analyze error traces
       └─ Identify failing code path
4.4  [epic]     Implement fix
4.5  [epic]     Verify fix
       ├─ Run existing tests              → test
       └─ Add regression test
4.6  [detailed] Code review               → Dev10x:review + Dev10x:review-fix
4.7  [detailed] Commit outstanding changes → Dev10x:git-commit
4.8  [detailed] Create draft PR           → Dev10x:gh-pr-create (--unattended)
4.9  [detailed] Monitor CI                → Dev10x:gh-pr-monitor
4.10 [epic]     Apply fixups              → Dev10x:gh-pr-respond
4.11 [detailed] Groom commit history      → Dev10x:git-groom
4.12 [detailed] Update PR description     → Dev10x:gh-pr-create (update mode)
4.13 [detailed] Request review            → Dev10x:gh-pr-request-review
4.14 [detailed] Verify acceptance criteria
```

**PR continuation:**
```
4.1  [detailed] Fetch PR and review context
4.2  [epic]     Address review comments
4.3  [epic]     Apply fixups              → Dev10x:gh-pr-respond
4.4  [detailed] Code review               → Dev10x:review + Dev10x:review-fix
4.5  [detailed] Commit outstanding changes → Dev10x:git-commit
4.6  [detailed] Monitor CI                → Dev10x:gh-pr-monitor
4.7  [detailed] Groom commit history      → Dev10x:git-groom
4.8  [detailed] Update PR description     → Dev10x:gh-pr-create (update mode)
4.9  [detailed] Request re-review         → Dev10x:gh-pr-request-review
4.10 [detailed] Verify acceptance criteria
```

**Local-only work (no ticket, no PR):**
```
4.1  [detailed] Summarize the work from gathered context
4.2  [epic]     Implement changes
4.3  [epic]     Verify
       ├─ Run tests                       → test
       └─ Run lint
4.4  [detailed] Decide: create ticket, create PR, or done
4.5  [detailed] Code review               → Dev10x:review + Dev10x:review-fix (if-pr-decided)
4.6  [detailed] Commit outstanding changes → Dev10x:git-commit (if-pr-decided)
4.7  [detailed] Create draft PR           → Dev10x:gh-pr-create (if-pr-decided)
4.8  [detailed] Monitor CI                → Dev10x:gh-pr-monitor (if-pr-decided)
4.9  [epic]     Apply fixups              → Dev10x:gh-pr-respond (if-pr-decided)
4.10 [detailed] Groom commit history      → Dev10x:git-groom (if-pr-decided)
4.11 [detailed] Update PR description     → Dev10x:gh-pr-create (if-pr-decided)
4.12 [detailed] Request review            → Dev10x:gh-pr-request-review (if-pr-decided)
4.13 [detailed] Verify acceptance criteria
```

**Investigation (no fix planned):**
```
4.1  [detailed] Summarize findings from gathered context
4.2  [epic]     Investigate in codebase
       ├─ Trace relevant code paths
       └─ Check logs and error patterns
4.3  [detailed] Document findings and next steps
4.4  [detailed] Decide: create ticket, fix now, or done
```

### Supervisor Approval Gate

Present the plan as a numbered list.

**Implicit approval bypass:** Skip `AskUserQuestion` ONLY when
ALL three conditions are met:
1. User input contains **numbered steps** (not just a list of
   tickets, URLs, or a prose description)
2. The steps explicitly cover **deliverables**, **verification**,
   AND **integration/shipping** (commit, PR, merge)
3. The steps are **actionable as-is** — not "investigate X" or
   "fix the issues" but concrete actions like "add retry logic
   to payments/service.py"

A list of ticket URLs, a vague description, or bullet points
without shipping steps does NOT qualify — always present the
plan gate in those cases.

**Natural language mapping:** User phrases like "prepare a draft",
"for my approval", "let me review first", "show me the plan", or
"what's the plan" all map to THIS gate. Present the plan via
`AskUserQuestion` — do not write a document, create a plan file,
or use Claude Code's built-in plan mode.

**REQUIRED: Call `AskUserQuestion`** when the plan was
agent-generated (do NOT use plain text).

**Adaptive friction behavior (GH-808):** At adaptive level,
auto-select "Approve (Recommended)" — proceed directly to
Phase 4 without calling `AskUserQuestion`. This means: approve
the plan and start execution immediately. Do NOT skip the gate
entirely (which would leave the plan unapproved and execution
blocked). Auto-select = execute the recommended action.

**Guided/Strict friction:** Call `AskUserQuestion`:

1. `AskUserQuestion(questions=[{question: "How would you like to proceed with the work plan?", header: "Plan", options: [{label: "Approve (Recommended)", description: "Start execution immediately"}, {label: "Edit", description: "Describe what to change (add/remove/reorder steps)"}], multiSelect: false}])`

After approval (explicit or auto-selected), set task
dependencies where appropriate (use `TaskUpdate` with
`addBlockedBy`). Mark the first task as `in_progress` and
begin Phase 4.

### Persist Plan Context

**REQUIRED after plan approval (GH-760 F2).** Execute these
calls immediately — do NOT defer or skip:

1. `mcp__plugin_Dev10x_cli__plan_sync_set_context(args=["work_type=<detected_work_type>", "tickets=<JSON array of ticket IDs>", "routing_table={\"commit\":\"Skill(Dev10x:git-commit)\",\"create_pr\":\"Skill(Dev10x:gh-pr-create)\",\"monitor_ci\":\"Skill(Dev10x:gh-pr-monitor)\",\"push\":\"Skill(Dev10x:git)\",\"groom\":\"Skill(Dev10x:git-groom)\",\"branch\":\"Skill(Dev10x:ticket-branch)\",\"verify_acceptance\":\"Skill(Dev10x:verify-acc-dod)\",\"merge_pr\":\"Skill(Dev10x:gh-pr-merge)\"}"])`
2. `mcp__plugin_Dev10x_cli__plan_sync_set_context(args=["gathered_summary=<1-3 sentence summary>"])`

This ensures the PreCompact hook can inject the routing table
and work type into the recovery context. Without this, the
agent loses skill-to-action mappings after compaction (GH-477).
Prior code-block formatting was treated as advisory — the
numbered list enforces execution per
`skill-orchestration-format.md`.

---

## Phase 4: Execute (Adaptive, Auto-Advance)

Work through the approved task list. Update task status via
`TaskUpdate` as work progresses.

### Progress Compaction

After completing each phase boundary (e.g., all gather subtasks,
all implementation subtasks), compact completed tasks into a brief
summary via `TaskUpdate` metadata. This frees context window for
remaining work. See `references/task-orchestration.md` Pattern 8
for the full compaction protocol.

### Context Fill Monitoring (GH-884)

**Advisory check at phase boundaries.** Quality degrades when
context utilization exceeds ~40%. Check context fill at these
transition points:

| Transition | When |
|-----------|------|
| Phase 2 → Phase 3 | After all gather subagents return |
| Phase 3 → Phase 4 | After plan approval |
| Mid-Phase 4 | After completing implementation epic |

**Check method:** Approximate context fill from conversation
length. If the Claude Code harness exposes token count or
context utilization, use it directly. Otherwise estimate from
message count and tool result sizes.

**When context exceeds 40%:**
1. Log: "Context fill ~{N}% — consider mitigation"
2. **Recommended mitigations:**
   - Delegate remaining implementation to subagents (use
     haiku for data collection, sonnet for analysis)
   - Compact completed task metadata (Pattern 8)
   - For large remaining work: spawn a fresh session with
     `Dev10x:session-wrap-up` + resume instructions
3. Do NOT block execution — this is advisory. Some tasks
   legitimately need deep context (e.g., cross-cutting
   refactors spanning many files).

**Skip when:** Session has fewer than 10 tool calls (too
early to measure meaningfully).

### Skill Routing Enforcement

**Hard rule — applies to ALL plans and ALL work types
(feature, bugfix, local-only, investigation, pr-continuation):**

| Action | MUST delegate to | Never use directly |
|--------|-----------------|-------------------|
| Run tests | `Skill(test)` | `pytest`, `uv run pytest`, `python -m pytest` |
| Create a commit | `Skill(Dev10x:git-commit)` | `git commit` |
| Create a PR | `Skill(Dev10x:gh-pr-create)` | `gh pr create` |
| Monitor CI | `Skill(Dev10x:gh-pr-monitor)` | `gh pr checks --watch` |
| Push to remote | `Skill(Dev10x:git)` | `git push` |
| Groom history | `Skill(Dev10x:git-groom)` | `git rebase -i`, `git develop-log` for assessment |
| Create branch | `Skill(Dev10x:ticket-branch)` | `git checkout -b` |
| Create a skill | `Skill(Dev10x:skill-create)` | Writing SKILL.md directly |
| Check PR state | `mcp__plugin_Dev10x_cli__pr_detect` | `gh pr view --json` |
| Verify PR readiness | `mcp__plugin_Dev10x_cli__verify_pr_state` | `gh pr checks` |
| Verify acceptance criteria | `Skill(Dev10x:verify-acc-dod)` | Inline checks |
| Merge PR | `Skill(Dev10x:gh-pr-merge)` | `gh pr merge`, `git merge` |

This table survives context compaction — it is the canonical
routing for shipping actions. If you are about to run a raw
git/gh command that appears in the "Never use directly" column,
STOP and invoke the corresponding skill instead.

**Compaction preservation (CRITICAL):** When context is
compacted, the summary MUST retain this routing table
verbatim. Without it, the agent loses skill-to-action
mappings and falls back to raw CLI commands — the #1
source of guardrail bypasses (24% compliance in GH-477).
Re-inject the table into the compacted context as a
**numbered list** (not a code block — code blocks are treated
as advisory examples per `skill-orchestration-format.md`).
**Self-check after compaction:** After any context compaction
event, verify the routing table is still present by scanning
for "Skill(Dev10x:git-commit)" in the current context. If
missing, re-read this section before proceeding.

1. run tests → `Skill(test)`
2. commit → `Skill(Dev10x:git-commit)`
3. create PR → `Skill(Dev10x:gh-pr-create)`
4. monitor CI → `Skill(Dev10x:gh-pr-monitor)`
5. push → `Skill(Dev10x:git)`
6. groom → `Skill(Dev10x:git-groom)`
7. branch → `Skill(Dev10x:ticket-branch)`
8. create skill → `Skill(Dev10x:skill-create)`
9. check PR state → `mcp__plugin_Dev10x_cli__pr_detect`
10. verify PR readiness → `mcp__plugin_Dev10x_cli__verify_pr_state`
11. verify acceptance → `Skill(Dev10x:verify-acc-dod)`
12. merge PR → `Skill(Dev10x:gh-pr-merge)`

### Groom Step: Always Delegate, Never Self-Assess

**Hard rule (GH-505, GH-776, GH-929):** When the plan includes
a "Groom commit history" step, you MUST invoke
`Skill(Dev10x:git-groom)` and let the skill run its own
analysis. Do NOT run `git develop-log`, `git log`, or any
commit inspection to pre-assess whether grooming is needed —
not before invoking the skill, and not after invoking the
skill to override its decision. The groom skill's Phase 2
strategy gate determines whether grooming is required — that
decision belongs to the skill, not to the orchestrator.

**Anti-pattern (GH-776, GH-929):** The orchestrator
pre-assessed "single commit, nothing to groom" and marked
the task complete without invoking the skill. Session
`da0d9c73` repeated this — third recurrence. Even when the
groom skill is expected to be a no-op, the skill must run
its own logic. The orchestrator must not inspect commit
history to predict the outcome.

### CI Re-Monitoring After Force Push

**Hard rule:** Force push (from `Dev10x:git-groom` or conflict
rebase) invalidates all previous CI results. After any force
push, you MUST re-invoke `Skill(Dev10x:gh-pr-monitor)` to
monitor the new CI runs. Do NOT declare CI green based on
pre-groom results — the new HEAD has different commit SHAs
and GitHub runs fresh checks against it.

This applies to the shipping pipeline sequence:
```
... → Groom (force push) → RE-MONITOR CI → Update PR → ...
```

### Apply Fixups Completion Guard (GH-851 F2)

**Hard rule:** The "Apply fixups" task (4.10) CANNOT be marked
complete until ALL PR checks — including automated review bots
(claude-review, hygiene-review, openai-review) — have finished.
A monitor returning "CI green" covers only core CI checks. Bot
reviews are separate GitHub check runs that may still be PENDING
when core CI passes. Verify via `gh pr checks` that zero checks
remain in PENDING or IN_PROGRESS state before marking complete.

### Post-PR Review-Comment Routing (GH-43)

**Hard rule:** ANY review comment on the PR — human OR bot
(claude-review, hygiene-review, openai-review) — MUST be
addressed via `Skill(Dev10x:gh-pr-respond)`. Do NOT use raw
`gh api PATCH`, `gh pr edit`, or `gh pr comment` to "just edit
the PR body" or "just post a quick reply" inline. The
gh-pr-respond skill runs the documented triage → fixup →
resolve flow that bypasses get skipped when the agent edits
directly.

**Anti-pattern (GH-43):** Bot review surfaces "Fix JTBD voice"
on PR body; agent runs `gh api -X PATCH .../pulls/N -F body=@...`
followed by `gh pr comment N --body "..."`. The fix lands but
the skill's triage/fixup/resolve flow is bypassed. The agent
rationalizes "this is a one-liner, the skill is overkill" — that
rationalization is the violation. Skill delegation is mandatory
regardless of the comment's apparent simplicity.

**Detection signal:** If you are about to call `gh api PATCH
.../pulls/`, `gh pr edit`, or `gh pr comment` to respond to a
PR review comment, STOP and invoke `Skill(Dev10x:gh-pr-respond)`
instead. The skill handles single-comment cases just as well as
batch.

### Auto-Advance Rule

See `references/task-orchestration.md` for the full pattern.

**Complete a task → immediately start the next.** Do not pause
between tasks to ask "should I continue?" or wait for the user
to say "go" / "next" / "continue". The approved plan is the
authorization to proceed.

**Auto-advance on commits:** After creating a commit, immediately
proceed to the next task. Never pause to show the commit or ask
for confirmation — the commit is done, move on.

**Auto-advance on code review (GH-932):** When delegating to
`Dev10x:review` from the shipping pipeline, pass
`args="--unattended"` so the skill skips the zero-findings
AskUserQuestion gate and auto-advances to `Dev10x:review-fix`.
Session `da0d9c73` invoked the skill without this flag,
causing it to skip the mandatory attended-mode gate and the
findings file write. The playbook `prompt:` says to use
`--unattended` — this is not advisory, it is required.

**Auto-advance on draft PR creation:** Create the draft PR and
immediately proceed to **Monitor CI** — this is mandatory, not
optional. Do not block on PR preview approval when executing
the shipping pipeline — the PR body and title can always be
updated later via the "Update PR description" step. When
delegating to `Dev10x:gh-pr-create`, pass
`args="--unattended"` to skip the preview gate.

**Hard rule: Always invoke CI monitor after PR creation.**
After `Dev10x:gh-pr-create` completes, the very next action
MUST be `Skill(Dev10x:gh-pr-monitor)`. Do NOT skip this step
even if the PR "looks fine" or CI "should pass." Session
GH-477 showed the monitor was not invoked for 12+ hours after
PR creation, requiring 9 user prompts. The monitor is part of
the shipping pipeline, not an optional convenience.

**Shipping pipeline is atomic:** Once the main implementation
and verification are done, the remaining shipping steps (code
review → commit → PR → CI → groom → update → ready → merge)
form an atomic sequence. Auto-advance through ALL of them
without pausing for user input. Do NOT stop after posting
review replies, after creating the PR, or after grooming —
continue until the plan completion gate or a genuine blocker.

**Batched Decision Queue:** When a task hits a genuine A/B
decision, do NOT interrupt the user immediately. Instead:

1. Queue the decision in task metadata:
   ```
   TaskUpdate(taskId, status="pending",
       metadata={"decision_needed": "description",
                 "options": ["A", "B", "C"]})
   ```
2. Move to the next unblocked task and keep advancing.
3. Only interrupt when ALL tasks are blocked — collect all
   queued decisions into one `AskUserQuestion` batch (1-4 Qs).
4. After the user answers, unblock and resume auto-advancing.

The supervisor can step away, come back to answer all decisions
at once, then step away again confident maximum progress will
happen before the next interruption.

**If blocked on the current task** (waiting for user input,
external dependency, CI), check whether the next unblocked
task can start. Examples:
- Waiting for CI? Start self-review in parallel.
- Waiting for user input on approach? Create the branch or
  draft the Job Story meanwhile.
- Stuck on a sub-task? Mark it `pending` with a note and
  advance to the next unblocked task in the list.

Return to the blocked task once the blocker resolves.

### Plan Completion Gate

**REQUIRED: Pre-gate verification checklist.** Before triggering
`AskUserQuestion`, verify ALL of the following:

1. All background agents have completed or reported results —
   check `TaskList` for any tasks still `in_progress`
2. No unaddressed review comments exist on the PR — check via
   `gh pr view --json reviewDecision,reviews`
3. CI checks have completed (not still running) — check via
   `gh pr checks`
4. Working copy is clean — `git status` shows no uncommitted
   changes
5. No pending fixup commits that haven't been pushed — compare
   local HEAD with remote tracking branch
6. **verify-acc-dod was invoked** — check the conversation for
   a `Skill(Dev10x:verify-acc-dod)` call. If absent, invoke it
   NOW before presenting the gate. This is the #1 bypass pattern
   (GH-471, GH-497, GH-930) — agents perform inline checks
   instead of delegating. Session `da0d9c73` repeated this —
   marking the task completed with an inline description and
   never firing the completion gate AskUserQuestion. The
   completion gate MUST NOT fire without it.

If any check fails, resolve it before presenting the gate.
Do NOT present "Work complete" as recommended when preconditions
are unmet.

**Background agent task status:** Tasks for background agents
(e.g., PR monitor dispatched via `run_in_background`) MUST remain
`in_progress` until the agent confirms completion. Do NOT mark
them `completed` on dispatch — only mark `completed` when the
agent's result notification arrives and confirms success.

**After all checks pass:**

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text).
Show the full task list via `TaskList`, then call:

1. `AskUserQuestion(questions=[{question: "All tasks completed. How would you like to proceed?", header: "Done", options: [{label: "Work complete — hand over (Recommended)", description: "All checks pass, ready to close"}, {label: "Add more tasks", description: "Continue with additional work"}, {label: "Revisit a step", description: "Re-examine a completed task"}], multiSelect: false}])`

Never auto-complete the plan without supervisor confirmation.
The supervisor must explicitly sign off that work is done.
Plain text questions (e.g., "Ready to merge?") are NOT
acceptable — they allow the session to auto-proceed without
structured confirmation.

### Executing Detailed Tasks

Run the task directly. If the task has a `prompt` in metadata,
use it as execution guidance. If the task has `skills` in
metadata, delegate to those skills in order.

**REQUIRED: When the playbook step lists `skills:`, you MUST
invoke via `Skill()`. Do NOT perform actions directly.** Skill
delegation ensures consistent behavior, proper tool declarations,
and reusable orchestration. Bypassing delegation by inlining the
skill's logic breaks these guarantees.

**Unattended mode compliance:** Auto-advance pressure in
unattended mode makes it tempting to perform operations directly
(e.g., `git checkout -b` instead of `Dev10x:ticket-branch`,
inline review instead of `Dev10x:review`). This is still a
violation — unattended mode changes the *pace*, not the *rules*.
If you catch yourself about to skip a `Skill()` call, stop and
invoke the skill. Refer to the **Skill Routing Enforcement**
table above — it lists every action that MUST use a skill
wrapper regardless of execution mode.

**Mandatory delegation flag:** When a playbook step has
`skills:` entries, delegation is mandatory — not advisory.
The `skills:` field means "invoke these via `Skill()`", not
"consider using these". Zero of 15 expected delegations in
session 05d49f11 were made because the enforcement was
treated as optional. It is not optional.

Common skill delegations:

| Task | Delegated to |
|------|-------------|
| Set up workspace (branch) | `Dev10x:ticket-branch` skill |
| Set up workspace (worktree) | `Dev10x:git-worktree` skill |
| Draft Job Story | `Dev10x:jtbd` skill (attended mode) |
| Update ticket status | Linear MCP (see references/team-info.md) |
| Fetch PR context | `gh pr view` + `gh pr diff` |
| Code review | `Dev10x:review` (`--unattended`) + `Dev10x:review-fix` skills |
| Commit changes | `Dev10x:git-commit` skill |
| Create draft PR | `Dev10x:gh-pr-create` skill (`--unattended`) |
| Monitor CI | `Dev10x:gh-pr-monitor` skill |
| Apply fixups to review | `Dev10x:gh-pr-respond` skill |
| Groom commit history | `Dev10x:git-groom` skill |
| Update PR description | `Dev10x:gh-pr-create` skill (update mode) |
| Request review | `Dev10x:gh-pr-request-review` skill |
| Merge PR | `Dev10x:gh-pr-merge` skill |

### Post-Step Skill Delegation Verification

**REQUIRED: After completing ANY playbook step that lists
`skills:`, verify the delegation occurred.** Before marking
the task `completed`, confirm:

1. The `Skill()` tool was called for each listed skill
2. Raw CLI commands were NOT used as substitutes (e.g.,
   `git commit` instead of `Skill(Dev10x:git-commit)`)
3. If you used raw commands instead of `Skill()`, STOP —
   re-do the step with proper delegation before proceeding

This check exists because under auto-advance pressure, the
agent rationalizes raw commands as "equivalent" to skill
invocations. They are not — skills enforce gitmoji, JTBD,
Fixes links, CI monitoring, and other guardrails that raw
commands skip.

**Special attention: verify-acc-dod delegation.** The
acceptance criteria step is the most commonly bypassed
delegation (GH-471, GH-930). Agents perform inline AC checks
(e.g., "CI green, PR merged, looks good") instead of
invoking `Skill(Dev10x:verify-acc-dod)`. The inline check
skips structured PR state verification (`gh pr checks`,
`gh pr view --json isDraft`) and the skill's own
`AskUserQuestion` gate. Always delegate — unless a playbook
override provides an explicit inline substitute.

After verification, mark the task `completed` via
`TaskUpdate` and move to the next task.

### Task Reconciliation After Skill Delegation

**REQUIRED:** After a delegated skill completes (e.g.,
`Dev10x:gh-pr-respond`, `Dev10x:gh-pr-monitor`), reconcile
the task list before proceeding. Delegated skills may create
their own tasks that overlap with the parent's remaining
pipeline steps. Without reconciliation, parent tasks remain
`pending` forever and the completion gate is never reached.

**Reconciliation protocol:**

1. Call `TaskList` after the delegated skill returns
2. Check if the delegated skill fulfilled any of the parent's
   remaining tasks (e.g., if `gh-pr-respond` ran groom + push,
   mark the parent's "Groom commit history" and "Push" tasks
   as `completed`)
3. Mark any tasks completed by the delegated skill's side
   effects — match by subject/action, not by task ID
4. If context compaction cleared the task list, recreate only
   the remaining uncompleted tasks from the playbook

This prevents the failure mode where delegated skills run
their own shipping pipeline, the parent's tasks are never
updated, and the completion gate never fires.

### Expanding Epic Tasks

When reaching an epic task:

1. **Read the step prompt** — if the task metadata contains a
   `prompt` field (from playbook.yaml), use it as guidance
   for how to execute or expand the step. The prompt may
   contain heuristics for adapting the step to context.
2. **Check for pre-templated children** — if the task metadata
   contains `steps` (from the playbook.yaml template), use
   those as the sub-task list instead of generating from scratch.
   Each child step may also have its own `prompt` for guidance.
   This gives users control over epic expansion via YAML.
3. **If no pre-templated children**, generate sub-tasks from
   context. This may involve:
   - Reading code to understand scope
   - `AskUserQuestion` for A/B decisions (e.g., "approach X
     vs approach Y?") — but only when the choice genuinely
     cannot be inferred from context
   - Follow-up information gathering
4. **Delegate to listed skills** — if the task or sub-task has
   `skills` in metadata, invoke those skills in order. Multiple
   skills on one step run sequentially (each may depend on the
   previous).
5. **Present sub-tasks** briefly (inline, not a new approval
   gate) and begin executing immediately. Only ask for
   approval if the expansion reveals unexpected scope or
   trade-offs the supervisor should weigh in on.
6. **Check for parallelism** — if sub-tasks are independent,
   ask the supervisor before launching parallel agents
7. **Execute sub-tasks**, marking each completed as they finish.
   Auto-advance between sub-tasks (same rule as top-level).
8. **Mark the epic completed** when all sub-tasks are done

### Multi-Issue Execution

When multiple issues are provided, two strategies exist:

**Strategy A: Separate PRs (fanout — default)**

Each issue gets its own branch, PR, and full playbook play.
Use `Dev10x:fanout` for parallel execution or sequential
execution within `work-on`.

Each issue MUST execute the **full playbook play** — not a
collapsed subset. Fanout does NOT exempt individual issues
from the shipping pipeline.

**Strategy B: Bundled PR (atomic commits)**

All issues share one branch and one PR. Each issue becomes
one atomic commit. The shipping pipeline runs once for the
bundle, not per issue. Use this when issues are small,
related, and benefit from a single review cycle.

**Bundled execution pattern:**
```
1. Set up workspace (one branch for all issues)
2. For each issue (sequentially):
   a. Design approach for this issue
   b. Implement changes
   c. Create atomic commit (one per issue, ticket ID in msg)
3. Verify (run tests once for all changes)
4. Shipping pipeline (review → PR → CI → groom → merge)
```

The "Implement changes" epic expands to one sub-task per
issue. Each sub-task produces exactly one commit with the
issue's ticket ID in the message. The shipping pipeline
runs once — the PR references all bundled issues via
multiple `Fixes:` lines.

**Strategy selection:** When the user explicitly requests
bundling (e.g., "one PR", "atomic commits", "bundle these"),
use Strategy B. When the user provides multiple independent
issues without bundling intent, apply the **Same-Milestone
Heuristic (GH-948)** below; otherwise use Strategy A (fanout).
When still ambiguous, ask via `AskUserQuestion`.

**Same-Milestone Heuristic (GH-948):** Prefer Strategy B
(bundled) when ALL of these conditions hold:

1. **Same milestone** — every classified ticket belongs to
   the same GitHub milestone (or Linear project). Detect via
   the `milestone` field from `mcp__plugin_Dev10x_cli__issue_get`
   or the Linear project field. Skip this check if any ticket
   lacks a milestone field.
2. **Solo-maintainer mode active** — `active_modes` in
   `.claude/Dev10x/session.yaml` contains `solo-maintainer`.
   Team reviewers imply separate review cycles, so fanout
   remains correct for team modes.
3. **Small/medium effort** — no ticket is labeled `effort:L`,
   `effort:XL`, or `size:L`+. Large epics warrant isolation
   even within a milestone.
4. **Thematically related** — tickets share at least one
   non-milestone label (e.g., all `audit:patterns`, all
   `refactor:cleanup`).

When all four conditions hold, auto-select Strategy B at
adaptive friction level; recommend Strategy B at guided level.
When any condition fails, fall back to Strategy A (fanout).

The heuristic only changes the **recommended** strategy — the
strategy gate still presents both options so the user can
override.

**Anti-pattern (PROHIBITED for both strategies):**
```
for each issue:
  branch → edit → commit → push → PR   # 5 steps
```

### Parallelism Policy

| Phase | Parallelism | Approval needed? |
|-------|------------|-----------------|
| Phase 2 (Gather) | Auto-parallel | No |
| Phase 4 (detailed tasks) | Sequential | No |
| Phase 4 (epic sub-tasks) | Parallel if independent | Yes — ask supervisor |

When asking about parallelism, present which tasks would run
concurrently and why they're independent:

```
Tasks 4a and 4b are independent (different files, no shared state).
Run them in parallel?
- Yes, launch parallel agents (Recommended)
- No, run sequentially
```

**Worktree isolation limitation:** Agents dispatched with
`isolation: "worktree"` cannot use the `Write` tool — Claude Code
restricts Write access to the main session's working directory.
Use `Bash(cat <<'EOF' > file)` or `Edit` as a workaround inside
worktree-isolated agents. Alternatively, avoid `isolation: "worktree"`
and use sequential tool calls in the main session instead.

**`bypassPermissions` limitation:** The `bypassPermissions` flag
does not propagate into worktree isolation contexts. If a task
step requires unattended execution inside a worktree agent, use
`mode: "dontAsk"` on the Agent call or avoid `isolation: "worktree"`
for that step. Sequential tool calls in the main session are the
safest fallback for permission-sensitive operations.

### Skill Delegation During Execution

**Workspace setup** (uses the decision from Phase 1):

| State | Action |
|-------|--------|
| Main repo, user wants worktree | Invoke `Dev10x:git-worktree` (creates branch internally — do NOT call `Dev10x:ticket-branch` first) |
| Main repo, work here | Invoke `Dev10x:ticket-branch` to create feature branch |
| Worktree, generic WT branch | Invoke `Dev10x:ticket-branch` to create work-specific branch from within the worktree |
| Worktree, matching feature branch | No action needed — branch already exists |

If the Phase 1 workspace decision was deferred (local-only
work):

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text, call spec: [ask-workspace-decision.md](./tool-calls/ask-workspace-decision.md)).
Options:
- Work here (Recommended) — Use current directory and branch
- New worktree — Create an isolated worktree

**Job Story drafting:**
- MUST invoke `Skill(Dev10x:jtbd)` explicitly — never draft inline
- Pass gathered context to avoid redundant API calls
- If approved, write back to the ticket:

| Tracker | Write-back |
|---------|-----------|
| GitHub | `gh issue comment` |
| Linear | Prepend to description via `save_issue` |
| JIRA | `Dev10x:jira` skill |

**Ticket status update (Linear only):**

**REQUIRED after workspace setup:** When a ticket-backed plan
starts execution (feature or bugfix), update the ticket status
to "In Progress" immediately after the "Set up workspace" step
completes. Do NOT defer this to the end of the session.

1. Get statuses: `list_issue_statuses(teamId)` from
   references/team-info.md
2. Find "In Progress" (type `started`)
3. Update: `save_issue(id, stateId)`
4. Skip if already "In Progress"; warn if "Done"/"Canceled"

---

## Pause/Resume

At any pause signal ("wrap up", "pause", "that's enough for
today", end-of-session):

1. Invoke `Dev10x:session-wrap-up` — it reads `TaskList` and
   discovers all open tasks automatically
2. `Dev10x:session-wrap-up` handles routing each open item (PR
   bookmark, TODO.md, Slack DM, etc.)
3. The task list itself serves as resume context — when the user
   resumes work, they can invoke `Dev10x:park-discover` to find
   deferred items and `Dev10x:session-tasks` to see the saved
   task list

No custom bookmarking needed — leverage existing
`Dev10x:session-wrap-up` and `Dev10x:park` infrastructure.

---

## Important Notes

- **DO NOT use `ExitPlanMode` or Claude Code's built-in plan mode.**
  This skill has its own planning phase (Phase 3) that uses
  `TaskCreate` + `AskUserQuestion`. Writing a plan file and calling
  `ExitPlanMode` bypasses the playbook system and destroys the
  session's task-tracking capability. If the user asks to "see the
  plan" or "prepare a draft", present it via `AskUserQuestion` at
  the Phase 3 approval gate — never via plan mode.
- **Always create tasks via `TaskCreate`** — never skip the task
  list, even for single-step work. The supervisor uses it to add
  new tasks mid-session.
- Always verify ticket exists before creating a branch
- If ticket is "Done"/"Canceled" (Linear) or "closed" (GitHub),
  warn the user before proceeding
- Handle errors gracefully — if a fetch fails, continue with
  what was gathered and note the failure in the context summary
- Linear team UUID is in `references/team-info.md` (template)
- After completing work, use `Dev10x:gh-pr-create` to create the PR
- Do not modify ticket description or add comments unless the
  user explicitly approves (e.g., Job Story write-back)
- **Batch data files must use `.json` format** — never `.env`.
  Pre-tool-use hooks block `.env` file creation. When creating
  temporary data files (e.g., batch issue lists, config), use
  `.json` instead.

### Known Limitations

- **Worktree cleanup:** No skill currently handles worktree
  teardown after work completes. Users must manually run
  `git worktree remove <path>` when done.
- **PR merge-to-completion lifecycle:** The `Dev10x:gh-pr-monitor`
  skill stops after CI passes and review is requested — it does
  not monitor through to merge. Users must manually merge or
  re-invoke monitoring after approval.
- **Write tool in worktree agents:** See Parallelism Policy
  section for the `isolation: "worktree"` Write tool limitation.
- **`bypassPermissions` in worktree agents:** See Parallelism
  Policy section for the propagation limitation and workarounds.

## Resources

### references/team-info.md

Linear team configuration template: UUID, status mappings,
branch naming, Sentry integration patterns.

---

## Examples

### Example 1: Single Ticket URL

**User:** `/Dev10x:work-on https://github.com/org/repo/issues/15`

**Phase 1:** Classify → `github-issue`, repo=`org/repo`, number=15

**Phase 2:** Fetch issue. Body mentions Sentry URL → fetch Sentry
issue. Body mentions PR #42 → fetch PR. Produce context summary.

**Phase 3:** Load `feature` plan template (user overrides →
defaults → schema). Build subtasks of Phase 4:
```
4.1  [detailed] Set up workspace          → Dev10x:ticket-branch
4.2  [detailed] Draft Job Story           → Dev10x:jtbd
4.3  [epic]     Design implementation approach (3 children)
4.4  [epic]     Implement changes
4.5  [epic]     Verify (2 children)
4.6  [detailed] Code review               → Dev10x:review + Dev10x:review-fix
4.7  [detailed] Commit outstanding changes → Dev10x:git-commit
4.8  [detailed] Create draft PR           → Dev10x:gh-pr-create
4.9  [detailed] Monitor CI                → Dev10x:gh-pr-monitor
4.10 [epic]     Apply fixups              → Dev10x:gh-pr-respond
4.11 [detailed] Groom commit history      → Dev10x:git-groom
4.12 [detailed] Update PR description     → Dev10x:gh-pr-create
4.13 [detailed] Request review            → Dev10x:gh-pr-request-review
4.14 [detailed] Verify acceptance criteria
```
Supervisor approves.

**Phase 4:** Auto-advance through subtasks 4.1-4.10, expanding
epics as reached. No pauses between tasks unless a genuine
decision is needed.

### Example 2: Multiple Inputs

**User:** `/Dev10x:work-on TEAM-133 https://slack.com/archives/C123/p456 "check the retry logic"`

**Phase 1:** Classify →
- `linear-ticket` TEAM-133
- `slack-thread` C123/p456
- `note` "check the retry logic"

**Phase 2:** Fetch all three in parallel. Linear ticket links to
Sentry issue → fetch that too. Produce context summary with 4
sources.

**Phase 3:** Load `bugfix` plan template (Sentry issue detected):

```
4.1  [detailed] Set up workspace          → Dev10x:ticket-branch
4.2  [detailed] Reproduce the issue
4.3  [epic]     Investigate root cause (2 children)
4.4  [epic]     Implement fix
4.5  [epic]     Verify fix (2 children)
4.6  [detailed] Code review               → Dev10x:review + Dev10x:review-fix
4.7  [detailed] Commit outstanding changes → Dev10x:git-commit
4.8  [detailed] Create draft PR           → Dev10x:gh-pr-create
4.9  [detailed] Monitor CI                → Dev10x:gh-pr-monitor
4.10 [epic]     Apply fixups              → Dev10x:gh-pr-respond
4.11 [detailed] Groom commit history      → Dev10x:git-groom
4.12 [detailed] Update PR description     → Dev10x:gh-pr-create
4.13 [detailed] Request review            → Dev10x:gh-pr-request-review
4.14 [detailed] Verify acceptance criteria
```

### Example 3: PR Continuation

**User:** `/Dev10x:work-on https://github.com/org/repo/pull/42`

**Phase 1:** Classify → `github-pr`, number=42

**Phase 2:** Fetch PR. Body has `Fixes: GH-15` → fetch issue.
PR has 3 review comments → note them.

**Phase 3:** Load `pr-continuation` plan template:
```
4.1  [detailed] Fetch PR and review context
4.2  [epic]     Address review comments
4.3  [epic]     Apply fixups              → Dev10x:gh-pr-respond
4.4  [detailed] Code review               → Dev10x:review + Dev10x:review-fix
4.5  [detailed] Commit outstanding changes → Dev10x:git-commit
4.6  [detailed] Monitor CI                → Dev10x:gh-pr-monitor
4.7  [detailed] Groom commit history      → Dev10x:git-groom
4.8  [detailed] Update PR description     → Dev10x:gh-pr-create
4.9  [detailed] Request re-review         → Dev10x:gh-pr-request-review
4.10 [detailed] Verify acceptance criteria
```

### Example 4: Mid-Workflow Pause

User is at task 4 of 7 and says "let's wrap up for today".

1. Skill detects pause signal
2. Invokes `Dev10x:session-wrap-up`
3. `Dev10x:session-wrap-up` reads `TaskList` — sees 3 pending tasks
4. Routes each via `Dev10x:park` (e.g., PR bookmark, TODO.md)
5. Session ends with bookmark saved

Next session: user runs `Dev10x:discover` to find bookmarks and
resume where they left off.
