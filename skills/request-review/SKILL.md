---
name: Dev10x:request-review
description: >
  Request PR review — assigns GitHub reviewers and posts Slack
  notification in one command. Delegates to Dev10x:gh-pr-request-review
  and Dev10x:slack-review-request.
  TRIGGER when: PR is ready for review and needs both GitHub reviewer
  assignment and Slack notification.
  DO NOT TRIGGER when: PR is draft/WIP, or only need GitHub assignment
  without Slack (use Dev10x:gh-pr-request-review directly).
user-invocable: true
invocation-name: Dev10x:request-review
allowed-tools:
  - Bash(${CLAUDE_PLUGIN_ROOT}/skills/gh-context/scripts/:*)
  - Skill(Dev10x:gh-pr-request-review)
  - Skill(Dev10x:slack-review-request)
  - Bash(gh pr view:*)
  - Bash(gh pr comment:*)
---

## Orchestration

This skill follows `references/task-orchestration.md` patterns.

**REQUIRED: Create a task at invocation.** Execute at startup:

1. `TaskCreate(subject="Request PR review", activeForm="Requesting review")`

Mark completed when done: `TaskUpdate(taskId, status="completed")`

**Auto-advance:** Complete each step, immediately start the next.

## Flow

### Step 1: Detect PR context

Use the `Dev10x:gh-context` script to detect PR number and repo:

```bash
${CLAUDE_PLUGIN_ROOT}/skills/gh-context/scripts/gh-pr-detect.sh "$ARG"
```

Parse `PR_NUMBER`, `REPO`, `PR_URL` from KEY=VALUE stdout.
Pass `$ARG` as the skill argument (PR URL, bare number, or empty).

If detection fails, report the error and stop.

### Step 1.5: Approval state precheck (GH-993)

Before pinging reviewers, check whether the PR is already
approved on its current HEAD:

```bash
gh pr view {PR_NUMBER} --repo {REPO} \
  --json reviewDecision,reviews,headRefOid
```

Decision logic:

- `reviewDecision == "APPROVED"` and the latest review's
  `commit.oid` matches `headRefOid` → PR is approved on the
  current HEAD. **REQUIRED: Call `AskUserQuestion`** (do NOT
  use plain text):
  - **Skip — merge instead (Recommended)** — short-circuit
    review request and offer to invoke `Dev10x:gh-pr-merge`
  - **Force request anyway** — proceed to Step 2 with all
    reviewers (e.g., user wants additional eyes)
  - **Cancel** — do nothing
- `reviewDecision == "APPROVED"` but newer commits have landed
  since the latest approval → approval is stale; proceed
  normally to Step 2 (re-review needed)
- `reviewDecision == "CHANGES_REQUESTED"` or `null` → proceed
  normally to Step 2

Skip this precheck when invoked with `--force` or when the
caller is `Dev10x:gh-pr-monitor` Phase 3 with explicit
`bypass_approval_check: true` (re-review request after fixups
where the monitor has already validated state).

### Step 2: Assign GitHub reviewers

Delegate to the GitHub reviewer assignment skill:

```
Skill("Dev10x:gh-pr-request-review", args="--pr {PR_NUMBER} --repo {REPO}")
```

This skill reads `~/.claude/memory/Dev10x/github-reviewers-config.yaml`,
resolves reviewers, and assigns them via GitHub API. It may skip
if the project is configured with `skip: true`.

Capture the outcome (assigned / skipped / error) for the summary.

### Step 3: Post Slack review notification

Delegate to the Slack notification skill:

```
Skill("Dev10x:slack-review-request", args="--pr {PR_NUMBER} --repo {REPO}")
```

This skill reads `~/.claude/memory/Dev10x/slack-config-code-review-requests.yaml`,
formats the message, asks for user confirmation, and posts to Slack.
It may skip if the project is configured with `skip: true`.

Capture the outcome (posted / skipped / error) for the summary.

### Step 3.5: Post PR comment (optional)

Post a review request comment on the PR mentioning assigned reviewers:

```bash
gh pr comment {PR_NUMBER} --repo {REPO} --body "Ready for review @reviewer1 @reviewer2"
```

Skip this step if:
- No reviewers were assigned (Step 2 skipped or errored)
- Project config sets `pr_comment: false`

### Step 4: Report summary

Report the combined result:

```
Review request for PR #{PR_NUMBER}:
- GitHub reviewers: {assigned / skipped / error}
- PR comment: {posted / skipped}
- Slack notification: {posted / skipped / error}
```

## Notes

- Steps 2 and 3 are independent — if one skips, the other still runs
- Both skipping is valid (project may be configured to skip both)
- Each sub-skill uses its own config file — no combined config needed
- This skill is invoked by `Dev10x:gh-pr-monitor` Phase 3 and
  directly by users via `/Dev10x:request-review`

## See Also

- `Dev10x:gh-pr-request-review` — GitHub reviewer assignment
- `Dev10x:slack-review-request` — Slack notification
- `Dev10x:gh-pr-monitor` — calls this skill in Phase 3
