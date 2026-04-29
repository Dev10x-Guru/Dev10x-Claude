# New Slack Bot Creation Guide

Use this reference when the user chose "Create a new Slack Bot"
in Step 2a of `Dev10x:slack-setup`.

## App Creation

1. Direct the user to https://api.slack.com/apps → "Create New App"
2. Choose "From scratch"
3. Name the app (suggest: "Claude AI" or "Dev10x Bot")
4. Select the workspace

## Required Bot Token Scopes

Add under **OAuth & Permissions → Bot Token Scopes**:

| Scope | Used by |
|-------|---------|
| `chat:write` | Posting messages |
| `files:write` | Uploading screenshots/evidence |
| `reactions:write` | Adding emoji reactions |
| `conversations:join` | Auto-joining channels when posting |
| `users:read` | Resolving user mentions |
| `users:read.email` | Deriving `self_user_id` from git email |

## Optional Scopes

| Scope | Used by |
|-------|---------|
| `im:write` | Sending DM reminders to yourself |

## Install and Copy Token

1. Install the app to the workspace
2. Copy the **Bot User OAuth Token** (starts with `xoxb-`)
3. Paste it back to the skill

After paste, the skill loops back through Step 1c (`auth.test`)
to validate before storing.
