# Google Chat review-request integration — design

**Date:** 2026-07-14 (revised 2026-07-15)
**Branch:** `janusz/gchat-review-request`
**Status:** Approved design; scope-only PR (no implementation yet)

## Problem

PR review requests are posted to Slack today via `Dev10x:request-review`
→ `Dev10x:slack-review-request` → `Dev10x:slack`. The team also wants the
same review request delivered to a **Google Chat** space, in parallel with
Slack (Slack stays as-is).

The Slack machinery lives in this repo, so the Google Chat equivalent is
built here as a sibling set of skills — not by editing the pinned plugin
cache and not by replacing Slack.

## Goals

- Post a PR review request to a Google Chat space, formatted like the Slack
  one (JTBD Job Story + linked PR title + mention).
- Author configuration the **same way as Slack**: per-repo space + named
  group mentions (`@dev-team-fe`), resolved from a central config.
- Standalone invocation (`Dev10x:gchat-review-request`) — the user runs it in
  addition to `Dev10x:request-review`. NOT auto-wired into `request-review`.

## Non-goals (YAGNI)

- Wiring Google Chat into `Dev10x:request-review` orchestration.
- Rich card (cardsV2) messages — plain text/markup only for v1.
- Threading / reply-in-thread.
- Advanced transport flags (file upload, message update/delete, reactions) —
  the Slack transport has these; the Google Chat v1 CLI intentionally does not.
- Migrating Slack off; both run in parallel.

## Transport decision: private Chat app + service account

Post through a **private Google Chat app (bot) authenticated with a service
account** — app authentication against the Chat REST API. This supersedes the
incoming-webhook approach from the first draft.

Why the bot over a webhook:

- The bot posts under its own identity (name + avatar) rather than an
  anonymous per-space webhook.
- One credential (the service-account key) covers every space the bot is a
  member of, instead of a separate webhook URL + key per space.
- App authentication needs no OAuth consent screen and no per-user token
  refresh — it mirrors Slack's single-bot-token model.

Mechanics (all inside the `dev10x` CLI, so the skill layer stays thin and the
logic is unit-testable off the HTTP surface):

1. Read the **service-account key JSON** from the OS keyring
   (`secret-tool lookup service gchat key sa_key`).
2. Sign a JWT with the SA private key using the already-present
   `pyjwt[crypto]` dependency, claiming scope
   `https://www.googleapis.com/auth/chat.bot`.
3. Exchange the JWT for an access token at
   `https://oauth2.googleapis.com/token`
   (`grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer`).
4. `POST https://chat.googleapis.com/v1/spaces/{SPACE_ID}/messages` with
   `{"text": "<message>"}` and `Authorization: Bearer <access_token>`.

**No new runtime dependency.** Token minting uses the existing
`pyjwt[crypto]` base dep; the two HTTPS calls (token exchange + message POST)
use the standard library (`urllib.request`). This matches the repo's stance
of keeping the `uvx`-distributed base env lean, and the direct-HTTP-client
approach preferred for App-JWT flows (GH-499). `google-auth` was considered
and rejected as an unnecessary dependency for two well-understood calls.

**Setup (documented in the `Dev10x:gchat` skill):**

- Create a Chat app in a Google Cloud project, publish it **privately** to the
  Workspace (not the Marketplace), and attach a service account.
- Add the bot to the target space.
- Download the SA key JSON and store it: `secret-tool store --label="GChat SA
  key" service gchat key sa_key`.

**[Verify] during implementation:** that app-authenticated
`spaces.messages.create` is enabled for the target Workspace, and that the bot
has been added to the space (messages to a space the app is not a member of
are rejected).

**Note:** the link `chat.google.com/u/1/app/chat/AAQA-6ChjqA` is a Chat *app*
link, not a space ID — the real space ID (`spaces/AAAA...`) must be read from
the target space.

## Architecture (mirrors the Slack pair)

### 1. `Dev10x:gchat` — transport (mirrors `Dev10x:slack`)

- Resolves the SA-key JSON from the keyring (`service=gchat`, `key=sa_key`).
- Resolves the space alias → space ID from `gchat-config.yaml`.
- Resolves group aliases → Google Chat mention text (see Mentions).
- Mints the access token and posts `{"text": "<message>"}` to the space.
- Backed by a `dev10x skill notify gchat-send` CLI subcommand
  (`src/dev10x/skills/notifications/gchat_notify.py`), mirroring
  `slack_notify.py`.

Flags mirror the Slack CLI where sensible: `--space <alias>`,
`--message` / `--message-file`, and a `--space-id` override for ad-hoc posts.

