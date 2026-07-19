---
name: Dev10x:gchat
description: >
  Send notifications to a Google Chat space via a private Chat bot
  (service-account app auth). Mirrors Dev10x:slack.
  TRIGGER when: sending a message to a Google Chat space.
  DO NOT TRIGGER when: posting a review request (use
  Dev10x:gchat-review-request), or sending to Slack (use Dev10x:slack).
user-invocable: true
invocation-name: Dev10x:gchat
allowed-tools:
  - Bash(uvx dev10x skill notify gchat-send:*)
---

# Dev10x:gchat — Google Chat Notifications

**Announce:** "Using Dev10x:gchat to send a Google Chat notification."

## Orchestration

**REQUIRED: Create a task at invocation.** Execute at startup:

1. `TaskCreate(subject="Send Google Chat notification", activeForm="Sending notification")`

Mark completed when done: `TaskUpdate(taskId, status="completed")`

## Overview

Post a plain-text/markup message to a Google Chat space through a private
Chat bot. The bot authenticates with a service account (app auth) and posts
via the Chat REST API. Group mentions are resolved from config.

## First-Time Setup

If no service-account key is found, walk the user through setup:

1. **Create a private Chat app.** In a Google Cloud project, enable the Google
   Chat API and configure a Chat app. Publish it **privately** to your
   Workspace (not the Marketplace). Attach a service account.
2. **Add the bot to the space.** Open the target space → *Apps & integrations*
   → add your Chat app. App-auth messages are rejected for spaces the bot is
   not a member of. **[Verify]** app-auth `spaces.messages.create` is enabled
   for your Workspace.
3. **Store the SA key in the keyring:**
   ```bash
   secret-tool store --label="GChat SA key" service gchat key sa_key
   ```
   Paste the full service-account key JSON when prompted.
4. **Record the space ID** in config (below). The space ID is the
   `spaces/AAAA...` segment — not the app link `chat.google.com/.../app/chat/...`.

## Configuration

Create `gchat-config.yaml` (resolved via the shared Dev10x config home,
alongside `slack-config.yaml`):

```yaml
spaces:
  tt-reviews:
    space_id: "AAAA1234567"
# @alias -> native Google Chat group mention token
user_groups:
  "@dev-team-fe": "<the native group mention token>"
# GitHub login -> Chat user ID (individual mentions)
users:
  wooyek:
    chat_user_id: "1234567890"
    name: Janusz Skonieczny
```

## Usage

```bash
uvx dev10x skill notify gchat-send \
  --space tt-reviews \
  --message "Your message here"
```

For multi-line messages, use the Write tool to create a temp file and pass
`--message-file PATH`. Do NOT use heredocs (blocked by the bash security hook).

| Flag | Effect |
|------|--------|
| `--space` | Space alias from `gchat-config.yaml` (required) |
| `--message` | Message text |
| `--message-file` | Read message body from a file |

## Formatting

Google Chat markup: `*bold*`, `_italic_`, `<url|text>`, `>quote`.
Mentions: `<users/USER_ID>`, `<users/all>`, or the configured group token.

## Error Handling

| Error | Cause | Fix |
|-------|-------|-----|
| `No Google Chat service-account key found` | Keyring secret missing | Run the `secret-tool store` command in First-Time Setup |
| `service-account key is not valid JSON` | Wrong keyring value | Re-store the full SA key JSON |
| `Google Chat POST failed (HTTP 403)` | Bot not in space / API disabled | Add the bot to the space; verify Chat API app-auth is enabled |
| `No Google Chat space configured for alias` | Alias missing in config | Add it under `spaces:` in `gchat-config.yaml` |

## Non-goals (v1)

File upload, message update/delete, reactions, threading, rich cards.
These exist for Slack but are intentionally out of scope for Google Chat v1.
