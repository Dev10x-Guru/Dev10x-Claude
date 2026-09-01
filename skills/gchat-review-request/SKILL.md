---
name: Dev10x:gchat-review-request
description: >
  Post a Google Chat review request for a PR using per-repo config
  (space, mentions). Mirrors Dev10x:slack-review-request. Standalone —
  not wired into Dev10x:request-review.
  TRIGGER when: a PR needs a Google Chat review notification.
  DO NOT TRIGGER when: Google Chat is not configured, or posting to Slack
  (use Dev10x:slack-review-request).
user-invocable: true
invocation-name: Dev10x:gchat-review-request
allowed-tools:
  - Bash(uvx dev10x skill notify gchat-review-prepare:*)
  - Bash(gh pr view:*)
  - AskUserQuestion
---

# Google Chat Review Request

## Orchestration

**REQUIRED: Create a task at invocation.** Execute at startup:

1. `TaskCreate(subject="Post Google Chat review request", activeForm="Posting review request")`

Mark completed when done: `TaskUpdate(taskId, status="completed")`

## Config

Per-repo config in `gchat-config-code-review-requests.yaml` (resolved via the
shared Dev10x config home):

```yaml
default_action: ask  # "skip" or "ask" for unconfigured repos
default_card: true   # cardsV2 panels for every repo (the default)
projects:
  my-app:
    space: tt-reviews      # alias from gchat-config.yaml
    mentions:
      - "@dev-team-fe"     # user group -> native group mention token
  plain-text-repo:
    space: tt-reviews
    card: false            # opt this repo out, back to plain text
  internal-tools:
    skip: true
```

Mentions resolve against `gchat-config.yaml` `user_groups` and `users`.

**Cards are the default.** A review request renders as a panel — PR title
as the card header, the Job Story as formatted text, and an *Open PR*
button — accompanied by a short text line carrying the mentions, because
a card cannot resolve them.

Two opt-outs remain, narrowest first: a per-repo `card: false`, and a
global `default_card: false`. Either restores the single plain-text
message; the per-repo key wins over the global one.

## Flow

### Step 0: Approval-state precheck

Skip the ping if the PR is already human-approved on its current HEAD (bot
approvals do not count). Mirror `Dev10x:slack-review-request` Step 0:

```bash
gh pr view {pr_number} --repo {repo} --json reviewDecision,reviews,headRefOid  # cli-friction: allow raw-gh-pr — review-state precheck
```

Drop reviews whose `author.login` ends with `[bot]` or `author.type == "Bot"`.
If a HUMAN `APPROVED` review matches `headRefOid`, report "skipped — already
approved" and stop. Skip this precheck when invoked with `--force`.

### Step 0.5: Draft check

If the PR is still a draft, do NOT post the review request — a draft is not
ready for review.
Report that the PR must be marked ready first (via
`Dev10x:gh-pr-request-review` / `gh pr ready`) and stop.
Skip this check when invoked with `--force`.

### Step 1: Prepare

**REQUIRED:** Run the prepare subcommand — do NOT inline YAML reads or
hand-build the message:

```bash
uvx dev10x skill notify gchat-review-prepare --pr {pr_number} --repo {repo}
```

Output JSON keys: `skip`, `ask`, `space`, `message`, `reason`,
`resolved_mentions`, `pr_url`, `pr_title`, `card`, `fallback_text`.

`card` holds the panel unless the repo opted out, in which case it is
`null`. When set, `message` shrinks to the mentions line and the
formatted body lives in the card.

### Step 2: Handle result

- `skip=true` → report "Google Chat notification skipped for {repo}", done.
- `ask=true` → **REQUIRED: Call `AskUserQuestion`** for space alias (required)
  and mentions (optional); then proceed with the provided values.
- otherwise → continue to Step 3.

### Step 3: Confirm

**REQUIRED: Call `AskUserQuestion`** showing the formatted message with options
"Post to Google Chat" / "Skip". If "Skip", done.

### Step 4: Send

Delegate to `Skill(Dev10x:gchat)` — write the message to a temp file and pass it:

`Skill(skill="Dev10x:gchat", args="--space {space} --message-file {temp_file}")`

When `card` is non-null, write that JSON to a second temp file and pass
both halves so the mentions still notify:

`Skill(skill="Dev10x:gchat", args="--space {space} --message-file {temp_file} --card-file {card_file} --fallback-text {fallback_text}")`

**NEVER** call the CLI `gchat-send` directly from here — delegate to the
`Dev10x:gchat` skill so transport rules stay centralized.

Report success: space alias and returned message name.

## [Verify] during use

- App-auth `spaces.messages.create` is enabled and the bot is in the space.
- A native Google Group mention notifies members; if not, switch the config
  to expand `@alias` to member `<users/ID>` tokens.
