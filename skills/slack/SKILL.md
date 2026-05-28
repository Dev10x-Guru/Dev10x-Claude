---
name: Dev10x:slack
description: >
  Send notifications to Slack channels with support for threads,
  file uploads, message updates, and user group mentions.
  TRIGGER when: sending messages, uploading files, or updating
  messages in Slack channels.
  DO NOT TRIGGER when: setting up Slack integration (use
  Dev10x:slack-setup), or posting review requests (use
  Dev10x:slack-review-request).
user-invocable: true
invocation-name: Dev10x:slack
allowed-tools:
  - Bash(uvx dev10x skill notify slack-send:*)
  - Bash(${CLAUDE_PLUGIN_ROOT}/skills/slack/slack-notify.py:*)
---

# Dev10x:slack — Slack Notifications

**Announce:** "Using Dev10x:slack to send a Slack notification."

## Orchestration

This skill follows `references/task-orchestration.md` patterns.
Create a task at invocation, mark completed when done:

**REQUIRED: Create a task at invocation.** Execute at startup:

1. `TaskCreate(subject="Send Slack notification", activeForm="Sending notification")`

Mark completed when done: `TaskUpdate(taskId, status="completed")`

## Overview

Post messages, upload files, reply in threads, update or delete
messages, and send self-DM reminders — all from Claude Code. The
script resolves user group mentions automatically from your config.

## First-Time Setup

If no Slack token is found, walk the user through setup using
AskUserQuestion:

**Step 1 — Bot Token Scopes.** Configure the full scope set at
`api.slack.com/apps → <your app> → OAuth & Permissions` **before**
clicking *Install to Workspace*. Each *Reinstall to Workspace* drops
the bot's channel memberships, so install once with everything.

| Scope | Skill feature it enables |
|-------|--------------------------|
| `chat:write` | Post messages (`--message`, `--update`). |
| `chat:write.public` | Post to public channels without being a member. |
| `files:write` | Upload files (`--files`), delete files (`--delete-file`). |
| `reactions:write` | Add emoji reactions (`--reactions`). |
| `channels:read` | Diagnose `channel_not_found`, look up channels by name. |
| `groups:read` | Same as above for private channels. |
| `mpim:read`, `im:read` | Same for multi-party and direct messages. |
| `channels:history` | Read thread replies (post-and-read workflows). |
| `groups:history` | Same for private channel threads. |
| `mpim:history`, `im:history` | Same for MPIM / DM threads. |

> **Why all of these?** The narrow `chat:write` set lets the skill
> *send* messages but not *recover* from failures. Without
> `channels:read`, the skill cannot tell the user *which* channels
> the bot is actually in when `channel_not_found` returns. Without
> `*:history`, post-and-read flows are impossible.

After adding scopes, click **Reinstall to Workspace** and re-invite
the bot to channels you want it to post in.

**Step 2 — Token storage method:**

| Option | Pros | Cons |
|--------|------|------|
| System keyring (recommended) | Secure, persists across sessions | Requires `secret-tool` |
| `SLACK_TOKEN` env var | Simple, works everywhere | Must set per-session |
| Config file token | Always available | Plaintext on disk |

For **keyring** (recommended):
```bash
secret-tool store --label="Slack Bot Token" service slack key bot_token
```

For **env var**: add `export SLACK_TOKEN=xoxb-...` to shell profile.

**Step 3 — User token vs bot token:**

- `xoxb-` (bot token): Posts as a named bot. Requires the app to be
  added to each channel. Set `bot_username` in config.
- `xoxp-` (user token): Posts as yourself. No username override.
  Broader permissions but tied to your account.

The script auto-detects the token type from its prefix.

## Multi-Workspace Support

The skill supports posting to multiple Slack workspaces from one
machine via the `--workspace NAME` flag:

```bash
${CLAUDE_PLUGIN_ROOT}/skills/slack/slack-notify.py \
  --workspace aperture \
  --channel C_APERTURE_CHAN \
  --message "hi"
# Reads bot token from: secret-tool lookup service slack-aperture key bot_token
```

Token resolution order:

1. `--workspace NAME` → keyring `service=slack-<NAME>` (or the
   `workspaces.<name>.keyring_service` override). Raises if missing —
   the workspace was explicitly requested.
2. `SLACK_TOKEN` env var (wins over the default keyring; use this for
   ad-hoc workspace switching without persistent config).
3. Default keyring `service=slack`.

Store each workspace's bot token under its own keyring service:

```bash
secret-tool store --label="Slack Tyrell"    service slack            key bot_token
secret-tool store --label="Slack Aperture"  service slack-aperture   key bot_token
```

## Configuration

Create `~/.claude/memory/Dev10x/slack-config.yaml`:

