# Dev10x PR Review — GitHub Action install

Run Dev10x automated PR review on **any** repository by installing the
Dev10x GitHub Action. This is independent of the Claude Code plugin
install ([installation.md](installation.md)) — you do not need the
plugin to use the Action.

> **Status (M6).** The full pipeline is live: the install flow (GH-351),
> the learned-rules review path (GH-352), and the continuous learning
> loop (GH-353, the `learn` mode).

## What it does

| PR event | Mode | Behavior |
|----------|------|----------|
| `opened`, `synchronize`, `ready_for_review` | `review` | Reviews the diff with the packaged reviewer checklist + learned rules, posts inline + summary comments |
| `closed` | `learn` | Mines recurring review patterns into validated rules and opens a *rules-update* PR for human approval |

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

### How the learning loop works (GH-353)

On the `learn` path — triggered when a PR is **closed** — the Action
mines your repository's merged-PR review history into validated
reference rules and opens a **rules-update PR** proposing them:

1. Mine recurring reviewer comments and validate each against recent
   diffs (the same pipeline that feeds `review` mode).
2. Write one rule doc per validated pattern under
   `references/review-checks/generated/`.
3. Force-push them to the `dev10x/learned-rules` branch and open (or
   refresh) a PR titled *"🤖 Propose N learned review rule(s)"*.

The bot only **proposes** — merging the PR adopts the rules, closing it
discards them. Nothing is enforced without your approval. When no
pattern validates, or the proposal is already up to date, the learn run
is a no-op (it opens no PR). Because the loop pushes a branch and opens
a PR, the `learn` path needs `contents: write` (see Step 3).

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
PR, post review feedback, and open the learning-loop's rules-update PR:

```yaml
permissions:
  contents: write        # check out the PR head; push the rules branch (learn)
  pull-requests: write   # post review comments; open the rules-update PR
  issues: write          # post issue-style comments / labels
  id-token: write        # OIDC for the Claude Code action
```

`contents: write` (rather than `read`) is required only by the `learn`
path, which pushes the `dev10x/learned-rules` branch. If you run
**review only** (drop the `closed` event from the trigger), `contents:
read` is sufficient. These are **job-level** permissions in the consumer
workflow — the Action does not request additional scopes. No GitHub App
installation is required for the Action route.

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

To confirm the learning loop, **close or merge** a PR that has review
comments. The `learn` run opens (or refreshes) the
*"🤖 Propose N learned review rule(s)"* PR; if no pattern yet validates,
the run logs a no-op notice and opens nothing.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| No check appears on the PR | Workflow not on the default branch, or wrong path | The workflow must live at `.github/workflows/dev10x-review.yml` on the repo's default branch |
| Review never runs, only on close | PR is a draft | Draft PRs are skipped on the review path — mark *Ready for review* |
| `401`/`403` from the model step | Missing or invalid `ANTHROPIC_API_KEY` | Re-add the secret (Settings → Secrets and variables → Actions) |
| Review posts no comments | Diff is clean, or all findings failed the false-positive gate | Expected — a clean PR gets a single "looks good" summary |
| Learn run fails pushing the branch | Job lacks `contents: write` | Set `contents: write` (Step 3); review-only repos can keep `read` |
| No rules-update PR after closing PRs | Not enough recurring review history yet | The loop needs repeated reviewer comments before a pattern validates |
| Learned rules look wrong | They are heuristic proposals | Close the rules-update PR to discard, or edit it before merging |

## FAQ

**Do I need the Claude Code plugin to use the Action?**
No. The Action is fully independent — it only needs the workflow file
and the `ANTHROPIC_API_KEY` secret.

**Will the bot change my code or rules automatically?**
No. Review mode only comments. Learn mode only *opens a PR* proposing
new rule docs — you merge or close it. Nothing lands without approval.

**Which model should I use?**
`haiku` (default) is fast and inexpensive for most reviews. Bump to
`sonnet` or `opus` via the `model` input for deeper analysis on
larger or higher-risk diffs.

**Can I run review without the learning loop?**
Yes. Drop `closed` from the workflow `on.pull_request.types` and set
`contents: read`. You lose rule proposals but keep review on open PRs.

**Where do learned rules live?**
Under `references/review-checks/generated/` in your repo, added by the
rules-update PR. Review mode picks them up on the next run.

## Cost

Each review and each learn run makes Anthropic API calls billed to your
`ANTHROPIC_API_KEY`. Cost scales with the model and the diff size:

- `haiku` (default) is the cheapest — suitable for routine PR review.
- `sonnet`/`opus` cost more per run but reason more deeply.

There is no Dev10x-side charge — you pay only Anthropic API usage and
standard GitHub Actions minutes. See
[Anthropic pricing](https://www.anthropic.com/pricing) for current
per-token rates, and cap spend with a budget on your Anthropic console.
