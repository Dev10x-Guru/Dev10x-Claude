---
name: Dev10x:park-discover
description: >
  Gather deferred items across all sources — so nothing is missed
  when starting a session or picking up where you left off.
  TRIGGER when: starting a session, picking up prior work, or checking
  for deferred items.
  DO NOT TRIGGER when: mid-session active work with no need to check
  deferred items.
user-invocable: true
invocation-name: Dev10x:park-discover
allowed-tools:
  - Read
  - Grep
  - Bash(git branch:*)
  - Bash(git log:*)
  - mcp__plugin_Dev10x_cli__pr_detect
  - mcp__plugin_Dev10x_cli__pr_comments
  - mcp__claude_ai_Slack__slack_search_public_and_private
---

# Dev10x:park-discover — Gather Deferred Items

**Announce:** "Using Dev10x:park-discover to check all deferral sources."

## Orchestration

This skill follows `references/task-orchestration.md` patterns.
Create a task at invocation, mark completed when done:

**REQUIRED: Create a task at invocation.** Execute at startup:

1. `TaskCreate(subject="Discover deferred items", activeForm="Discovering items")`

Mark completed when done: `TaskUpdate(taskId, status="completed")`

## When to Use

Invoke this skill when the user asks about existing deferred items:
- "what's deferred"
- "any open items from yesterday"
- "what do we have to pick up"
- "check for deferrals"

Do NOT use for writing new deferrals — use `Dev10x:park-todo` or
`Dev10x:park` instead.

## Substrate

The canonical store for deferred work is
`.claude/Dev10x/session.yaml` (GH-85). Every writer in the
park/session family appends a structured entry into its
`tasks:` list with a `source:` field that names the writer:

| `source:` value     | Written by                          |
|---------------------|-------------------------------------|
| `manual`            | `Dev10x:park` (target: TODO)        |
| `code-todo`         | `Dev10x:park-todo` (inline mode)    |
| `slack-reminder`    | `Dev10x:park-remind`                |
| `pr-bookmark`       | `Dev10x:park` (target: PR bookmark) |
| `session-wrap-up`   | `Dev10x:session-wrap-up` Phase 3b   |

External sources (Slack DMs, PR comments) remain as the
authoritative content; session.yaml carries a pointer
(`metadata.slack_ts`, `metadata.pr_url`) so the discovery
report can link out.

## Workflow

### 1. Read session.yaml (primary source)

Read `.claude/Dev10x/session.yaml` directly with the Read
tool. If the file does not exist, note "No session.yaml — no
local deferrals indexed" and skip to the external-sources
step.

```
Read(file_path="<repo-root>/.claude/Dev10x/session.yaml")
```

Parse the YAML and extract three sections:

- `continuation_prompt:` — a paragraph carrying diagnosed
  context from the prior session. Surface this **verbatim** in
  the report; do not summarize.
- `tasks:` — a list of structured entries. Each entry has
  `subject`, `status`, and (when present) `metadata` and
  `source`. Group by `source:` for the report.
- `insights:` — a list of lessons / decisions the prior
  session carried forward. Surface each item verbatim.

**Staleness classification (GH-782).** `Dev10x:session-wrap-up`
stamps the payload with `branch:`, `tickets:`, and `wrapped_at:`.
Classify the carried `continuation_prompt:` / `tasks:` /
`insights:` before presenting them, using the same rule as the
`session_stale` predicate the `session_adoption` gate applies:

- **Live** — the recorded `branch:` equals the current branch,
  OR a recorded ticket overlaps the resuming session's tickets.
- **Stale** — neither holds (identity mismatch), or `wrapped_at`
  is absent / clearly old.

Present live entries as actionable. Present stale entries under a
separate **Stale carryover (verify before resuming)** heading so
months-old, already-shipped items are surfaced for pruning rather
than re-offered as current work. Do not delete them — flagging is
enough; the user (or a later `Dev10x:park` write) decides.

### 2. Read legacy `.claude/TODO.md` (back-compat)

For repos that still carry items in the pre-GH-85 TODO file:

```
Read(file_path="<repo-root>/.claude/TODO.md")
```

If the file does not exist, note "No legacy TODO file" and
move on. Extract pending items (`- [ ]` lines) and present
them under a separate **Legacy TODO file** heading so the user
can migrate them into session.yaml.

### 3. Scan code TODOs / FIXMEs (Grep tool)

```
Grep(pattern="TODO|FIXME", path="src", output_mode="content", -n=true)
```

