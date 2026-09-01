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

If no credentials are found, walk the user through setup:

1. **Create a private Chat app.** In a Google Cloud project, enable the Google
   Chat API and configure a Chat app. Publish it **privately** to your
   Workspace (not the Marketplace). Attach a service account.
   A GCP project can host **only one Chat app**, and the project defines the
   bot's identity. To get the same per-engineer setup as `Dev10x:slack`
   (where each engineer posts as their own personal bot), each engineer
   creates their **own project** (e.g. `gchat-<name>`) with their own Chat
   app and service account. Projects are free and the Chat API needs no
   billing account.
   Even for a post-only bot, **enable Interactive features** and check
   *Join spaces and group conversations* — the Visibility list and the
   ability to add the app to spaces only exist inside that section. Use a
   dummy HTTPS endpoint (e.g. `https://example.com`) for Connection
   settings; it is only called on interaction, which a post-only bot
   never receives.
   Leave *Build this Chat app as a Workspace add-on* **unchecked** — the
   add-on framework is for apps extending Gmail/Docs/Calendar and adds
   deployment requirements a notification bot never needs.
   The Avatar URL must be a **direct image link** (`content-type:
   image/*`, e.g. `https://github.com/<user>.png` or an
   `i.imgur.com/....png` URL) — a page URL that merely shows the image
   fails silently and leaves the bot avatar blank.
2. **Add the bot to the space.** Open the target space → *Apps & integrations*
   → add your Chat app. App-auth messages are rejected for spaces the bot is
   not a member of. **[Verify]** app-auth `spaces.messages.create` is enabled
   for your Workspace.
3. **Set up credentials** using one of the two auth methods:

   **impersonate (recommended — keyless).** Google's recommended pattern
   for local development: no key is ever created, only short-lived (1h)
   tokens minted via the IAM Credentials API. Prefer this for every new
   setup — a downloaded JSON key never expires and leaks easily, and orgs
   that enforce the `iam.disableServiceAccountKeyCreation` org policy
   cannot create one at all. Grant yourself *Service Account Token
   Creator* (`roles/iam.serviceAccountTokenCreator`) **on the service
   account**: console → *IAM & Admin → Service Accounts* → open the SA →
   *Permissions* tab → *Grant access* → **your email** as the new
   principal. Direction matters — you are the principal, the SA is the
   resource; granting the role *to the SA itself* (an easy mix-up, the
   dialogs look alike) does nothing here. Then log in
   once with `gcloud auth application-default login`, and add to
   `gchat-config.yaml`:
   ```yaml
   auth:
     method: impersonate
     service_account: gchat-bot@PROJECT_ID.iam.gserviceaccount.com
   ```
   `gcloud` is only needed once to create the ADC file.

   **sa_key (legacy default).** Kept as the implicit default for existing
   setups, and for headless environments with no human `gcloud` login.
   Download a JSON key for the service account and store it in the
   keyring:
   ```bash
   secret-tool store --label="GChat SA key" service gchat key sa_key
   ```
   Paste the full service-account key JSON when prompted.
   On macOS use the Keychain instead:
   ```bash
   security add-generic-password -U -s gchat -a sa_key -l "GChat SA key" -w '<key JSON>'
   ```
4. **Record the space ID** in config (below). The space ID is the
   `spaces/AAAA...` segment — not the app link `chat.google.com/.../app/chat/...`.

## Configuration

Create `gchat-config.yaml` (resolved via the shared Dev10x config home,
alongside `slack-config.yaml`):

```yaml
spaces:
  tt-reviews:
    space_id: "AAAA1234567"
# Recommended; omitting falls back to the legacy sa_key (keyring) method
auth:
  method: impersonate
  service_account: gchat-bot@PROJECT_ID.iam.gserviceaccount.com
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
| `--card-title` | Render the body as a cardsV2 panel with this header |
| `--card-subtitle` | Subtitle under `--card-title` |
| `--card-file` | Post hand-authored card JSON from a file |
| `--fallback-text` | Notification text when a card cannot render |

## Formatting

**Plain text** (default). Google Chat markup: `*bold*`, `_italic_`,
`<url|text>`, `>quote`. Mentions: `<users/USER_ID>`, `<users/all>`, or
the configured group token.

**Cards (v2 panels).** `--card-title` moves the body into a `cardsV2`
panel, translating the same markup into the HTML subset a card renders —
`<b> <i> <u> <s> <a href> <br> <code> <pre> <ul> <ol> <li>` — buying
headers, bullet lists and link buttons that plain text cannot express:

```bash
uvx dev10x skill notify gchat-send \
  --space tt-reviews --card-title "Nightly run" --message-file summary.md
```

**Mentions do not work inside a card.** Only a message's `text` field
resolves `<users/ID>` tokens. Since `--card-title` leaves nothing in
`text`, a mention in that body stops notifying — to mention someone and
still get a panel, pass `--message` for the mention line and
`--card-file` for the panel (in-process: `message=` plus `cards=`).

For a panel beyond one body of text, build the JSON with
`dev10x.skills.notifications.gchat_cards` (`text_paragraph`, `divider`,
`link_button`, `button_list`, `section`, `card`). `--card-file` accepts a
`cardsV2` array, a single `{cardId, card}`, or a bare card object.

`fallbackText` is what Chat shows in a mobile notification when the card
cannot render; it is derived from the message body unless you pass
`--fallback-text`, so a card is never silently unnotifiable.

## Error Handling

| Error | Cause | Fix |
|-------|-------|-----|
| `No Google Chat service-account key found` | Keyring secret missing | Run the `secret-tool store` command in First-Time Setup |
| `service-account key is not valid JSON` | Wrong keyring value | Re-store the full SA key JSON |
| `Google Chat POST failed (HTTP 403)` | Bot not in space / API disabled | Add the bot to the space; verify Chat API app-auth is enabled |
| `No Google Chat space configured for alias` | Alias missing in config | Add it under `spaces:` in `gchat-config.yaml` |
| `No Application Default Credentials found` | impersonate method without ADC login | Run `gcloud auth application-default login` |
| `Service-account impersonation failed (HTTP 403)` | Missing/backwards Token Creator grant, grant still propagating, or ADC logged into the wrong Google account | Grant `roles/iam.serviceAccountTokenCreator` on the SA **to your user**; wait a few minutes after granting; re-run ADC login with the right account |
| `auth.method is 'impersonate' but auth.service_account is not set` | Incomplete auth block | Add `service_account:` under `auth:` in `gchat-config.yaml` |
| App not findable under *Add apps* in the space | Interactive features off, missing Visibility entry, or propagation lag | Enable interactive features + *Join spaces*, add the user to Visibility, then allow a few minutes after saving |

## Non-goals

File upload, message update/delete, reactions, threading. These exist
for Slack but remain out of scope for Google Chat.

Rich cards **were** a v1 non-goal; GH-1113 lifted that — see § Formatting.
Interactive card widgets (`textInput`, `selectionInput`, `dateTimePicker`)
stay out of scope: they only pay off with an endpoint that handles the
interaction callback, and this is a post-only bot.
