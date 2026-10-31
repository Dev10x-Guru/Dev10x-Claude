---
paths:
  - ".github/workflows/claude*.yml"
  - ".github/claude/**"
  - ".github/claude-ci-settings.json"
  - ".github/scripts/claude-pr-context/**"
---

# Claude CI Workflows — Cost and Prompt Caching (GH-1585)

How the Claude workflows (`claude-code-review.yml`,
`claude-pr-hygiene.yml`, `claude-memory-review.yml` and `claude.yml`)
keep API spend low. Ported from tt-pos TD-6210 and AI-822. Each rule
names the mechanism it relies on, so a change that breaks one is easy
to spot in review.

## How the bill is made

A Claude Code run sends the same growing request on every turn: tool
schemas, then the system prompt, then the conversation. The API caches
that prefix up to the first byte that differs. A cache write costs 1.25×
the input price for a 5-minute entry (2× for 1 hour), and a read about
0.1×. Three things drive the bill:

- **Turns.** Each turn resends the whole context. A denied tool call is
  a turn spent for nothing.
- **Prefix stability.** A prefix that differs between runs is written
  again by every run; an identical one is read.
- **Model.** Cache writes and reads scale with the model's input price.

Setup steps (checkout, CLI install) cost seconds and nothing on the
bill, so `actions/cache`-style dependency caching is not worth adding to
these jobs.

## Rules

1. **Shared prefix.** Every Claude step starts `claude_args` with the
   same four flags, in this order:
   `--settings .github/claude-ci-settings.json`
   `--append-system-prompt-file .github/claude/ci-system-prompt.md`
   `--exclude-dynamic-system-prompt-sections`
   `--disallowed-tools "ScheduleWakeup,Monitor"`.
   Rules every CI agent needs (headless session, Bash shapes, evidence,
   untrusted content) go in `ci-system-prompt.md`, not in a workflow
   prompt. `--exclude-dynamic-system-prompt-sections` moves cwd, env and
   git status out of the system prompt.
2. **Static first, per-run values last.** A `prompt:` holds the
   instructions first and ends with a `RUN CONTEXT:` block for the
   repository and PR number. Instructions refer to `<REPO>` and `<PR>`.
   Never put `${{ }}` above the instructions. In `claude.yml` the
   triggering comment is per-run too: it sits in a `REQUEST:` block just
   above RUN CONTEXT.
3. **Prefetch, don't instruct.** PR data comes from
   `.github/scripts/claude-pr-context/gather-pr-context.sh`, run before
   the Claude step, into `.claude-ci/pr-context/` (`INDEX.md` lists the
   files). Stage it from the base or default branch into `RUNNER_TEMP`,
   never from the PR checkout: it runs with the job token. When neither
   branch has `build-claude-inputs.sh` beside it, skip the review with a
   notice. This applies to jobs
   that review a whole PR; a job that answers a single comment may read
   the PR with `gh`, and its prompt says so.
4. **Deterministic writes.** When the output is one comment, the model
   Writes it to a file and a shell step posts it. The hygiene check keeps
   one comment per PR, found by author and the `<!-- dev10x-pr-hygiene -->`
   marker, and edits it in place.
5. **Smallest tool set.** `--tools` drops the schemas of built-in tools
   a job never uses. Never allow an `mcp__github__*` tool: any one of
   them starts the GitHub MCP server and registers all of its tools.
   The `mcp__github_inline_comment__*` tool is a separate, single-tool
   server and is fine.
   Exception: the code review passes no `--tools`, because it needs
   Bash and the subagent tool, whose name differs across CLI
   versions. A list that misses that tool silently disables subagent
   dispatch. Subagent tiers come from each `.claude/agents/` spec's
   `model:`; `reviewer-security` and `reviewer-silent-failures` stay on
   `sonnet` in CI (GH-1619), so a Python or shell PR pays for two more
   sonnet subagents. Revisit from the usage report if that dominates.
6. **5-minute cache.** `claude-ci-settings.json` sets
   `FORCE_PROMPT_CACHING_5M=1`. A one-shot CI run rarely re-reads a
   1-hour entry, and that write costs 2× input. It also sets
   `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1`, so Task subagents return in
   the same turn instead of outliving the headless session.
7. **Measure.** Each Claude job has a "Report Claude usage" step: a
   per-model table in the job summary and a `::notice` line with cost,
   turns, cache read, cache write and uncached input. Healthy runs read
   far more than they write. Compare runs before and after any prompt,
   flag or model change.
