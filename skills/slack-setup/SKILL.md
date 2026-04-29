---
name: Dev10x:slack-setup
description: >
  Guide the user through setting up their Slack integration —
  create a Slack app, configure scopes, store the token in the
  system keyring, and generate slack-config.yaml. Auto-detects
  existing tokens, validates them via auth.test, and derives
  config from the API and git so prompts only fire when state
  cannot be discovered.
  TRIGGER when: setting up Slack integration for the first time, or
  reconfiguring Slack credentials.
  DO NOT TRIGGER when: Slack already configured and working, or
  sending messages (use Dev10x:slack).
user-invocable: true
invocation-name: Dev10x:slack-setup
allowed-tools:
  - AskUserQuestion
  - Bash(secret-tool:*)
  - Bash(security:*)
  - Bash(curl:*slack.com/api/auth.test*)
  - Bash(curl:*slack.com/api/users.lookupByEmail*)
  - Bash(pgrep:*)
  - Bash(command:*)
  - Bash(git config user.email:*)
---

# Dev10x:slack-setup — Slack Integration Setup

**Announce:** "Using Dev10x:slack-setup to configure Slack integration."

## Arguments

The skill accepts a single optional argument:

```
/Dev10x:slack-setup [xoxb-...]
```

When a token is passed, skip Step 2 entirely (no token-source
prompt) and go directly to validation in Step 1c.

## Orchestration

**REQUIRED: Create tasks before ANY work.** Execute at startup:

1. `TaskCreate(subject="Detect and validate Slack state", activeForm="Detecting state")`
2. `TaskCreate(subject="Acquire bot token (if missing)", activeForm="Acquiring token")`
3. `TaskCreate(subject="Store token in keyring", activeForm="Storing token")`
4. `TaskCreate(subject="Generate slack-config.yaml", activeForm="Generating config")`

Verification is folded into Step 1 — `auth.test` is the test.
A separate "Verify setup" task is created only when the user
opts into a test message in Step 4.

## Step 1: Detect and Validate Current State

The goal of this step is to short-circuit setup whenever the
existing state is already valid. Prompts MUST NOT fire while
state is still discoverable from the environment.

### 1a. Locate a candidate token

Probe sources in priority order — stop at the first hit:

1. **Argument** — token passed to the skill (`xoxb-...`)
2. **Keyring** — `secret-tool lookup service slack key bot_token`
   (Linux) or `security find-generic-password -s slack -a bot_token -w`
   (macOS)
3. **Environment** — `SLACK_TOKEN` env var

Record where the token came from (`source: arg|keyring|env`) so
later steps know whether to persist it.

### 1b. Read existing config (if any)

Check for `~/.claude/memory/Dev10x/slack-config.yaml`. If present,
load it — fields already filled there are reused, not re-prompted.

### 1c. Validate via auth.test

If a token was located in 1a, call Slack `auth.test`:

```
curl -sS -X POST https://slack.com/api/auth.test \
  -H "Authorization: Bearer <TOKEN>"
```

Parse the JSON response:

| `ok` | Action |
|------|--------|
| `true` | Persist `bot_username` ← `user`, `bot_user_id` ← `user_id`, `team_id` ← `team_id` into the in-memory config. Skip Step 2. Proceed to Step 3 only if the token still needs to be stored (`source: arg|env`); skip Step 3 when `source: keyring`. |
| `false` | Read the `error` field. Treat `invalid_auth` / `token_revoked` / `account_inactive` as unrecoverable for this token — discard it and fall through to Step 2 with a diagnostic line ("token validation failed: <error>"). |

When **no token is found** in 1a, fall through to Step 2.

### 1d. Final state report

Before any prompts fire, summarize what is already configured:

```
Token: found (keyring) — auth.test ok
Bot:   <user> (<user_id>) in team <team_id>
Config: present at ~/.claude/memory/Dev10x/slack-config.yaml
Result: setup already complete — nothing to do
```

If the report covers all required fields (`bot_username`,
`self_user_id`, `user_groups`, token reachable), exit with that
message. **No `AskUserQuestion` fires in this branch.**

## Step 2: Acquire Bot Token (only when missing or invalid)

Skip this step entirely when Step 1c reported `ok: true`.

When the user passed a token via arguments and `auth.test`
rejected it, report the diagnostic and fall through here.

### 2a. Token source

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text).
Options:
- **Use existing token (Recommended)** — paste a token you already have
- **Create a new Slack Bot** — guided app creation
- **Use a user token (xoxp-)** — works but acts as the user

