---
name: dev10x:request-review
description: >
  Request PR review — assigns GitHub reviewers and posts the team's
  chat notification (Slack, Google Chat, or both) in one command.
  Delegates to dev10x:gh-pr-request-review, dev10x:slack-review-request
  and dev10x:gchat-review-request.
  TRIGGER when: PR is ready for review and needs both GitHub reviewer
  assignment and a chat notification.
  DO NOT TRIGGER when: PR is draft/WIP, or only need GitHub assignment
  without a notification (use dev10x:gh-pr-request-review directly).
user-invocable: true
invocation-name: dev10x:request-review
allowed-tools:
  - Read
  - AskUserQuestion
  - mcp__plugin_dev10x_cli__pr_detect
  - mcp__plugin_dev10x_cli__pr_get
  - mcp__plugin_dev10x_cli__pr_issue_comment
  - mcp__plugin_dev10x_cli__ci_check_status
  - mcp__plugin_dev10x_cli__unresolved_threads
  - mcp__plugin_dev10x_cli__bot_review_status
  - mcp__plugin_dev10x_cli__review_readiness_audit
  - Skill(dev10x:gh-pr-request-review)
  - Skill(dev10x:slack-review-request)
  - Skill(dev10x:gchat-review-request)
---

## Orchestration

This skill follows `references/task-orchestration.md` patterns.

**REQUIRED: Create a task at invocation.** Execute at startup:

1. `TaskCreate(subject="Request PR review", activeForm="Requesting review")`

Mark completed when done: `TaskUpdate(taskId, status="completed")`

**Auto-advance:** Complete each step, immediately start the next — no checkpoints the resolver did not ask for.

## Flow

Arguments: PR URL or number, `--repo`, `--force`, `--unattended`,
`--audit`.

**Audit mode (`--audit`, GH-1834):** skip Steps 1–4. Call
`mcp__plugin_dev10x_cli__review_readiness_audit(repo="{REPO}")` (omit
`repo` for the current one), print one line per PR —
`#N verdict — problem detail (since)` — grouped `SENT-NOT-READY`
first, then `WENT-RED-AFTER`, then `UNKNOWN`, then the counts — and,
when `more_open_prs` is true, that only `scanned` PRs were read. Write
nothing. Verdict meanings: `references/review-readiness.md` § Audit.

### Step 1: Detect PR context

Use the MCP tool to detect PR number and repo:

```
mcp__plugin_dev10x_cli__pr_detect(arg="$ARG")
```

Pass `$ARG` (PR URL, bare number, or empty) and parse `PR_NUMBER`,
`REPO`, `PR_URL`. If detection fails, report the error and stop.

### Step 1.5: Approval state precheck (GH-993, GH-128)

Check whether a **human** already approved the current HEAD. Call
`mcp__plugin_dev10x_cli__pr_get(number={PR_NUMBER}, repo="{REPO}")`
and read `reviewDecision`, `reviews`, `headRefOid` and `isDraft`
(GH-917 — never the hook-blocked raw `gh pr view`). Step 1.6 reuses
`isDraft`.

**Filter bot approvals first (GH-128):** drop reviews whose
`author.login` ends with `[bot]` or whose `author.type == "Bot"` — a
bot approval never satisfies human review. Then:

- A HUMAN review with `state == "APPROVED"` and `commit.oid`
  matching `headRefOid` → PR is human-approved on the current
  HEAD. **REQUIRED: Call `AskUserQuestion`** (do NOT use plain
  text):
  - **Skip — merge instead (Recommended)** — short-circuit
    review request and offer to invoke `dev10x:gh-pr-merge`
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

Skip this precheck on `--force` or when `dev10x:gh-pr-monitor` Phase
3 passes `bypass_approval_check: true` (re-review after fixups).

### Step 1.6: Readiness check (GH-1834)

Run the four conditions in
[`references/review-readiness.md`](../../references/review-readiness.md)
— draft, CI, unresolved threads, bots at head. A draft fails like the
rest; never mark it ready here. `--force` does not skip this step.

When any condition fails or cannot be read:

- **Unattended** (defined in that file — `--unattended`, or an
  orchestrator's `Skill()` call with an active task list): refuse —
  stop before Step 2, report each reason, assign no one, post nothing.
- **Attended**: **REQUIRED: Call `AskUserQuestion`** (do NOT use plain
  text). Question: `"PR #{PR_NUMBER} is not ready for review:
  {reasons}. Request review anyway?"`, header `Readiness`. Options:
  - **Stop — fix it first (Recommended)** — end here; report the
    reasons. Nothing is assigned or posted.
  - **Request review anyway** — continue to Step 2; Step 3.5 and the
    Step 4 summary carry the reasons.

### Step 2: Assign GitHub reviewers

Delegate; `--readiness-checked` says Step 1.6 already ran. Pass
`--unattended` only when this run is unattended — without it the
sibling treats this call as attended:

```
Skill(skill="dev10x:gh-pr-request-review", args="--pr {PR_NUMBER} --repo {REPO} --readiness-checked [--unattended]")
```

It resolves reviewers from `<Dev10x config>/github-reviewers-config.yaml`
and may skip on `skip: true`. Capture assigned / skipped / error /
stopped. **Stopped** — its output ends with `Readiness: stopped —
{reasons}` — ends the run: skip Steps 3 and 3.5; Step 4 prints it.

### Step 3: Post the review notification

The transport is whichever one this team uses — Slack, Google Chat, or
both — resolved from config, never assumed (GH-1308).

**Resolve the transports.** `Read` each per-repo config and check
whether its `projects` map names the repo's short name (the part after
the `/` in `{REPO}`):

| Transport | Config file | Delegate to |
|-----------|-------------|-------------|
| Slack | `~/.config/Dev10x/slack-config-code-review-requests.yaml` | `dev10x:slack-review-request` |
| Google Chat | `~/.config/Dev10x/gchat-config-code-review-requests.yaml` | `dev10x:gchat-review-request` |

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
Skill("dev10x:slack-review-request", args="--pr {PR_NUMBER} --repo {REPO}")
Skill("dev10x:gchat-review-request", args="--pr {PR_NUMBER} --repo {REPO}")
```

Each skill formats, confirms and posts, or skips on `skip: true`.
Capture posted / skipped / error per transport, naming the one used.

### Step 3.5: Post PR comment (optional)

Mention the assigned reviewers. After "Request review anyway" in Step
1.6, the body names the reasons instead of claiming readiness:

```
mcp__plugin_dev10x_cli__pr_issue_comment(pr_number={PR_NUMBER}, repo="{REPO}",
    body="Ready for review @reviewer1 @reviewer2")
# override: body="Review requested before ready ({reasons}) @reviewer1"
```

Skip this step if:
- No reviewers were assigned (Step 2 skipped or errored)
- Project config sets `pr_comment: false`

### Step 4: Report summary

Report the combined result:

```
Review request for PR #{PR_NUMBER}:
- Readiness: {ready / not ready — requested anyway: reasons / stopped — reasons}
- GitHub reviewers: {assigned / skipped / error}
- PR comment: {posted / skipped}
- {Slack | Google Chat} notification: {posted / skipped / error}
```

List one line per transport that ran — never one the config omits.

## Notes

- A Step 1.6 refusal or a Step 2 stop ends the run. Otherwise Steps 2
  and 3 are independent: each may skip on its own config file.
- Callers: `dev10x:gh-pr-monitor` Phase 3 and `/dev10x:request-review`.
