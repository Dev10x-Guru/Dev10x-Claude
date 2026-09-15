---
name: Dev10x:request-review
description: >
  Request PR review — assigns GitHub reviewers and posts the team's
  chat notification (Slack, Google Chat, or both) in one command.
  Delegates to Dev10x:gh-pr-request-review, Dev10x:slack-review-request
  and Dev10x:gchat-review-request.
  TRIGGER when: PR is ready for review and needs both GitHub reviewer
  assignment and a chat notification.
  DO NOT TRIGGER when: PR is draft/WIP, or only need GitHub assignment
  without a notification (use Dev10x:gh-pr-request-review directly).
user-invocable: true
invocation-name: Dev10x:request-review
allowed-tools:
  - Read
  - AskUserQuestion
  - mcp__plugin_Dev10x_cli__pr_detect
  - mcp__plugin_Dev10x_cli__pr_get
  - mcp__plugin_Dev10x_cli__pr_issue_comment
  - Skill(Dev10x:gh-pr-request-review)
  - Skill(Dev10x:slack-review-request)
  - Skill(Dev10x:gchat-review-request)
---

## Orchestration

This skill follows `references/task-orchestration.md` patterns.

**REQUIRED: Create a task at invocation.** Execute at startup:

1. `TaskCreate(subject="Request PR review", activeForm="Requesting review")`

Mark completed when done: `TaskUpdate(taskId, status="completed")`

**Auto-advance:** Complete each step, immediately start the next — no checkpoints the resolver did not ask for.

## Flow

### Step 1: Detect PR context

Use the MCP tool to detect PR number and repo:

```
mcp__plugin_Dev10x_cli__pr_detect(arg="$ARG")
```

Parse `PR_NUMBER`, `REPO`, `PR_URL` from the returned dict.
Pass `$ARG` as the skill argument (PR URL, bare number, or empty).

If detection fails, report the error and stop.

### Step 1.5: Approval state precheck (GH-993, GH-128)

Before pinging reviewers, check whether the PR is already
approved on its current HEAD **by a human reviewer**. Bot
approvals (e.g., `claude[bot]`, `github-actions[bot]`) MUST
NOT short-circuit the human review request.

```
mcp__plugin_Dev10x_cli__pr_get(number={PR_NUMBER}, repo="{REPO}")
```

Read `reviewDecision`, `reviews`, and `headRefOid` from the
response — `pr_get` exposes all three (GH-917), so this precheck
never needs the hook-blocked raw `gh pr view`.

**Filter bot approvals first (GH-128).** Before matching reviews
against `headRefOid`, drop any review whose `author.login` ends
with `[bot]` (e.g., `claude[bot]`) or whose `author.type == "Bot"`.
Bot approvals do not satisfy the "human review" requirement.

Decision logic (operates on the human-filtered review list):

- A HUMAN review with `state == "APPROVED"` and `commit.oid`
  matching `headRefOid` → PR is human-approved on the current
  HEAD. **REQUIRED: Call `AskUserQuestion`** (do NOT use plain
  text):
  - **Skip — merge instead (Recommended)** — short-circuit
    review request and offer to invoke `Dev10x:gh-pr-merge`
  - **Force request anyway** — proceed to Step 2 with all
    reviewers (e.g., user wants additional eyes)
  - **Cancel** — do nothing
- HUMAN `APPROVED` reviews exist but newer commits landed since
  the latest approval → approval is stale; proceed normally to
  Step 2 (re-review needed)
- Only bot approvals match the current HEAD, or
  `reviewDecision == "CHANGES_REQUESTED"`, or no reviews → proceed
  normally to Step 2. When only bot approvals exist on the current
  HEAD, log "PR has only a bot approval — requesting human review"
  so the rationale is visible.

Skip this precheck when invoked with `--force` or when the
caller is `Dev10x:gh-pr-monitor` Phase 3 with explicit
`bypass_approval_check: true` (re-review request after fixups
where the monitor has already validated state).

### Step 2: Assign GitHub reviewers

Delegate to the GitHub reviewer assignment skill:

```
Skill("Dev10x:gh-pr-request-review", args="--pr {PR_NUMBER} --repo {REPO}")
```

This skill reads `<Dev10x config>/github-reviewers-config.yaml`,
resolves reviewers, and assigns them via GitHub API. It may skip
if the project is configured with `skip: true`.

Capture the outcome (assigned / skipped / error) for the summary.

### Step 3: Post the review notification

The transport is whichever one this team actually uses — Slack, Google
Chat, or both. Resolve it from config rather than assuming (GH-1308);
hardcoding Slack here left a Chat-only team with no supported way to
invoke this skill at all.

**Resolve the transports.** `Read` each per-repo config and check
whether its `projects` map names the repo's short name (the part after
the `/` in `{REPO}`):

| Transport | Config file | Delegate to |
|-----------|-------------|-------------|
| Slack | `~/.config/Dev10x/slack-config-code-review-requests.yaml` | `Dev10x:slack-review-request` |
| Google Chat | `~/.config/Dev10x/gchat-config-code-review-requests.yaml` | `Dev10x:gchat-review-request` |

A missing file counts as "does not name the repo". Then:

- **One names it** → delegate to that transport.
- **Both name it** → delegate to **both**, in the order above. Mirroring
  review requests into two places is a legitimate configuration, so this
  step must not assume exactly one.
- **Neither names it** → **REQUIRED: Call `AskUserQuestion`** (do NOT
  use plain text): "No chat transport is configured for {REPO}. Where
  should the review request go?" with options **Slack**, **Google
  Chat**, and **Skip the notification (Recommended)**. Delegate to the
  chosen skill, which will ask for the channel or space itself.

```
Skill("Dev10x:slack-review-request", args="--pr {PR_NUMBER} --repo {REPO}")
Skill("Dev10x:gchat-review-request", args="--pr {PR_NUMBER} --repo {REPO}")
```

Each skill resolves its own config, formats the message, confirms with
the user, and posts. Either may skip when its project entry sets
`skip: true`.

Capture the outcome per transport (posted / skipped / error) for the
summary — name the transport that was actually used.

### Step 3.5: Post PR comment (optional)

Post a review request comment on the PR mentioning assigned reviewers:

```
mcp__plugin_Dev10x_cli__pr_issue_comment(
    pr_number={PR_NUMBER},
    repo="{REPO}",
    body="Ready for review @reviewer1 @reviewer2",
)
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
- {Slack | Google Chat} notification: {posted / skipped / error}
```

List one line per transport that ran. A transport whose config does not
name the repo is not reported at all — it was never in play.

## Notes

- Steps 2 and 3 are independent — if one skips, the other still runs
- Both skipping is valid (project may be configured to skip both)
- Either transport may skip independently of the other — the same
  wording applies within Step 3
- Each sub-skill uses its own config file — no combined config needed
- This skill is invoked by `Dev10x:gh-pr-monitor` Phase 3 and
  directly by users via `/Dev10x:request-review`

## See Also

- `Dev10x:gh-pr-request-review` — GitHub reviewer assignment
- `Dev10x:slack-review-request` — Slack notification
- `Dev10x:gchat-review-request` — Google Chat notification
- `Dev10x:gh-pr-monitor` — calls this skill in Phase 3
