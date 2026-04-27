# Create Pull Request for Ticket (Instructions)

## Overview

This skill automates the creation of a GitHub pull request for the
current branch with issue tracker integration (GitHub Issues, Linear,
or JIRA). It handles pushing the branch, creating the PR with
appropriate title and body, adding checklist comments, and opening the
PR in your browser.

## Orchestration

This skill follows `references/task-orchestration.md` patterns
(Tier: Standard).

**Auto-advance:** Complete each step and immediately start the next.
Never pause between steps to ask "should I continue?".

**REQUIRED: Create tasks before ANY work.** Execute these
`TaskCreate` calls at startup:

1. `TaskCreate(subject="Verify git state", description="Check branch, commits, base branch", activeForm="Verifying git state")`
2. `TaskCreate(subject="Generate PR body", description="Source JTBD, build commit list, compose body", activeForm="Generating PR body")`
3. `TaskCreate(subject="Run pre-PR checks", description="Run ruff, black, mypy, pytest if Python", activeForm="Running pre-PR checks")`
4. `TaskCreate(subject="Push and create PR", description="Push branch, create draft PR on GitHub", activeForm="Creating PR")`

Set sequential dependencies: generate blocked by verify, checks
blocked by generate, push blocked by checks.

**Task creation in unattended mode:** All 4 startup tasks MUST
be created regardless of mode. When a task's work is auto-skipped
(e.g., "Run pre-PR checks" on a non-Python project), still create
the task via `TaskCreate` and immediately mark it `completed`
with description "Auto-skipped: non-Python project" (or the
appropriate reason). This preserves supervisor visibility into
the full workflow.

**Unattended mode:** When this skill is invoked by an
orchestrating skill (e.g., `Dev10x:work-on`, `Dev10x:git-promote`,
`test:fix-flaky`) and the orchestrator has already approved the
work plan, all interactive decision gates are bypassed:
- PR preview gate → skip (orchestrator already approved the plan)
- Title → auto-generate from commit(s) (single-commit: use
  title; multi-commit: derive from JTBD "so I can" clause)
- Job Story → auto-generate inline for simple changes; reuse
  session context for complex ones (skip full `Dev10x:jtbd` skill)
- Pre-PR checks → still run (safety gate, not interactive)
- Browser open → skip
- Next steps → return control to orchestrator immediately

**Task reduction in unattended mode:** Reduce `TaskCreate` calls
to at most 1 task (`"Create PR"`) instead of decomposing into
the full 4-task sequence. The orchestrator already tracks
high-level progress.

Detection: unattended mode activates when **both** conditions
are met:
1. The skill is invoked via `Skill(Dev10x:gh-pr-create)` (not
   directly by the user via `/Dev10x:gh-pr-create`)
2. The caller is executing a plan step with an active task
   list (i.e., an orchestrating skill like `work-on`)

When either condition is absent, default to **attended mode**
with all interactive gates. When in doubt, default to attended.

**Decision gates (attended mode) — REQUIRED: Call
`AskUserQuestion`** (do NOT use plain text) at each of these
points. In unattended mode, these gates are skipped:

- **PR preview approval (MANDATORY in attended mode):**
  **REQUIRED: Call `AskUserQuestion`** (do NOT use plain text,
  call spec: [ask-pr-preview.md](./tool-calls/ask-pr-preview.md))
  after generating the PR body. This blocks execution until the
  user responds. **DO NOT skip this gate in attended mode —
  proceeding directly to `create_pr` without user approval is
  a compliance violation.**
  Options:
  - Create PR (Recommended) — Push branch and create draft PR as shown
  - Edit title/body — I want to revise before creating
  - Abort — Cancel PR creation

## Scripts

All multi-line commands live in `${CLAUDE_PLUGIN_ROOT}/skills/gh-pr-create/scripts/`:

| Script | Purpose |
|--------|---------|
| `detect-base-branch.sh` | Auto-detect base branch (develop → main fallback) |
| `verify-state.sh` | Validate branch, commits, and base branch ancestry |
| `generate-commit-list.sh` | Generate linked commit list for PR body |
| `pre-pr-checks.sh` | Run ruff, black, mypy, pytest before push |
| `create-pr.sh` | Push branch, create draft PR with body including checklist |
| `post-summary-comment.sh` | _(deprecated — checklist is now in PR body)_ |

## Prerequisites Check

**IMPORTANT:** Before executing this workflow, verify required tools:

1. Check if `gh` CLI is installed and authenticated:
   ```bash
   gh auth status
   ```
   If not authenticated, inform the user to run `gh auth login`

2. Verify we're in a git repository with a remote:
   ```bash
   git remote get-url origin
   ```

3. **Worktree check** — `verify-state.sh` reads git state from the current working
   directory. If the session is rooted in the main repo but the branch lives in a
   worktree, run it with `GIT_DIR` pointing to the worktree — BUT that env var
   prefix breaks `Bash(~/.claude/skills:*)` allow-rule matching. Instead, pass
   the worktree path as an argument when the script supports it, or use a subshell:
   ```bash
   # When invoking from main repo for a branch checked out in a worktree:
   # ❌  GIT_DIR=... verify-state.sh   (env prefix breaks allow rules)
   # ✅  Run the script from within the worktree context
   # Note: env var prefix is still subject to permission friction. The
   # cleanest alternative is to invoke pr:create while CWD is inside the
   # worktree, not the main repo.
   ```

## When to Use This Skill

Use this skill when:
- Ready to create a PR for your current feature branch
- Have committed changes that need review
- Want to link a PR to an issue tracker ticket
- Need to create a draft PR for early feedback
- **Updating an existing PR** (pass PR number or URL as argument)

### Update Existing PR Mode

When a PR number or URL is provided as argument, switch to "update" mode:
- Skip Steps 1-3 (branch check, ticket extraction) — use the existing PR's info
- Steps 4-5 still apply (source JTBD, generate body)
- Skip Step 6 (pre-PR checks) and Step 7 (push) — PR already exists
- Step 8 becomes "Update PR" using `gh pr edit`
- Steps 8-9 still apply (re-mark N/A checklist items, open browser, display summary)

## Workflow

### Step 1: Verify Current State and Extract Ticket

**Primary (MCP tool):** Call
`mcp__plugin_Dev10x_cli__verify_pr_state` to validate branch
state. Parse `BRANCH_NAME` and `ISSUE` from the response.

**MCP server unavailable.** If the tool is listed as "no longer
available" in system-reminders, STOP and ask the user to reconnect
via `/mcp` or a session restart. Do NOT fall back to the wrapper
script or use `DEV10X_SKIP_CMD_VALIDATION` — see
`references/mcp-unavailable-escape-hatch.md`.

**Fallback (script):** Only when the MCP server is healthy but the
tool call errored for another reason:

```bash
${CLAUDE_PLUGIN_ROOT}/skills/gh-pr-create/scripts/verify-state.sh
```

This validates:
- Not on develop/main/master
- No uncommitted changes
- Has commits ahead of develop
- Branch does not include master-only commits (would cause PR to target master)
- No merge conflicts with base branch (requires Git 2.38+; suggests rebase if conflicts found)

On success, outputs `BRANCH_NAME=<name>` and `ISSUE=<ticket-id>`.

**Verify base branch from live git data** — do not trust memory alone:
```bash
git symbolic-ref refs/remotes/origin/HEAD
```
Use whatever branch this returns as the PR base.

### Step 2: Generate PR Title

**Single-commit PRs:** Use the commit title directly:

```bash
TITLE=$(git log -1 --format=%s)
```

**Multi-commit PRs:** The most recent commit title often describes the
last incremental step, not the overall change. Instead:

1. List all commit titles in the branch:
   ```bash
   git log origin/$BASE_BRANCH..HEAD --reverse --format=%s
   ```