Distinguish in-flight items added in the current branch from
long-standing tech debt by checking the branch's commits:

```bash
git log --oneline origin/develop..HEAD
```

Only flag TODOs introduced on the current branch as actionable;
the rest are tech-debt notes for `Dev10x:project-audit`.

### 4. Open PR bookmark comments

Detect the PR for the current branch via the MCP wrapper:

```
mcp__plugin_Dev10x_cli__pr_detect(arg="")
```

If a PR is found, fetch its comments via the MCP wrapper:

```
mcp__plugin_Dev10x_cli__pr_comments(action="list", pr_number=<number>)
```

Filter for comments whose body starts with
`🔖 **Session bookmark**` (the standard marker set by
`Dev10x:session-wrap-up`). Include the matched comments under
**PR Session Bookmarks**.

Skip silently when `pr_detect` returns `{"error": ...}` — that
means no PR for the current branch, not a failure.

### 5. Slack DM reminders

Search Slack for self-reminders from the park-remind bot. The
`🔖` emoji is the standard prefix from `Dev10x:park-remind`:

```
mcp__claude_ai_Slack__slack_search_public_and_private(
  query="from:<@U0AD92X4X1S> 🔖",
  include_bots=true,
  sort="timestamp",
  sort_dir="desc",
  limit=20)
```

If no results, broaden to `from:<@U0AD92X4X1S> defer OR TODO OR
reminder`. Skip silently when Slack search returns no matches.

### 6. Memory notes (`~/.claude/memory/`)

Search the global memory directory for in-progress items:

```
Grep(pattern="defer|TODO|in-progress|pick up",
     path="/home/<user>/.claude/memory",
     glob="*.md",
     output_mode="content", -n=true)
```

These are user-global notes, not project-local — surface them
in a dedicated section.

## Presentation

Group findings in a scannable format. Always lead with
`continuation_prompt` verbatim — it is qualitatively richer
than any single TODO line.

```markdown
## Deferred Items — <project name>

### Continuation prompt (session.yaml)

<continuation_prompt verbatim, or "(none)">

### Open tasks (session.yaml)

#### From session-wrap-up
- [<status>] <subject> — <metadata summary>

#### From park (manual / PR bookmark)
- [<status>] <subject> — <metadata summary>

#### From park-todo (code-todo)
- [<status>] <subject> — `<metadata.location>`

#### From park-remind (slack-reminder)
- [<status>] <subject> — Slack ts `<metadata.slack_ts>`

### Carried insights (session.yaml)

- <insight 1 verbatim>
- <insight 2 verbatim>

### Stale carryover (verify before resuming)

- [<status>] <subject> — recorded on `<branch>` / `<tickets>`,
  wrapped `<wrapped_at>` (identity ≠ current session)

### PR Session Bookmarks

- PR #<n>: <comment excerpt> (<comment url>)

### Slack reminders

- <message excerpt> (<permalink>)

### Legacy TODO file (`.claude/TODO.md`)

- [ ] <legacy item> (consider migrating to session.yaml via park)

### Recent code TODOs (current branch)

- `<file>:<line>` <comment>

### Memory notes (`~/.claude/memory/`)

- <file>: <excerpt>
```

If a section has no matches, render it as `(none)` rather than
omitting — the absence is itself information.

## Next steps

After presenting findings, ask whether to resume any item.
**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text)
when at least one source returned items.

Options:
- Resume the continuation prompt (Recommended when present)
- Pick a specific task to work on
- Migrate legacy TODO.md items into session.yaml
- Just informational — close

## Commands and permissions

This skill MUST NOT use any of the following anti-patterns —
they all trigger permission friction and were the second
documented friction class in GH-85:

| ❌ Anti-pattern                              | ✅ Use instead                              |
|---------------------------------------------|---------------------------------------------|
| `cat .claude/TODO.md`                       | `Read(file_path=...)`                       |
| `grep -rn 'TODO' src/`                      | `Grep(pattern='TODO', path='src')`          |
| `date +%Y-%m-%d; git branch ...; basename` | Single Bash call per command                |
| `$(git rev-parse --show-toplevel)`          | Pass an absolute path to Read directly      |
| `gh pr view N --json comments --jq ...`     | `mcp__plugin_Dev10x_cli__pr_comments(...)` |

Every Bash invocation in this skill is a single command — no
`;` chaining, no `&&`, no subshells, no inline scripts.

## Used By

- `Dev10x:park-todo` — redirects here when user asks to review/check
  deferrals instead of write them
