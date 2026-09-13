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
| `merge_pr` (executing a gated merge) | bot, opt-in — see below |
| `create_pr` (PR authorship) | engineer |
| `request_review` (reviewer assignment) | engineer |
| `resolve_review_thread` | engineer |
| `issue_create` | engineer |
| `pr_notify` (Slack + reviewer ping) | engineer |

Engineer-attribution stays for actions where `dev10x-bot[bot]` would
break GitHub semantics — branch protection rules that require a human
author/approver, reviewer assignment, and thread resolution.

### Why `merge_pr` can use the bot identity

Without it, `merged_by` carries no information: the orchestrator,
every crew worker, and the human all act through the same `gh auth`
token, so an agent merge and a human merge are indistinguishable. A
merge that bypassed the pre-merge gate cannot be attributed even in
principle.

With `merge_bot: true`, a gated merge reads `merged_by: <bot>`, and
therefore **`merged_by: <engineer>` comes to mean "a human, or an
agent that went around the gate"** — the signal that was missing.

Three things this deliberately does **not** claim:

- **Signal, not control.** An agent that hand-rolls
  `PUT /pulls/{n}/merge` with the user token still merges as the
  engineer. The control is a required status check that holds the PR
  while the gate runs; this only makes a bypass *visible*.
- **Not a bypass of branch protection.** A bot merge is refused by a
  required-review rule exactly as an unapproved engineer merge is.
  The `admin` escape hatch (GH-733) is unchanged and still behind its
  `ALWAYS_ASK` gate.
- **Not a licence for workers to merge.** The transport lives inside
  `merge_pr`, reachable only as the last step of the nine-check gate.
  Workers still stop at PR-open (GH-922).

If your repo has a ruleset restricting *who* may merge, leave this
off: the merge falls back to the engineer identity and says so in the
payload, rather than failing.

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
   moved to `~/.config/Dev10x/github-bot/dev10x-bot.pem` and
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
  private_key_path: "~/.config/Dev10x/github-bot/dev10x-bot.pem"
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

   | Permission | Level | Unlocks |
   |---|---|---|
   | `Pull requests` | Read and write | Review-thread replies, PR summary comments |
   | `Issues` | Read and write | Comments on **issues** — see the asymmetry below |
   | `Contents` | Read and write | Reading the repo before commenting; bot-authored commits (§ Commit identity) |

   All others → `No access`.

   **Why `Issues: write` when the bot only comments on PRs.** Comment
   posting goes through `POST /repos/{repo}/issues/{n}/comments` for
   both — GitHub models a PR as an issue for this endpoint. On a PR
   the call is covered by `pull_requests: write`; on an actual issue
   it needs `issues: write`. Grant only the first and you get a bot
   that comments fine on PRs and returns 403 on issues, with nothing
   in the response explaining the difference. `Dev10x:gh-pr-review`
   Transport B routes merged or oversize reviews through this
   endpoint, so the gap is reachable in normal use.

   `Contents` is `Read and write` rather than read-only because the
   same App can author commits; drop it to read-only if you want
   comments but not commit identity.
4. **Where can this App be installed:**
   - Personal-account App that needs to install on orgs → **"Any
     account"**.
   - Org-owned App → leave the default (scope is the org).
   - Personal-only with no org installs → "Only on this account".
5. Create the App, then on the App settings page:
   - Note the **App ID** (numeric)
   - Click **Generate a private key** — a `.pem` file downloads.
     Move it to `~/.config/Dev10x/github-bot/dev10x-bot.pem` and `chmod 600`.
6. Click **Install App** in the left nav. Pick the repos you want
   the bot to post in. After installing, the URL contains
   `installations/<id>` — that's the **Installation ID** (optional;
   Dev10x can resolve it per-repo automatically).

### Accepting a permission change

**Editing an App's permissions does not grant them.** GitHub raises a
request that the *installation* must accept; until someone accepts it,
every call keeps running under the old permission set and fails exactly
as before. This bites hardest when adding `Issues` or `Contents: write`
to an App that already worked for PR comments.

Where the acceptance banner appears depends on who owns the
installation, and the two pages are easy to confuse:

| Installed on | Accept at |
|---|---|
| Your personal account | <https://github.com/settings/installations> |
| An organization | `https://github.com/organizations/<org>/settings/installations` |

A **personal App installed on an org** is the trap: you edit
permissions on your personal App settings page, but the acceptance
banner is on the *org's* installations page. Nothing on the personal
page indicates a pending request.

Open the installation, and accept the "review and accept new
permissions" prompt. Then re-run `dev10x github-app status`, which
reports the permissions actually granted to the installation rather
than the ones you requested.

## Configure Dev10x

