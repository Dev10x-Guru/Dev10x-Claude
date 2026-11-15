# ticket-create — Title Patterns, Label Signals, Tracker Recipes

Reference material moved out of `SKILL.md` to bring it near its line
budget (GH-1705). `SKILL.md` keeps the workflow, the Step 4e gate and
the Step 5 dispatch contract; this file holds the tables and the
per-tracker creation calls the Step 5 agent executes.

## Title Format Patterns (Step 2)

| Context | Pattern | Example |
|---------|---------|---------|
| Tech debt | "Fix tech debt in..." | "Fix tech debt in TestAddTireService flaky tests" |
| Bug fix | "Fix bug in..." | "Fix bug in payment processing timeout handling" |
| Enhancement | "Improve..." | "Improve customer search performance" |
| Refactoring | "Refactor..." | "Refactor invoice generation service" |
| Test improvement | "Fix flaky test in..." | "Fix flaky test in work order creation" |
| Missing feature | "Add..." | "Add retry mechanism for Square API" |

## Label Signals (Step 4b)

| Signal in the ticket | Label to propose |
|----------------------|------------------|
| Names a skill (`dev10x:fanout`, `gh-pr-create`, …) | the matching `skill:*` label |
| Permission prompt / allow-rule gap | `permission-friction` |
| Error swallowed or surfaced without diagnostics | `silent-failure` |
| Raw git/gh used where a wrapper is required | `routing-bypass` |
| Umbrella issue spanning milestones | `tracker` |
| New capability | `enhancement` |
| Incorrect behavior | `bug` |

Propose every label whose signal is present — labels are not
exclusive. When the roster contains a label this table does not
mention, prefer the roster: its description states its purpose.

## Tracker-Specific Creation (Step 5)

Include the relevant section in the Step 5 agent's prompt. The
fenced blocks are reference material for the dispatched agent, not
instructions for the main session.

### GitHub Issues

Write the description to a temp file first (inline `--body` strings
break shell quoting on markdown tables and long descriptions):

```bash
# Generate temp path via mktmp.sh, then write body via Write tool
BODY_FILE=$(/tmp/Dev10x/bin/mktmp.sh gh-issue body .md)
# Write description content to $BODY_FILE via the Write tool
gh issue create --repo "$REPO" --title "$TITLE" --body-file "$BODY_FILE" --label "$LABELS" --milestone "$MILESTONE"
```

Omit `--milestone` only when Step 4d found no confident match — in
which case `$LABELS` carries `needs-triage`.

**Title-in-file convention:** When the caller provides
`--body-file` without `--title`, use the wrapper script that
reads line 1 as the title and creates the issue in one call
(like `git commit -F`):

```bash
${CLAUDE_PLUGIN_ROOT}/skills/ticket-create/scripts/create-github-issue.sh "$BODY_FILE" "$REPO" "$LABELS"
```

This avoids passing titles with special characters in args
strings, which can cause permission friction.

### Linear

If a `project` parameter was provided by the caller, resolve the
project UUID first via `list_projects(team: "TEAM_UUID")` — never
pass a display name (name matching is exact and fails silently).
After creation, verify linkage with `get_issue(id)` and confirm
`projectId` matches the expected UUID. See `dev10x:linear`
§ Project Assignment.

```
mcp__claude_ai_Linear__save_issue(
    team: "TEAM_UUID",
    title: TITLE,
    description: DESCRIPTION,
    labels: [LABELS],
    project: "PROJECT_UUID"  # optional — resolved UUID only
)
```

### JIRA

Create via the Atlassian MCP `createJiraIssue` tool, mirroring the
GitHub/Linear branches above. The `dev10x:jira` skill ships only
read / search / update / comment / link scripts — it has **no create
path** — so the Atlassian MCP is the JIRA-creation surface (GH-631):

```
mcp__claude_ai_Atlassian__createJiraIssue(
    cloudId: <from getAccessibleAtlassianResources>,
    projectKey: <from getVisibleJiraProjects>,
    issueTypeName: <Task | Bug — from getJiraProjectIssueTypesMetadata>,
    summary: TITLE,
    description: DESCRIPTION,
)
```

Resolve `cloudId`, `projectKey`, and the issue-type name via the
read-only Atlassian tools (all pre-approved) before the create call;
use the live tool schema for exact field names.

The Atlassian ticket-management **write** tools (`createJiraIssue`,
`editJiraIssue`, `addCommentToJiraIssue`, `transitionJiraIssue`,
`createIssueLink`, …) **are** pre-approved via the
`mcp-atlassian-write` baseline permission group (GH-631). This
deliberately overrides the GH-593 write-precedence default, so the
Step 5 background creation agent can call `createJiraIssue`
unattended without stalling on a permission prompt.

**Troubleshooting (GH-899):** if these writes still prompt for
approval, the `mcp-atlassian-write` baseline group has not reached
your live `settings.json` yet — that is a seed/sync gap, not the
intended design. Re-apply base permissions with
`dev10x:plugin-maintenance` (or run `dev10x:upgrade-cleanup`, which
invokes it in full mode), then retry. See Step 5's inline-creation
exception in `SKILL.md` for a stopgap while the sync gap persists.

> Team-specific IDs are documented in the tracker skill (`dev10x:linear`, `dev10x:jira`).
