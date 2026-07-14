# Google Chat review-request integration — design

**Date:** 2026-07-14
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
- Migrating Slack off; both run in parallel.

## Transport decision: incoming webhook

Use a Google Chat **incoming webhook** per space (recommended over the REST
API + service account):

- One-way "please review" notifications are the canonical webhook use case.
- Mirrors the Slack model: a single secret in the OS keyring, no OAuth /
  token refresh / GCP service-account key management.
- Setup: in the target space → *Apps & integrations → Manage webhooks* →
  create → copy URL `https://chat.googleapis.com/v1/spaces/<SPACE>/messages?key=...&token=...`.

**REST API + service account** is the documented fallback if (a) the
Workspace admin disables incoming webhooks org-wide, or (b) we later need a
proper Chat app identity / rich cards. **[Verify]** whether webhooks are
enabled for the target space's Workspace.

**Note:** the link `chat.google.com/u/1/app/chat/AAQA-6ChjqA` is a Chat *app*
link, not a webhook URL — the webhook must be generated in the actual space.

## Architecture (mirrors the Slack pair)

### 1. `Dev10x:gchat` — transport (mirrors `Dev10x:slack`)

- Resolves the webhook URL from the OS keyring: `service=gchat`, key per
  space alias (e.g. `secret-tool store service gchat key <alias>_webhook`).
- Resolves group aliases → Google Chat mention annotations (see Mentions).
- Posts `{"text": "<message>"}` to the space webhook.
- Backed by a `dev10x skill notify gchat-send` CLI subcommand so the skill
  layer stays thin and the logic is unit-testable off the HTTP surface.

Flags mirror the Slack CLI where sensible: `--space <alias>`,
`--message` / `--message-file`.

### 2. `Dev10x:gchat-review-request` (mirrors `Dev10x:slack-review-request`)

Flow, mirroring the Slack skill:

1. **Approval-state precheck** — skip if the PR is already human-approved on
   its current HEAD (bot approvals do not count).
2. **Draft check** — if the PR is a draft, mark ready first (or skip, matching
   Slack behavior).
3. **Prepare** — `dev10x skill notify gchat-review-prepare --pr N --repo R`
   reads `gchat-config-code-review-requests.yaml`, resolves the space +
   mentions, fetches PR title + JTBD from the body, formats the message.
4. **Confirm + post** — delegate to `Dev10x:gchat` to send.

Returns `skip` / `ask` / posted, same shape as the Slack prepare output.

### 3. Config files (in `~/.claude/memory/Dev10x/`, same location as Slack)

`gchat-config.yaml`:

```yaml
# Display name is set on the webhook itself.
spaces:
  tt-reviews:
    keyring_key: tt-reviews_webhook   # secret-tool service=gchat
# Group mention resolution (@name → mention annotation or member expansion)
user_groups:
  "@dev-team-fe":
    # Preferred: a Google Group that is a member of the space, if webhook
    # group-mention is supported; else expand to members below.
    members: ["<users/1234567890>", "<users/2345678901>"]
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

Google Chat has no Slack-style subteams. We mirror the **authoring
experience** (config references `@dev-team-fe`) and resolve it at post time:

- Individual: `<users/USER_ID>`; whole space: `<users/all>` — both documented
  for webhooks.
- Group alias `@dev-team-fe` resolves to either a native Google Group mention
  (if the space has that group as a member and webhook group-mention works)
  or an **expansion to member `<users/ID>` annotations**. **[Verify]** native
  group-mention-via-webhook support during implementation; the member
  expansion is the guaranteed fallback.

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

- Missing webhook secret → actionable error naming the keyring command to run.
- Unconfigured repo → honor `default_action` (skip / ask), like Slack.
- Non-2xx from the webhook POST → surface status + response body; do not
  claim success.
- `skip: true` repo → report skipped, no post.

## Testing

Mirror the repo's existing skill-testing approach:

- CLI logic (`gchat-send`, `gchat-review-prepare`) covered by `pytest` with a
  PATH-injectable / patched fake for the HTTP POST that records the payload;
  assert on the resolved message, mentions, and space URL.
- Config resolution (space alias, group expansion, per-repo lookup) unit
  tested against fixture YAML.
- No live network calls in tests.

## Open items to confirm during implementation

- **[Verify]** Incoming webhooks are enabled for the target space's Workspace.
- **[Verify]** Whether a Google Group can be @mentioned via webhook text, or
  we must expand to member user IDs.
- Obtain the real space ID / webhook URL (the provided link is an app link).

## Implementation status

This PR carries the **design/scope only** — no skill code yet. Implementation
(the two skills, the `dev10x` CLI subcommands, config schemas, and tests) is
the follow-up, to be planned via `superpowers:writing-plans` in a session
rooted in this worktree.