```yaml
# Your Slack user ID (for --remind self-DMs)
self_user_id: U040B2ES3N2

# Display name when posting with a bot token (xoxb-)
bot_username: Claude AI

# User group mention resolution (@name → <!subteam^ID>)
user_groups:
  "@dev-team": "<!subteam^S0123456789>"
  "@qa-team": "<!subteam^S9876543210>"

# Optional: per-workspace overrides for --workspace NAME
workspaces:
  aperture:
    self_user_id: U0B3EXAMPLE
    bot_username: Aperture Bot
    # Defaults to "slack-<name>" if omitted
    keyring_service: slack-aperture
    user_groups:
      "@aperture-team": "<!subteam^S1111111111>"
```

All fields are optional. The script works without a config file —
user group mentions and self-DMs just won't resolve. When
`--workspace NAME` is set, values under `workspaces.<name>` override
the top-level keys.

## Usage

**Friction-free CLI:** prefer `uvx dev10x skill notify slack-send`
for the common send paths. The underlying `slack-notify.py` script
remains available for advanced flags (file upload, message
update, reactions, reminder DMs) until they are exposed on the
CLI surface.

### Send a message

```bash
uvx dev10x skill notify slack-send \
  --channel CHANNEL_ID \
  --message "Your message here"
```

### Reply in a thread

```bash
uvx dev10x skill notify slack-send \
  --channel CHANNEL_ID \
  --thread-ts 1770113637.855309 \
  --message "Thread reply"
```

**Extracting thread info from a Slack URL:**
- URL format: `https://WORKSPACE.slack.com/archives/<CHANNEL>/p<TS>`
- Insert `.` before the last 6 digits of the timestamp
  (e.g., `p1770113637855309` → `1770113637.855309`)

### Upload files

```bash
${CLAUDE_PLUGIN_ROOT}/skills/slack/slack-notify.py \
  --channel CHANNEL_ID \
  --files screenshot.png report.pdf \
  --message "Optional comment"
```

### Update a message

```bash
${CLAUDE_PLUGIN_ROOT}/skills/slack/slack-notify.py \
  --channel CHANNEL_ID \
  --update MESSAGE_TS \
  --message "Revised content"
```

### Delete a message

```bash
${CLAUDE_PLUGIN_ROOT}/skills/slack/slack-notify.py \
  --channel CHANNEL_ID \
  --delete MESSAGE_TS
```

### Delete a file

```bash
${CLAUDE_PLUGIN_ROOT}/skills/slack/slack-notify.py \
  --delete-file FILE_ID
```

Does not require `--channel`. Use the file ID returned by `--files`
upload or visible in Slack URLs.

### Send a self-DM reminder

```bash
${CLAUDE_PLUGIN_ROOT}/skills/slack/slack-notify.py \
  --remind "Follow up on PR #1234"
```

Requires `self_user_id` in config or `SLACK_SELF_USER_ID` env var.

### Additional flags

| Flag | Effect |
|------|--------|
| `--workspace NAME` | Select non-default workspace (see Multi-Workspace Support) |
| `--broadcast` | Also post thread reply to channel |
| `--reactions emoji1 emoji2` | Add emoji reactions after posting |
| `--unfurl` | Enable link previews |
| `--message-file PATH` | Read message body from a file |
| `--verbose` | Show debug output |

## MCP Integration

**MCP for reads, this script for sends.** The MCP Slack tools are
better for searching channels, looking up users, and reading threads.
Use this script for all posting operations — it handles user group
resolution and bot identity consistently.

### Mention Syntax

- **User:** `<@USER_ID>` (e.g., `<@U040B2ES3N2>`)
- **Group:** `<!subteam^GROUP_ID>` (auto-resolved from config)
- **Plain `@name`** does NOT notify anyone — always use ID syntax.

To discover user IDs, use MCP `slack_search_users` tool.

## Slack Formatting Tips

- Slack supports: `*bold*`, `_italic_`, `~strike~`, `` `code` ``,
  ` ```code block``` `, `>quote`, bullet lists
- Slack does NOT support: markdown tables (use code blocks),
  headings (#), `[text](url)` links — use `<url|text>` instead

## Error Handling

| Error | Cause | Fix |
|-------|-------|-----|
| `not_in_channel` | Bot not added to channel | Add bot via channel settings → Integrations |
| `channel_not_found` | Wrong channel ID | Verify ID in Slack |
| `No Slack token found` | No token configured | Run first-time setup above |
| `missing_scope` | Token lacks required permissions | Add scope in Slack app settings, then **Reinstall to Workspace** (see First-Time Setup scope table) |
| `channel_not_found` (multi-workspace) | Token belongs to a different workspace than the channel | Pass `--workspace NAME` or unset `SLACK_TOKEN` to fall through to default keyring |
| `cant_delete_message` | Trying to delete another user's msg | Bot can only delete its own messages |

## Integration with Other Skills

This script is used by:
- **Dev10x:park-remind** — sends deferred-item DMs to yourself
- **Dev10x:gh-pr-monitor** — posts PR review notifications

For multi-line messages, use the Write tool to create a temp file,
then pass via `--message-file` or `$(cat /tmp/msg.txt)`. Do NOT use
heredoc (`cat <<'EOF'`) — the bash security hook blocks it.