### 2. `Dev10x:gchat-review-request` (mirrors `Dev10x:slack-review-request`)

Flow, mirroring the Slack skill:

1. **Approval-state precheck** — skip if the PR is already human-approved on
   its current HEAD (bot approvals do not count), matching the Slack skill's
   Step 0.
2. **Draft check** — if the PR is a draft, mark ready first (or skip, matching
   Slack behavior).
3. **Prepare** — `dev10x skill notify gchat-review-prepare --pr N --repo R`
   (`src/dev10x/skills/notifications/gchat_review_request.py`) reads
   `gchat-config-code-review-requests.yaml`, resolves the space + mentions,
   fetches PR title + JTBD from the body, formats the message.
4. **Confirm + post** — delegate to `Dev10x:gchat` to send.

Returns `skip` / `ask` / posted, same JSON shape as the Slack prepare output
(`{skip, ask, space, message, reason}`).

### 3. Config files (in `~/.claude/memory/Dev10x/`, same location as Slack)

Kept alongside the Slack config for parity — the current `Dev10x:slack` skill
still reads its config from `~/.claude/memory/Dev10x/`.

`gchat-config.yaml`:

```yaml
spaces:
  tt-reviews:
    space_id: "AAAA1234567"   # the space's ID (spaces/AAAA1234567)
# Group mention resolution (@alias → native Google Chat group mention token)
user_groups:
  "@dev-team-fe": "<the native group mention token for the space>"
# GitHub login → Chat user ID (for author/individual mentions)
users:
  wooyek:
    chat_user_id: "1234567890"
    name: Janusz Skonieczny
```

`gchat-config-code-review-requests.yaml`:

```yaml
default_action: ask   # skip | ask for unconfigured repos
projects:
  tiretutorv2-dealeradmin:
    space: tt-reviews
    mentions: ["@dev-team-fe"]
  dev10x-ai:
    skip: true
```

## Mentions

v1 uses a **native Google Group mention**: the config maps `@dev-team-fe` to
the group mention token and the bot posts it verbatim in the message text,
relying on Google Chat to notify the group's members.

- Individual mentions use `<users/USER_ID>`; whole-space uses `<users/all>`.
- Group aliases resolve to the configured native group mention token.

**[Verify] during implementation:** that an app-authenticated message can
mention a Google Group *and actually notify its members*. If verification
fails, the documented fallback is to expand the alias to individual
`<users/ID>` member annotations — the config shape leaves room for a
`members: [...]` list per group without a schema change. The error handling
below is designed so a non-notifying post is detectable rather than silently
assumed successful.

## Message format

Google Chat markup: `*bold*`, `_italic_`, `<url|text>`, `>quote`.

```
<group-mention> Please review <https://github.com/org/repo/pull/1751|repo#1751>
*💄 Align Square signup wizard with MUI theme tokens*
> When a dealer opens the Square signup wizard, I want to see copy and icons
> rendered through our shared MUI theme, so I can trust a consistent,
> on-brand onboarding experience.
```

## Error handling

- Missing SA-key secret → actionable error naming the `secret-tool store`
  command to run.
- Token exchange failure (invalid key, clock skew, disabled API) → surface the
  Google error response; do not attempt the message POST.
- Unconfigured repo → honor `default_action` (skip / ask), like Slack.
- Non-2xx from the message POST → surface status + response body; do not claim
  success.
- Bot not a member of the space → surface the API error and point to the
  "add the bot to the space" setup step.
- `skip: true` repo → report skipped, no post.

## Testing

Mirror the repo's existing skill-testing approach:

- CLI logic (`gchat-send`, `gchat-review-prepare`) covered by `pytest` with a
  patched fake for the HTTP layer that records the payload; assert on the
  resolved message, mention token, and space URL.
- Token minting is mocked — tests never sign against a real key or hit
  Google's token endpoint.
- Config resolution (space alias → ID, group mention lookup, per-repo lookup)
  unit tested against fixture YAML.
- No live network calls in tests.

## Open items to confirm during implementation

- **[Verify]** App-authenticated `spaces.messages.create` is enabled for the
  target Workspace, and the bot is a member of the space.
- **[Verify]** Whether a Google Group can be @mentioned via an app-auth
  message and notify its members, or we must expand to member user IDs.
- Obtain the real space ID (the provided link is an app link) and provision
  the service-account key in the keyring.

## Implementation status

This PR carries the **design/scope only** — no skill code yet. Implementation
(the two skills, the `dev10x` CLI subcommands, config schemas, and tests) is
the follow-up, planned via `superpowers:writing-plans` in a session rooted in
this worktree.
