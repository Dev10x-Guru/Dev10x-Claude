# GitHub App Bot Identity Setup

When configured, Dev10x posts agent-generated PR review replies and
PR summary comments under a GitHub App identity (e.g.
`dev10x-bot[bot]`) so reviewers can tell at a glance which messages
came from the engineer and which came from the local agent.

The feature is **opt-in**. With no configuration, every call uses
the engineer's existing `gh auth` token — no behavior change.

## What identity each call uses

| Call site | Identity |
|-----------|----------|
| `pr_comment_reply` (review thread replies) | bot |
| `post_summary_comment` (PR summary footer) | bot |
| `create_pr` (PR authorship) | engineer |
| `request_review` (reviewer assignment) | engineer |
| `resolve_review_thread` | engineer |
| `issue_create` | engineer |
| `pr_notify` (Slack + reviewer ping) | engineer |

Engineer-attribution stays for actions where `dev10x-bot[bot]` would
break GitHub semantics — branch protection rules that require a human
author/approver, reviewer assignment, and thread resolution.

## Quick start: interactive wizard

The fastest way to set this up is the bundled CLI. If you don't
already have `dev10x` on your `PATH` (Claude Code marketplace
installs the plugin but not the CLI globally), install it once
from PyPI via [`uv`](https://docs.astral.sh/uv/):

```bash
uv tool install Dev10x
```

Then run the wizard:

```bash
dev10x github-app setup
```

It walks through:

1. **Picking an install target** — Personal, Organization, or
   Manual. The wizard switches the registration URL accordingly
   and tells you which "Where can this App be installed?" radio
   to pick (see table below).
2. **Registering the App** — opens the right URL for the chosen
   target.
3. **Installing it on at least one repo.**
4. **Pointing the wizard at the downloaded `.pem`** — defaults to
   the newest `*.private-key.pem` in `~/Downloads`. The file is
   moved to `~/.claude/Dev10x/github-bot/dev10x-bot.pem` and
   `chmod 600`'d. Use `--paste` for headless setups.
5. **End-to-end verification** before writing config:
   - `GET /app` confirms the key matches the App ID you entered
   - `GET /app/installations` confirms the App is installed
     somewhere
   - Token exchange + `GET /repos/<owner>/<repo>` per
     installation confirms the bot can actually read a target repo

Failed verification leaves no config behind. On success the
wizard prints the verified installations and target repos.

Run `dev10x github-app status` to confirm the config is in place.

To upgrade later: `uv tool upgrade Dev10x`.

The rest of this doc covers the manual flow if you prefer to wire
things up yourself, or want context on what each value means.

### Install-target choices

| Choice | Registration URL | "Where can this App be installed?" |
|--------|------------------|------------------------------------|
| Personal account (multi-target) | `https://github.com/settings/apps/new` | **"Any account"** — required to install on org accounts you belong to |
| Organization | `https://github.com/organizations/<org>/settings/apps/new` | Implicit — the App is owned by the org |
| Manual | (you open the settings page yourself) | Match the scope to where the bot will comment |

Picking "Only on this account" on a personal-account App blocks
you from installing it on any org. The wizard's Personal flow
explicitly steers you to "Any account" to avoid this trap.

### Advanced: pinning a single installation

`dev10x github-app setup` no longer prompts for an Installation
ID. The bot resolves the right installation per repo at call
time, which is the correct behavior for any user with more than
one installation.

If you specifically need to pin every call to one installation
(rare — typically a multi-org constraint), add the field to the
yaml by hand after running setup:

```yaml
github_app:
  app_id: "123456"
  private_key_path: "~/.claude/Dev10x/github-bot/dev10x-bot.pem"
  installation_id: "78901234"   # optional pin
  enabled: true
```

## One-time GitHub App registration

1. Visit
   <https://github.com/settings/apps/new> (personal) or
   `https://github.com/organizations/<org>/settings/apps/new` (org).
2. Fill in:
   - **Name:** `dev10x-bot` (or any unique name — what appears as
     `<name>[bot]` next to the comments)
   - **Homepage URL:** anything; it's not user-facing
   - **Webhook:** uncheck "Active" — Dev10x doesn't receive webhooks
3. **Repository permissions:**
   - `Pull requests` → `Read and write` — required for review
     replies and summary comments
   - `Contents` → `Read-only` — required so the App can read the
     repo before commenting
   - All others → `No access`
4. **Where can this App be installed:**
   - Personal-account App that needs to install on orgs → **"Any
     account"**.
   - Org-owned App → leave the default (scope is the org).
   - Personal-only with no org installs → "Only on this account".
5. Create the App, then on the App settings page:
   - Note the **App ID** (numeric)
   - Click **Generate a private key** — a `.pem` file downloads.
     Move it to `~/.claude/Dev10x/github-bot/dev10x-bot.pem` and `chmod 600`.
6. Click **Install App** in the left nav. Pick the repos you want
   the bot to post in. After installing, the URL contains
   `installations/<id>` — that's the **Installation ID** (optional;
   Dev10x can resolve it per-repo automatically).