8. **One CLI version (GH-1615).** Every Claude step runs the CLI
   version in the `CLAUDE_CLI_VERSION` Actions variable (set on the
   Dev10x-Guru organization). The install
   step fails on an empty value instead of installing `latest`, and runs
   from `RUNNER_TEMP` so a PR's `.npmrc` cannot redirect the registry;
   the action gets the binary through `path_to_claude_code_executable`.
   The CLI decides which model
   `sonnet` and `haiku` name, and the one bundled with
   `claude-code-action` lags a generation, so keep the aliases in
   `--model` and move them by changing the variable. That changes every
   workflow without a PR: read the CLI changelog first, then compare
   usage reports (rule 7). Bump the action and the variable together:
   each action release bundles one CLI through its `claude-agent-sdk`
   dependency (v1.0.250 ships SDK 0.3.300, CLI 2.1.300), and the
   variable should be at least that version, so the action never
   drives a CLI older than the one it was released with.
9. **Federation, not keys (GH-1622).** Every Claude step authenticates
   with the four `anthropic_federation_*` inputs, read from the
   `ANTHROPIC_FEDERATION_RULE_ID` / `_ORGANIZATION_ID` /
   `_SERVICE_ACCOUNT_ID` / `_WORKSPACE_ID` organization variables: the
   job's GitHub OIDC token is exchanged for a short-lived token acting
   as the Dev10x service account, so spend bills to that account and no
   long-lived key sits in the repo. They are identifiers, not secrets.
   Never set `anthropic_api_key` beside them — a key outranks
   federation. The federation rule must accept the OIDC subject of every
   trigger: `pull_request` for the reviewers, the default branch for
   `claude.yml`'s comment events. The code review turns the action's
   probe-comment classifier off (`classify_inline_comments: "false"`)
   because it needs a key, and deletes probe comments in its own step.
10. **Prompts and args are files (GH-1625).** The code review and the
    hygiene check read their prompt from `.github/claude/prompts/` and
    their `claude_args` from `.github/claude/args/<job>.txt` (one line,
    the shared prefix first), so one text can serve the workflow and,
    once wired, `dev10x:gh-review-setup` and a local review mode
    (follow-ups to GH-1625). `claude.yml` and the memory review still
    carry inline prompts. The stage step copies the base-owned files
    (table below) over the checkout, and `build-claude-inputs.sh` joins
    the parts and appends RUN CONTEXT. Edit the files, never the
    workflow step. `tests/test_claude_ci_prompts.py` fails on a `${{` in
    those files, an inline prompt, or a drifted prefix.

## Review Trigger Cadence (GH-1694)

The paid review runs once per ready-for-review flip, never once per
push: `claude-code-review.yml` triggers on `opened` and
`ready_for_review` only, and both review jobs skip drafts. Three
things keep a merged head reviewed:

1. A blocking round drafts the PR (the review's draft step); the
   author's flip back to ready runs the next round.
2. `pr-draft-on-push.yml` drafts a ready PR on every push, so a commit
   pushed after a clean round is re-reviewed on the next flip. It acts
   as a GitHub App (`PR_DRAFT_APP_ID` variable,
   `PR_DRAFT_APP_PRIVATE_KEY` secret), because the workflow token cannot
   convert a PR to draft, and fails loudly until both are set.
3. The review checklist in the PR body stamps the reviewed `sha`;
   `references/pr-merge-policy.md` § Reading Review Signals compares it
   with HEAD before a merge.

A draft suppresses CI here, so after a push the PR shows no checks
until it is marked ready again: an agent that pushes a fixup marks the
PR ready (`pr_ready`) to get CI and the next round. A push made with
the workflow `GITHUB_TOKEN` fires no `pull_request` event, and a fork
PR's run gets no secrets, so neither is drafted — flip those by hand.

## Where each file comes from (GH-1620)

A review runs the PR's code under the base branch's instructions: the
rules, prompts, settings and `references/` a review reads all come
from the base, so a PR cannot rewrite what its own review follows.

| Source | Files | Why |
|---|---|---|
| Base branch (the action) | `.claude/`, `CLAUDE.md` and the other config `restoreConfigFromBase` restores; the PR's copies sit in `.claude-pr/` | claude-code-action restores them before the CLI starts |
| Base branch (the workflow) | `.github/claude/**`, `.github/claude-ci-settings.json`, `references/**`, `.github/scripts/claude-pr-context/`; the code review keeps the PR's copies in `.claude-ci/pr-head/` | the stage step copies them from the base or default ref (rule 3, rule 10) |
| The PR | everything else | the checkout is `refs/pull/<N>/merge`, the PR merged into its base |

To review a change to one of those files against its new text, read
the PR's copy (`.claude-pr/` or `.claude-ci/pr-head/`); the code
review prompt says so. `claude-ci-settings.json` sets only the two
environment values in rule 6; it does not change which plugins load.

## Verifying a change

Changes to `claude*.yml` are validated against the default branch, and
the action skips on the PR that edits them. Verify on the next PR after
merge, from the usage step: the per-model table in the job summary
names the model ids the aliases resolved to, and the `::notice` line
gives cache read against cache write.