2. Check if the JTBD "so I can" clause (from Step 3) suggests a
   better title — transform it to imperative form with the ticket's
   gitmoji prefix (e.g., "so I can reuse outbox for SMS" →
   `♻️ PROJ-551 Enable outbox reuse for SMS messaging`).
3. If no JTBD is available yet, select the commit title that best
   describes the **overall outcome** of the PR, not an intermediate
   step.
4. Present the candidate title to the user for approval.

**Guiding Principle:** The PR title should describe the user-facing
outcome, not the implementation detail.

### Step 3: Source or Generate Job Story

The PR body must start with a JTBD Job Story. Look for an existing one
before generating a new one.

**Step 3a: Detect issue tracker**

Call the MCP tool with the ISSUE extracted from the branch name:

`mcp__plugin_Dev10x_cli__detect_tracker(ticket_id="$ISSUE")`

Parse `tracker` and `fixes_url` from the response.

**Step 3b: Search for existing Job Story**

Dispatch based on TRACKER:

| TRACKER | How to search |
|---------|--------------|
| `github` | `${CLAUDE_PLUGIN_ROOT}/skills/gh-context/scripts/gh-issue-get.sh` for body, `${CLAUDE_PLUGIN_ROOT}/skills/gh-context/scripts/gh-issue-comments.sh` for comments |
| `linear` | Linear MCP tools for description and comments |
| `jira` | JIRA API for description |
| `unknown` | Skip ticket search, rely on commit messages |

Search each source for the `**When**` / `**I want to**` / `**so I can**`
pattern.

**Step 3c: Check commit messages (fallback)**

If no Job Story found in the ticket:

```bash
git log origin/$BASE_BRANCH..HEAD --format=%B
```

**Step 3d: Generate a new one**

If none found, generate a Job Story:

- **For simple/trivial fixes** (flaky tests, typos, single-line changes):
  generate the Job Story inline in `**When** / **I want to** / **so I can**`
  format without invoking the full `Dev10x:jtbd` skill.
- **For features, bug fixes, and multi-commit PRs**: follow the `Dev10x:jtbd`
  base skill workflow:
  1. Gather context (ticket, parent ticket, diff)
  2. Identify the situation (who, trigger, current pain)
  3. Draft using format: `**When** [situation], **I want to** [motivation], **so I can** [expected outcome].`
  4. Present draft and ask user: "Apply this Job Story to the PR? (y/edit/n)"

### Step 4: Generate PR Body

The PR body must be **compact** to minimize notification preview size.
It starts with the Job Story, followed by a commit list with links and
the issue tracker reference.

**Generate commit list (for preview before PR creation):**

`mcp__plugin_Dev10x_cli__generate_commit_list(pr_number="PLACEHOLDER")`

**NEVER call `generate-commit-list.sh` directly** — use the MCP tool
above. The script is an internal implementation detail.

**Body format (Job Story + separator + commit list + issue link + separator + checklist):**
```markdown
**When** [situation], **I want to** [motivation], **so I can** [expected outcome].

---

[`b3a015a8`](REPO_URL/pull/NUMBER/commits/FULL_HASH) ✨ PROJ-36 Enable feature
[`fec49998`](REPO_URL/pull/NUMBER/commits/FULL_HASH) ♻️ PROJ-36 Refactor module

Fixes: {fixes_url from detect_tracker MCP tool}

---

{.github/checklist.md contents with TICKET-ID substituted}
```

If FIXES_URL is empty (unknown tracker), omit the `Fixes:` line entirely.

### Step 5: Run Pre-PR Checks

```bash
${CLAUDE_PLUGIN_ROOT}/skills/gh-pr-create/scripts/pre-pr-checks.sh
```

Automatically skips if no Python files changed. Runs ruff, formatting,
mypy, and pytest. Exits on first failure.

**STOP on failure (REQUIRED):**