## Configure Dev10x

Create `~/.claude/Dev10x/github-bot/github-app.yaml`:

```yaml
github_app:
  app_id: "123456"
  private_key_path: "~/.claude/Dev10x/github-bot/dev10x-bot.pem"
  # installation_id is optional — Dev10x will auto-resolve it
  # from the target repo via the App JWT if omitted
  installation_id: "78901234"
  enabled: true
```

To temporarily disable the bot identity for a session, flip
`enabled: false` (or delete the file). Calls fall back to user
auth.

## Verify the setup end-to-end

The wizard runs this automatically; if you set things up
manually, you can prove the credentials work without opening a
draft PR:

1. Mint an App JWT (PyJWT + the `.pem`, 5-minute expiry).
2. `GET https://api.github.com/app` with `Authorization: Bearer
   <jwt>` — the `id` field must match your `app_id`.
3. `GET https://api.github.com/app/installations` — must return
   at least one entry.
4. `POST /app/installations/<id>/access_tokens` — should return
   a short-lived `token`.
5. `GET https://api.github.com/repos/<owner>/<repo>` with
   `Authorization: Bearer <token>` — should return the repo.

If step 2 returns a different `id`, you pasted the wrong `.pem`
or entered the wrong `app_id`. If step 3 is empty, the App is
registered but not installed. If step 5 fails, the installation
exists but doesn't include the target repo.

## Verify the bot identity is in effect

Open a draft PR on a repo where the App is installed, then ask
Dev10x to reply to one of the PR review comments. The reply
should show the bot avatar and `[bot]` suffix on the author
chip. Other engineer-driven actions (PR creation, reviewer
assignment) should keep your personal avatar.

If a reply still posts under your personal account:

1. Confirm the App is **installed** on the target repo (the
   GitHub App settings page lists the repos under "Installed").
2. Confirm `~/.claude/Dev10x/github-bot/dev10x-bot.pem` is readable
   (`ls -l` should show `600`).
3. Confirm `app_id` in the yaml matches the numeric App ID
   on the App settings page.
4. Run the failing call once more and check the Dev10x debug
   logs — when token resolution fails (missing key, bad scope,
   App not installed), Dev10x logs the failure and falls back
   to user auth silently rather than erroring.

## Security notes

- The private key authenticates as the App. Treat it like a
  password: store under `~/.claude/Dev10x/github-bot/`, set `chmod 600`,
  never commit it.
- Installation tokens (the short-lived bearer Dev10x mints from
  the JWT) live in process memory only; they are not written
  to disk.
- The token is cached per-repo until 60 seconds before its
  expiry, then refreshed transparently. Restart your Claude
  session to drop the cache early.

## Out of scope (current implementation)

- The shell-script paths in `gh-pr-monitor` and a few legacy
  comment-posting scripts still inherit the engineer's auth
  even when the App is configured. Migration is tracked
  separately — see the issue thread.
- Slack notifications continue to use the existing Slack bot.
  This document covers GitHub identity only.