Skip this prompt when a token argument was passed (the source is
already "existing token"; only validation in Step 1c failed).

### 2b. Existing token flow

Point the user at [`references/token-discovery.md`](references/token-discovery.md)
when they ask "where is my token?". Re-run Step 1c after the
user pastes a token; reject anything that fails `auth.test`.

### 2c. New bot flow

See [`references/new-bot-creation.md`](references/new-bot-creation.md)
for the full workspace-setup guide (app creation, required and
optional OAuth scopes, install + token copy steps). Walk the user
through it, then loop back to Step 1c with the pasted token to
validate before storing.

## Step 3: Store Token in System Keyring

Skip when `source: keyring` (already stored).

### 3a. Auto-detect the keyring backend

Run platform detection silently — do NOT prompt yet.

**Linux:**

```
command -v secret-tool >/dev/null 2>&1 && \
  pgrep -f 'gnome-keyring-daemon|kwalletd' >/dev/null 2>&1
```

If both succeed → the keyring backend is available. Default to
keyring storage **without** an `AskUserQuestion`.

**macOS:**

```
command -v security >/dev/null 2>&1
```

If it succeeds → default to Keychain storage **without** an
`AskUserQuestion`.

Store the token:

| Platform | Command |
|----------|---------|
| Linux | `secret-tool store --label="Slack Bot Token" service slack key bot_token` (token piped in) |
| macOS | `security add-generic-password -s slack -a bot_token -w "<token>"` |

### 3b. Fallback prompt

Only when 3a fails to detect a working keyring backend:

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text).
Options:
- **Environment variable (Recommended)** — add `export SLACK_TOKEN=...` to shell profile
- **Skip storage** — manual setup later

Provide the export line for the env-var option:

```
export SLACK_TOKEN="xoxb-your-token-here"
```

## Step 4: Generate slack-config.yaml

Generate `~/.claude/memory/Dev10x/slack-config.yaml`. Each field
is **derived first**, prompted only on derivation failure.

### 4a. Derive fields

| Field | Derivation | Fallback |
|-------|-----------|----------|
| `bot_username` | `auth.test.user` (already in memory from Step 1c) | Prompt only if absent |
| `bot_user_id` | `auth.test.user_id` | Prompt only if absent |
| `team_id` | `auth.test.team_id` | Prompt only if absent |
| `self_user_id` | `users.lookupByEmail?email=$(git config user.email)` against the same token | See 4b |
| `user_groups` | `{}` (empty default — managed in `Dev10x:slack` later) | None — never prompts |

`users.lookupByEmail` call:

```
curl -sS -G \
  --data-urlencode "email=$(git config user.email)" \
  -H "Authorization: Bearer <TOKEN>" \
  https://slack.com/api/users.lookupByEmail
```

On `ok: true`, take `user.id`. On `ok: false` with
`users_not_found`, `missing_scope`, or unset git email, fall to 4b.

### 4b. Prompt only on derivation failure

Only when at least one required field could not be derived,
issue a single batched `AskUserQuestion` listing the fields to
collect (e.g., `self_user_id` because the git email did not match
a workspace member). Never prompt for fields that were derived
successfully.

When all fields are derived (the common case), write the file
without any prompt:

```yaml
self_user_id: "U0123456789"
bot_username: "Claude AI"
bot_user_id: "U9876543210"
team_id: "T01234567"
user_groups: {}
```

## Step 5: Verify (Folded Into Step 1c)

`auth.test` is the verification. The skill marks setup verified
on `ok: true` from Step 1c — no separate verification prompt
fires by default.

### Opt-in test message

Only when the user explicitly asked for a verification message
(e.g., passed `--test` or asked "send a test message" inline)
should the skill fire:

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text).
Options:
- **Send test DM to myself (Recommended)** — uses derived `self_user_id`
- **Send test message to a channel** — prompts for channel ID
- **Skip** — accept the auth.test result

Delegate the actual send to `Dev10x:slack`.

## Net Effect

| Scenario | Prompts before this change | Prompts after |
|----------|---------------------------|--------------|
| Token already in keyring, valid | 3–5 | 0 |
| User pastes existing token | 3–5 | 1 (token paste) |
| User passes token as argument | 3–5 | 0 |
| New Slack Bot creation | 3–5 | ~2 (app guidance + token paste) |

All other prompts fire only on detection failure — never as a
default.
