---
name: Dev10x:slack-review-request
description: >
  Post a Slack review request for a PR using per-project config
  (channel, mentions). Reads configuration from userspace YAML.
  TRIGGER when: PR needs a Slack review notification posted to the
  team channel.
  DO NOT TRIGGER when: Slack not configured, or using the combined
  Dev10x:request-review skill (which delegates here automatically).
user-invocable: true
invocation-name: Dev10x:slack-review-request
allowed-tools:
  - Bash(${CLAUDE_PLUGIN_ROOT}/skills/slack-review-request/scripts/:*)
---

# Slack Review Request

## Orchestration

This skill follows `references/task-orchestration.md` patterns.
Create a task at invocation, mark completed when done:

**REQUIRED: Create a task at invocation.** Execute at startup:

1. `TaskCreate(subject="Post Slack review request", activeForm="Posting review request")`

Mark completed when done: `TaskUpdate(taskId, status="completed")`

Post a review notification to the project's configured Slack channel
with appropriate team and user mentions.

## Config

Configuration lives in `~/.claude/memory/Dev10x/slack-config-code-review-requests.yaml`:

```yaml
default_action: ask  # "skip" or "ask" for unconfigured projects

projects:
  my-app:
    channel: C0EXAMPLE01    # Slack channel ID
    mentions:               # resolved via slack-config.yaml
      - "@backend-team"     # user group → <!subteam^ID>
      - "@alice"            # user → <@SLACK_ID>

  internal-tools:
    skip: true              # no Slack notification
```

Mentions are resolved against `~/.claude/memory/Dev10x/slack-config.yaml`
`user_groups` and `users` mappings.

### Per-Project Actions

- **Configured**: Use `channel` and `mentions` from config; fetch PR
  details; format message with JTBD if present; ask user for confirmation.
- **`skip: true`**: Report "Slack notification skipped" and done.
- **Unconfigured** (matches `default_action: ask`): Ask user for
  channel and mentions interactively. If user provides them, proceed;
  otherwise done.
- **Unconfigured** (matches `default_action: skip`): Skip silently.

## Flow

### Step 0: Approval state precheck (GH-993)

Before posting a Slack ping, verify the PR is not already approved
on its current HEAD. Re-pinging reviewers on an approved PR is
noise — the human supervisor's next action is merge, not another
review pass.

1. Fetch review state:
   ```bash
   gh pr view {pr_number} --repo {repo} \
     --json reviewDecision,reviews,headRefOid
   ```
2. **If `reviewDecision == "APPROVED"`** and the latest review's
   `commit.oid` matches `headRefOid`: skip the Slack notification.
   Report "Slack notification skipped — PR already approved on
   current HEAD" and stop.
3. **Otherwise**: proceed to Step 1.

Skip this precheck when invoked with `--force` flag or when the
caller passes `bypass_approval_check: true` (e.g., re-review
notifications composed by `Dev10x:gh-pr-monitor` Phase 2.7 after
fixups, where the caller has already validated state).

### Step 1: Prepare

**REQUIRED:** Run the `prepare` subcommand to resolve project config
and format the Slack message. Do NOT inline `yq` reads of
`slack-config.yaml`, manual mention resolution, or hand-built message
strings — the script handles user-group → `<!subteam^ID>` resolution,
user → `<@SLACK_ID>` resolution, JTBD extraction from the PR body,
and channel lookup in one call. Inlining bypasses these and produces
malformed mentions.

```bash
${CLAUDE_PLUGIN_ROOT}/skills/slack-review-request/scripts/slack-review-request.py \
  prepare --pr {pr_number} --repo {repo}
```

Output is JSON with keys:
- `skip`: boolean — project is configured to skip
- `ask`: boolean — no config found; user input required
- `channel`: Slack channel ID (or null)
- `message`: formatted Slack message (or null)
- `reason`: short explanation if skip or ask

### Step 2: Handle Result

Check the `prepare` output:

- **If `skip=true`**: Report "Slack notification skipped for
  {repo}" and done. Do not ask user.

- **If `ask=true`**: Use `AskUserQuestion` to ask for:
  - Slack channel ID (required)
  - Mentions as space-separated @names (optional)

  If user provides a channel, resolve mentions and update config
  (optional — may save to YAML for future use). Then proceed to
  Step 3 with resolved config.

  If user declines, done.

- **Otherwise**: Continue to Step 3 with resolved config.

### Step 3: Confirm with User

Use `AskUserQuestion` to show:
- **Title**: "Review Slack message before posting"
- **Content**: the formatted message (from Step 1 output)
- **Options**: "Post to Slack" / "Skip"

If user chooses "Skip", done. If "Post to Slack", proceed to Step 4.

### Step 4: Send

Delegate to `Skill(Dev10x:slack)` for posting. Write the message to
a temporary file and pass it:

`Skill(skill="Dev10x:slack", args="--channel {channel} --message-file {temp_file}")`

**NEVER call `slack-review-request.py send` directly** — delegate to
the slack skill to honor global Slack posting rules. The script is
an internal fallback only.

Report success: channel ID, thread timestamp (if available).

## Integration

This skill is invoked by:
- `Dev10x:request-review` — combined review request orchestrator
- `Dev10x:gh-pr-monitor` Phase 2.7 (re-review notification)

It handles only Slack posting — no GitHub API calls.

For re-review notifications (Phase 2.7 in `Dev10x:gh-pr-monitor`), the
calling skill composes a custom message (e.g., "@reviewer please take
another look") and invokes this skill with `--message` directly,
skipping the `prepare` step.

## Message Format

Messages include:
- **Mentions** (if any): prepended to the first line before "Please review"
- **Review link**: formatted as `<url|my-app#42>`
- **PR title**: on next line
- **JTBD** (if present in PR body): extracted from first `**When**`
  paragraph and formatted as a blockquote

Example output:

```
<!subteam^S0EXAMPLE> <@U0ALICE> Please review <https://github.com/org/my-app/pull/42|my-app#42>
Fix payment routing
> *When* a customer uses a new card, *wants to* bypass 3D Secure, *so*
> *can* complete checkout faster.
```

## Usage

### Direct invocation (user-facing)

```
/Dev10x:slack-review-request                     # uses current branch PR
/Dev10x:slack-review-request --manual            # force config review
```

### Programmatic (from other skills)

```
Skill("Dev10x:slack-review-request",
  args={
    "pr_number": 42,
    "repo": "org/my-app",
    "ask_if_unconfigured": true,
  }
)
```

## See Also

- `Dev10x:gh-pr-monitor` — calls this skill in Phase 3 (review request workflow)
- `slack-config.yaml` — mention resolution mappings