If `pre-pr-checks.sh` exits non-zero, or
`mcp__plugin_Dev10x_cli__pre_pr_checks` returns
`{"error": "..."}` or any non-success structure:

1. STOP the PR creation workflow immediately
2. Display the error output to the user
3. Suggest fix commands or delegate to the appropriate skill
   (`Skill(test)` for pytest failures, project lint runner for
   ruff/black, etc.)

Do NOT attempt to debug by running `uv run mypy`, `.venv/bin/mypy`,
`ruff check`, `black --check`, or any other lint/test tool directly
in the main session. The check failure is the signal to halt — not
to investigate. The agent must hand control back to the user (or to
a test/lint skill) instead of looping on raw tool invocations. This
applies whether the failure was reported by the script path or the
MCP tool path.

### Step 6: Push and Create Draft PR

```bash
${CLAUDE_PLUGIN_ROOT}/skills/gh-pr-create/scripts/create-pr.sh "$TITLE" "$JOB_STORY" "$ISSUE" "$FIXES_URL"
```

This script:
1. Pushes the branch with upstream tracking
2. Creates a draft PR targeting `develop` with plain commit list + checklist template
3. Gets the PR number
4. Updates the body with linked commits (using `generate-commit-list.sh`)
5. Outputs the PR number

### Step 7: Mark N/A Checklist Items in PR Body

Analyze `git diff origin/$BASE_BRANCH..HEAD` to determine which checklist items
don't apply to this PR, then update the PR body with strikethroughs:

**N/A detection heuristics:**
- No `migrations/` files in diff → strike migration items
- No new env var references → strike environment variable items
- No schema-breaking changes → strike breaking changes items

**Strike-through format:** Replace `- [ ] item text` with `- ~item text~`

**Update PR body:**
```bash
PR_NUMBER=$(gh pr view --json number -q .number)
gh pr edit "$PR_NUMBER" --body "$UPDATED_BODY"
```

### Step 8: Open PR in Browser

```bash
gh pr view --web
```

### Step 9: Display Summary

Show a success message with PR details:

```
✅ Pull Request Created

Title: 🐛 PROJ-123 Fix timeout handling
Branch: user/PROJ-123/fix-timeout
Status: Draft
Issue: {FIXES_URL}
PR URL: https://github.com/owner/repo/pull/456

Next steps:
- Review the PR in your browser
- Wait for CI checks to complete
- Mark as "Ready for review" when done
- Request reviewers if needed
```

## Important Notes

- **DO NOT use raw `git push` or `gh pr create` commands.**
  Always use `Skill(Dev10x:git)` for push and the MCP tool
  `mcp__plugin_Dev10x_cli__create_pr` (or the `create-pr.sh`
  script as fallback) for PR creation. Raw commands bypass
  protected branch checks and body formatting. Audit sessions
  GH-448 and GH-446 confirmed this regression pattern.
- Always create PRs as drafts initially
- **Base branch is auto-detected** — `detect-base-branch.sh` checks for
  `develop`/`development` first, falls back to `main`/`master`/`trunk`.
  Pass `--force` to `verify-state.sh` to override when a dev branch exists
  but you intentionally target a different base.
- Ensure branch is pushed before creating PR
- Handle existing PR case gracefully
- Link to issue tracker ticket in PR body (when FIXES_URL is available)
- **PR body starts with the Job Story** — sourced from ticket description,
  ticket comments, or generated fresh using the `Dev10x:jtbd` base skill.
- **PR body contains the checklist** — Job Story + separator + commit
  list + issue tracker link + separator + checklist.
- Open PR in browser for immediate review

## Integration with Other Skills

This skill is designed to be used standalone or as part of larger workflows:

- **ticket:work-on**: Could add an optional final step to create PR when work is done
- **Dev10x:git-promote**: Uses this skill for Push and Create PR
- **test:fix-flaky**: Uses this skill for Create PR
- **Standalone usage**: User manually invokes when ready to create PR
