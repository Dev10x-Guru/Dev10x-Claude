# Dev10x PR Review — GitHub Action install

Run Dev10x automated PR review on **any** repository by installing the
Dev10x GitHub Action. This is independent of the Claude Code plugin
install ([installation.md](installation.md)) — you do not need the
plugin to use the Action.

> **Status (M6).** The install flow (GH-351) and the learned-rules
> review path (GH-352) are live. The continuous learning loop (GH-353,
> the `learn` mode) extends this and is tracked separately.

## What it does

| PR event | Mode | Behavior |
|----------|------|----------|
| `opened`, `synchronize`, `ready_for_review` | `review` | Reviews the diff with the packaged reviewer checklist + learned rules, posts inline + summary comments |
| `closed` | `learn` | Harvests review patterns (scaffolded — no-op until GH-353) |

### How the review works (GH-352)

On the `review` path the Action assembles two inputs into the consumer
workspace under `.dev10x-review/` before invoking the model:

- **`checklist.md`** — a bundled, repo-agnostic reviewer checklist that
  ships inside the Action. It distills the internal multi-agent review
  pipeline (scope rules, false-positive gate, severity levels, per-domain
  and cross-cutting checks) so an external repo gets comparable review
  quality without any Dev10x internal files checked out.
- **`learned-rules.md`** — review rules mined from **your own**
  repository's merged-PR review history via
  `dev10x github review-rules`. These are heuristic signals weighted
  during review, not hard rules. Mining degrades gracefully: if it is
  unavailable, the review proceeds on the bundled checklist alone.

When the review finds issues it converts the PR to draft so you can
batch fixes without re-triggering a review on each push; mark it
*Ready for review* when done.

## Prerequisites

- An **Anthropic API key** with access to the model you select
  (default `haiku`). Create one at
  [console.anthropic.com](https://console.anthropic.com/).
- Admin access to the target repository (to add a secret and a
  workflow file).

## Step 1 — Add the API key secret

In the target repository:

**Settings → Secrets and variables → Actions → New repository secret**

| Name | Value |
|------|-------|
| `ANTHROPIC_API_KEY` | your Anthropic API key |

The key is never written to logs and is only passed to
[`anthropics/claude-code-action`](https://github.com/anthropics/claude-code-action).

## Step 2 — Add the workflow

Copy [`install/dev10x-review.yml`](install/dev10x-review.yml) to
`.github/workflows/dev10x-review.yml` in the target repository.

The workflow references the Action by tag:

```yaml
- uses: Dev10x-Guru/dev10x-claude@v1
  with:
    anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}
```

Pin to a released tag (`@v1`) for stability, or a commit SHA for
maximum reproducibility.

## Step 3 — Permissions

The workflow job must grant these permissions so the Action can read the
PR and post review feedback:

```yaml
permissions:
  contents: read         # check out the PR head
  pull-requests: write   # post inline + summary review comments
  issues: write          # post issue-style comments / labels
  id-token: write        # OIDC for the Claude Code action
```

These are **job-level** permissions in the consumer workflow — the
Action does not request additional scopes. No GitHub App installation is
required for the Action route.

## Action inputs

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `anthropic_api_key` | yes | — | Anthropic API key (pass via secret) |
| `github_token` | no | `${{ github.token }}` | Token for PR read + comment writes |
| `model` | no | `haiku` | Claude model id (`haiku`, `sonnet`, `opus`) |
| `mode` | no | `auto` | `review`, `learn`, or `auto` (event-driven) |

## GitHub App route (deferred)

A hosted **GitHub App** — central install, webhook-driven, no per-repo
workflow file — is the heavier alternative to the Action. It is out of
scope for this scaffold and tracked under the M6 milestone. The Action
route above requires no hosting and works today.

## Verify

Open a pull request in the target repository. The **Dev10x PR Review**
check appears in the PR's Checks tab; review comments post on completion.
If nothing runs, confirm the workflow file path
(`.github/workflows/dev10x-review.yml`), the `ANTHROPIC_API_KEY` secret,
and that the PR is not a draft (draft PRs are skipped on the review path).
