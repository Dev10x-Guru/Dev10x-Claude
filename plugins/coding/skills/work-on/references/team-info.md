# Linear Team Reference (Template)

This file is a template. Replace placeholder values with your
team's actual configuration.

## Team Configuration

**Team Name:** My Team
**Team Key:** TEAM
**Team UUID:** `<your-linear-team-uuid>`

To find your team UUID, use:
`mcp__claude_ai_Linear__list_teams` and look for your team name.

## Status Mappings

Common Linear status names (may vary by team):

| Status Name | Type | Description |
|------------|------|-------------|
| Triage | `triage` | Newly created, needs review |
| Todo | `unstarted` | Ready to work on |
| In Progress | `started` | Currently being worked on |
| In Review | `started` | Code review in progress |
| Done | `completed` | Completed and merged |
| Canceled | `canceled` | Will not be implemented |

## Branch Naming Convention

Format: `username/TICKET-ID/short-slug`
Worktree: `username/TICKET-ID/worktree-name/short-slug`

Examples:
- `janusz/TEAM-133/fix-timeout`
- `janusz/TEAM-200/add-retry-mechanism`
- `janusz/TEAM-133/app-pos-7/fix-timeout` (worktree)

Rules:
- Username from existing branches (`git branch -a`)
- Ticket ID: `TEAM-NNN`
- Short slug: lowercase, hyphens, 3-4 words max

## Sentry Integration

Sentry URLs to scan for (replace `your-org` with your org slug):
- `https://sentry.io/organizations/your-org/issues/ISSUE-ID`
- `https://your-org.sentry.io/issues/ISSUE-ID`

Extract issue ID and use `mcp__sentry__get_issue_details` to fetch.
