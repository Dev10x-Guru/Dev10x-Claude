---
name: Dev10x:gh-context
invocation-name: Dev10x:gh-context
description: >
  Detect PR context (number, repo, URL, branch) from a URL, PR number,
  or current branch — so skills like Dev10x:gh-pr-monitor always get the
  correct target PR even in multi-worktree setups.
  TRIGGER when: resolving PR context from URL, number, or branch for
  downstream skills.
  DO NOT TRIGGER when: PR context is already known and passed explicitly.
user-invocable: false
allowed-tools:
  - mcp__plugin_Dev10x_cli__*
  - Bash(${CLAUDE_PLUGIN_ROOT}/skills/gh-context/scripts/:*)
  - Bash(/tmp/Dev10x/bin/mktmp.sh:*)
  - Bash(gh pr view:*)
  - Bash(gh repo view:*)
  - Bash(gh api:*)
---

# Dev10x:gh-context — GitHub CLI helpers

Shell script wrappers for common `gh` operations. **These operations are
now available as first-class MCP tools** via the `Dev10x-gh` MCP server.
Both paths (shell scripts and MCP tools) coexist during migration.

## Using MCP Tools (Preferred)

Instead of wrapping shell scripts via Bash, call the MCP tools directly for
structured JSON responses and input validation:

| Operation | MCP Tool | Replaces |
|-----------|----------|----------|
| Detect tracker type | `mcp__plugin_Dev10x_cli__detect_tracker(ticket_id)` | `detect-tracker.sh` |
| Detect PR context | `mcp__plugin_Dev10x_cli__pr_detect(arg)` | `gh-pr-detect.sh` |
| Get issue details | `mcp__plugin_Dev10x_cli__issue_get(number, repo?)` | `gh-issue-get.sh` |
| Get issue comments | `mcp__plugin_Dev10x_cli__issue_comments(number, repo?)` | `gh-issue-comments.sh` |
| Manage PR comments | `mcp__plugin_Dev10x_cli__pr_comments(action, ...)` | Inline `gh api` calls |
| Request review | `mcp__plugin_Dev10x_cli__request_review(pr_number, reviewers, ...)` | Inline `gh api` calls |

**Example usage in a skill:**

```python
# Old way (via Bash script):
result = await run_script("skills/gh-context/scripts/detect-tracker.sh", "TEAM-133")
tracker = parse_key_value_output(result.stdout)["TRACKER"]

# New way (via MCP tool):
result = await mcp_tool_detect_tracker(ticket_id="TEAM-133")
tracker = result["tracker"]
```

New skills and skill updates should prefer MCP tools for consistency,
input validation, and structured responses.

## Orchestration

This skill follows `references/task-orchestration.md` patterns.
Create a task at invocation, mark completed when done:

**REQUIRED: Create a task at invocation.** Execute at startup:

1. `TaskCreate(subject="Detect PR/issue context", activeForm="Detecting context")`

Mark completed when done: `TaskUpdate(taskId, status="completed")`

## Critical Rule: Never derive BRANCH from local git

**WRONG** — `git branch --show-current` returns the CURRENT WORKTREE's
branch, which is a DIFFERENT PR when using multiple worktrees:

```bash
# ❌ Will give the wrong branch in a multi-worktree setup
BRANCH=$(git branch --show-current)
```

**RIGHT** — always fetch the PR's branch from GitHub:

```bash
# ✅ Always correct regardless of which worktree you're in
BRANCH=$(gh pr view "$PR_NUMBER" --repo "$REPO" --json headRefName -q '.headRefName')
```

## Legacy Shell Scripts (Fallback)

The shell scripts below are maintained for backward compatibility.
**New skills should use the MCP tools above instead.** Use scripts
only when the MCP server is unavailable or inside shell contexts
where MCP tool calls are not possible.

### gh-pr-detect.sh

Detects PR number, repo, URL, and branch. Accepts a GitHub PR URL, a
bare PR number, or nothing (detects from current branch).

