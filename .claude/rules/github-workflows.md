---
paths:
  - ".github/workflows/**/*.yml"
  - ".github/workflows/**/*.yaml"
---

# GitHub Workflow Guidelines

Rules for GitHub Actions workflow files.

## Claude Code Workflows

This repository uses four Claude-powered workflows:

1. **claude.yml** - Interactive assistant triggered by @claude mentions
2. **claude-code-review.yml** - Automated PR code reviews
3. **claude-memory-review.yml** - Post-PR lessons learned analysis
4. **claude-pr-hygiene.yml** - PR metadata quality check on
   `opened` / `ready_for_review`

## Multi-Agent Architecture

The code review workflow (`claude-code-review.yml`) uses a
domain-routed architecture:

- **Orchestrator prompt** classifies changed files and dispatches
  to domain-specific agent specs in `.claude/agents/`
- **Agent specs** contain focused checklists and reference rules
  on demand from `.claude/rules/`
- **Cross-cutting checks** in `review-checks-common.md` apply to
  all domains

See `.claude/rules/INDEX.md` for the full architecture.

## Shared Guidelines

Review guidelines are centralized in:
- `references/review-guidelines.md` (workflow)
- `references/review-checks-common.md` (cross-cutting checks)
- `.claude/agents/*.md` (domain-specific checklists)

Workflows should reference these files rather than duplicating content.

## Workflow Optimization

- Keep prompts minimal — reference agent specs and rules on demand
- Add `Read` tool to `claude_args` so Claude can load files on-demand
- Use context variables for dynamic values (repository, PR number)
- Only load agent specs for domains with changed files

## Conditional Execution Pattern

### Three-Layer Filtering

Expensive PR-triggered workflows use a three-layer filtering
strategy to prevent wasted CI execution:

1. **Event-level filtering** (`paths:`) — prevents workflow from
   queuing, saving GitHub Actions minutes
2. **Step-level conditional** (`if:`) — skips steps when no relevant
   files changed, providing additional safety
3. **Runtime PR state validation** — exits before expensive operations
   (checkout, Claude API calls) if PR is already merged/closed

### Runtime PR State Validation

Add a state-check step early in your workflow to gate expensive
operations:

```yaml
- id: pr-state
  name: Check PR state
  run: |
    STATE=$(gh pr view ${{ github.event.pull_request.number }} \
      --json state -q '.state')
    if [ "$STATE" != "OPEN" ]; then
      echo "skip=true" >> $GITHUB_OUTPUT
    fi
  env:
    GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

Chain this check into downstream step conditionals to prevent
wasted operations on merged/closed PRs.

### Guard Output Chaining

When multiple guard conditions exist, chain them using AND logic:

```yaml
- name: Expensive operation
  if: >-
    steps.dedup.outputs.skip != 'true' &&
    steps.pr-state.outputs.skip != 'true'
  run: expensive-operation
```

Each guard step sets `skip=true` in `$GITHUB_OUTPUT`. Downstream
steps reference all guards with `&&`.

### Race Condition Limitations

The PR state check protects against PRs merged *before* the
expensive step runs. A small race window remains if a PR is merged
*during* an in-flight step. This is acceptable — the 99% case is
prevented, and the 1% case causes only redundant review comments.

### Fork PRs Cannot Mint an OIDC Token (GH-1226)

A job that authenticates via OIDC — anything running
`anthropics/claude-code-action` — **cannot work on a `pull_request`
run from a fork**. GitHub refuses to issue the token (and withholds
secrets) for fork-triggered runs. That is a platform security
restriction, not a misconfiguration, and the resulting error is
actively misleading: `Could not fetch an OIDC token. Did you remember
to add id-token: write…` when `id-token: write` is declared right
there in the job.

Guard such a job rather than letting it fail:

```yaml
if: >-
  !github.event.pull_request.draft
  && !github.event.pull_request.head.repo.fork
```

*Why skip rather than fix?* Two permanently-red non-required checks
train reviewers to read a red CI as "just the fork thing" — which is
the state a genuine failure slips through. Skipping costs the review
coverage that was never actually happening and buys back a check
column that means something.

Getting real coverage on fork PRs takes a `workflow_run` split (the
privileged job runs after the untrusted build, with fork code kept out
of the privileged context) or `pull_request_target` (which grants
base-repo credentials and must never check out or execute fork-supplied
code). Neither is a trigger swap; both need deliberate guarding.

## Concurrency Groups

All PR-triggered workflows use concurrency groups to prevent duplicate
runs when multiple events fire in quick succession.

### Pattern

```yaml
concurrency:
  group: ${{ github.workflow }}-${{ github.event.pull_request.number || github.ref }}
  cancel-in-progress: true
```

Apply to all PR-triggered workflows running expensive operations.

*Why?* When `ready_for_review` and `synchronize` events fire within
seconds, workflows listening to both fire twice — wasting CI minutes.

## Code Review Workflow Scope

The `claude-code-review.yml` workflow excludes **only** Claude-specific
workflows to prevent recursive review loops:

```yaml
paths:
  - "!.github/workflows/claude*.yml"
```

**All other workflow files are reviewed.** When modifying
Claude-excluded workflows, ensure manual review.

### Documentation in Review Scope

The review workflow also triggers on documentation changes:

```yaml
paths:
  - "CLAUDE.md"
  - ".claude/rules/**/*.md"
  - ".claude/agents/**/*.md"
```

## Hardcoded Branch Names Are a Bug

When a workflow step hardcodes a branch name, it will fail for PRs
that target a different branch.

```yaml
# BAD — fails for release PRs targeting main
run: git checkout develop

# GOOD — uses the PR's actual base branch
run: git checkout "${{ github.event.pull_request.base.ref }}"
```

## Branch Creation Idempotency

Use `git checkout -B` instead of `git checkout -b` so re-runs
don't fail on an existing branch.

```bash
# BAD — fails on re-run
git checkout -b "my-branch-$PR_NUMBER"

# GOOD — idempotent
git checkout -B "my-branch-$PR_NUMBER"
```

## Security

- Never expose secrets in prompts or logs
- Use `${{ secrets.* }}` for sensitive values
- Limit tool permissions to what's necessary