Create `~/.config/Dev10x/github-bot/github-app.yaml`:

```yaml
github_app:
  app_id: "123456"
  private_key_path: "~/.config/Dev10x/github-bot/dev10x-bot.pem"
  # installation_id is optional — Dev10x will auto-resolve it
  # from the target repo via the App JWT if omitted
  installation_id: "78901234"
  enabled: true
  # Execute gated merges under the bot identity so merged_by
  # distinguishes them from a human merge. Defaults to false —
  # leave it off if a ruleset restricts who may merge.
  merge_bot: false
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
   For a personal App installed on an org, check the **org's**
   installations page, not your personal one — see § Accepting a
   permission change.
2. Confirm there is no **pending permission request** on that
   installation. A request you never accepted leaves every call on
   the old permission set, which looks identical to "not
   configured".
3. Confirm `~/.config/Dev10x/github-bot/dev10x-bot.pem` is readable
   (`ls -l` should show `600`).
4. Confirm `app_id` in the yaml matches the numeric App ID
   on the App settings page.
5. Confirm `private_key_path` **inside** the yaml points at the
   config directory the yaml itself lives in. An install predating
   the `~/.config/Dev10x/` move may carry a stale
   `~/.claude/Dev10x/...` value even though the file was relocated.
   `dev10x config migrate` rewrites it — deriving the replacement
   from your resolved config root, so a `DEV10X_CONFIG_HOME` or
   `XDG_CONFIG_HOME` setting is honoured. It deliberately declines
   when the key is not present at the new location, leaving the
   broken path visible rather than substituting a plausible one.
6. Run the failing call once more and check the Dev10x debug
   logs — when token resolution fails (missing key, bad scope,
   App not installed), Dev10x logs the failure and falls back
   to user auth silently rather than erroring.

**These failures are layered, which is why a broken setup reads as an
absent one.** Each one aborts before the next becomes reachable: a
stale config path means the missing `issues` permission is never
exercised; granting it reveals a pending acceptance; accepting that
reveals whatever is next. Fixing one and seeing no change does not
mean the fix was wrong. `dev10x github-app status` exists to collapse
that chain into a single report — run it first.

## Commit identity

With `Contents: write`, the same App can author **commits**, not just
comments. Without it, `git log` and `git blame` attribute every
agent-written commit to the engineer.

Set the identity **per worktree**, never `--global` — the point is to
mark the commits an agent wrote in one checkout, and a global setting
would relabel your own work everywhere:

```bash
git config user.name "dev10x-bot[bot]"
git config user.email "<bot-user-id>+dev10x-bot[bot]@users.noreply.github.com"
```

**Where `<bot-user-id>` comes from.** It is the numeric id of the
App's *bot user*, which is **not** the App ID. Read it off any comment
the bot has already posted:

```bash
gh api repos/<owner>/<repo>/issues/<n>/comments --jq '.[] | select(.user.type == "Bot") | .user.id'
```

### The trap: invented noreply addresses break the branch

An invented per-agent address such as `my-crew-H@users.noreply.github.com`
looks plausible and makes the branch **unmergeable**. `aschbacd/gitlint-action`
with `prohibit-unknown-commit-authors` / `prohibit-unknown-commit-committers`
rejects any author or committer that does not resolve to a real GitHub
account, and a `@users.noreply.github.com` address resolves only when
it matches an actual account's noreply form. The App's bot user does
resolve; an invented name does not.

Verify against a throwaway commit on a temp ref before trusting it:

```bash
gh api repos/<owner>/<repo>/commits/<sha> --jq '{author: .author.login, author_type: .author.type, committer: .committer.login, committer_type: .committer.type}'
```

Both `author_type` and `committer_type` should read `Bot`.

### Two properties, so the signal is not over-trusted

- **One identity for all agents.** It distinguishes agent from human,
  never agent from agent. Two crew workers are indistinguishable.
- **The fields are unauthenticated strings.** Anyone can set them.
  This is a diagnostic label, not a control — it deters nothing and
  does not substitute for a required status check.

### Why it is worth setting anyway

GitHub's rebase-merge preserves the commit AUTHOR and rewrites the
COMMITTER to whoever performed the merge. So a bot-authored commit
merged outside an orchestrator's gate reads `author=<bot>
committer=<merger>`, and the discrepancy is visible in the git object
alone — no API call, no timeline reconstruction. Paired with a
bot-identity merge (§ What identity each call uses), a gated agent
merge reads `author=<bot> committer=<bot>`, and anything else stands
out.

## Security notes

- The private key authenticates as the App. Treat it like a
  password: store under `~/.config/Dev10x/github-bot/`, set `chmod 600`,
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