```bash
${CLAUDE_PLUGIN_ROOT}/skills/gh-context/scripts/gh-pr-detect.sh "$ARG"
```

| Input | Behaviour |
|---|---|
| `https://github.com/org/repo/pull/123` | Parses number and repo from URL |
| `123` | Uses number; detects repo from cwd via `gh repo view` |
| *(none)* | Detects PR number from current branch via `gh pr view` |

Output (KEY=VALUE lines, one per line):

```
PR_NUMBER=123
REPO=your-org/your-repo
PR_URL=https://github.com/your-org/your-repo/pull/123
BRANCH=user/TICKET-123/feature-description
```

Exits non-zero with an error message to stderr if detection fails.

### How to consume the output

Run the script directly. Claude parses the KEY=VALUE stdout and uses
the values in subsequent Bash calls. **Do not** use `source <(...)` —
it triggers process substitution permission prompts and breaks
allow-rule prefix matching.

```bash
# ✅ Run directly — script path is first token, matches allow rules
${CLAUDE_PLUGIN_ROOT}/skills/gh-context/scripts/gh-pr-detect.sh "$ARG"
# Parse PR_NUMBER, REPO, PR_URL, BRANCH from stdout

# ❌ NEVER use source <() — breaks allow rules, triggers permission prompt
source <(${CLAUDE_PLUGIN_ROOT}/skills/gh-context/scripts/gh-pr-detect.sh "$ARG")
```

When a single Bash call needs the variables (e.g., chaining with
another command), use the temp-file pattern:

```bash
ENVFILE=$(/tmp/Dev10x/bin/mktmp.sh git pr-detect .env)
${CLAUDE_PLUGIN_ROOT}/skills/gh-context/scripts/gh-pr-detect.sh "$ARG" > "$ENVFILE"
source "$ENVFILE"
echo "PR #$PR_NUMBER"
```

This keeps the script path as the first token so allow rules match.

### detect-tracker.sh

Detects issue tracker type from a ticket ID using prefix heuristics
and GitHub autolink references.

```bash
${CLAUDE_PLUGIN_ROOT}/skills/gh-context/scripts/detect-tracker.sh TICKET_ID
```

Detection cascade:

| Step | Condition | Result |
|---|---|---|
| 1 | `GH-` prefix | `TRACKER=github`, builds `FIXES_URL` from current repo |
| 2 | Prefix matches a GitHub autolink with `linear.app` URL | `TRACKER=linear` |
| 3 | Prefix matches a GitHub autolink with `atlassian.net` URL | `TRACKER=jira` |
| 4 | `LINEAR_API_KEY` set and Linear API confirms the ticket exists | `TRACKER=linear` |
| 5 | No match | `TRACKER=unknown`, `FIXES_URL` empty |

Output (KEY=VALUE lines, same convention as `gh-pr-detect.sh`):

```
TRACKER=github
TICKET_ID=GH-15
TICKET_NUMBER=15
FIXES_URL=https://github.com/your-org/your-repo/issues/15
```

Consume the output the same way as `gh-pr-detect.sh` — run directly
and parse KEY=VALUE stdout. Do not use `source <(...)`.

### gh-issue-get.sh

Fetches a GitHub issue as JSON with full details.

```bash
${CLAUDE_PLUGIN_ROOT}/skills/gh-context/scripts/gh-issue-get.sh NUMBER [REPO]
```

| Param | Required | Default |
|---|---|---|
| `NUMBER` | yes | — |
| `REPO` | no | current repo via `gh repo view` |

Output: JSON object with fields `number`, `title`, `body`, `state`,
`labels`, `assignees`, `comments`.

### gh-issue-comments.sh

Returns comments on a GitHub issue as a JSON array.

```bash
${CLAUDE_PLUGIN_ROOT}/skills/gh-context/scripts/gh-issue-comments.sh NUMBER [REPO]
```

| Param | Required | Default |
|---|---|---|
| `NUMBER` | yes | — |
| `REPO` | no | current repo via `gh repo view` |

Output: JSON array of comment objects with `author`, `body`,
`createdAt`.
