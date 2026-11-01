# PR Merge Policy: REQUIRED vs RECOMMENDED Feedback

How code review feedback is classified and whether it blocks merge.

## Feedback Classification

### REQUIRED Feedback

Marked with **REQUIRED:**, these items must be addressed before merge can proceed.

- **When enforced**: Merge is blocked until REQUIRED items are addressed
- **How to address**:
  - Create commits that fix the issue
  - Reply to comment with commit SHA
  - Author pushes changes; feedback is re-verified
- **If unaddressed**: PR cannot merge; reviewer or author must resolve before approval

**Example REQUIRED items**:
- PR body format violations (missing JTBD, missing `Fixes:` link, disallowed separators)
- Commit message format errors (missing gitmoji, ticket ID)
- Code conflicts with codebase conventions
- False positives verified by author response

### RECOMMENDED Feedback

Marked with **RECOMMENDED** or presented without explicit enforcement marker, these items are suggestions.

- **When applied**: Author may acknowledge, defer, or address per judgment
- **How to handle**:
  - Author may fix (create fixup commit)
  - Author may reply explaining deferral
  - Merge proceeds with or without addressing
- **If unaddressed**: Merge is allowed; no blocking

**Example RECOMMENDED items**:
- Suggestion to refactor for clarity (not correctness)
- Optional enhancement ideas
- Nice-to-haves flagged for future work
- Informational context

## Review Workflow

1. **Initial review** — Claude or maintainer posts feedback
2. **Author responds** — Creates fixup commits or replies to comments
3. **Force-push** — Feedback is re-verified after author pushes changes
4. **Re-review check** — On force-push, all feedback is re-evaluated
5. **Merge gate** — REQUIRED items must be addressed; RECOMMENDED may remain

## Frictionless Merge Feature

The `gh pr merge` feature (available after PR #455) enables one-command merge without web UI.

- **Impact**: Reduces friction but makes format compliance critical
- **Enforcement**: CI checks validate PR body format before merge is allowed
- **Responsibility**: Author must ensure REQUIRED feedback is addressed

## When Feedback is Re-Checked

Feedback is re-evaluated in these scenarios:

- **Force-push**: When author pushes new commits (common after fixup squash)
- **Author comment**: When author replies to explain changes
- **Manual request**: When reviewer requests another review pass

Feedback is **not** automatically re-checked after simple file edits or
approvals — it requires a commit push to re-trigger.

## Reading Review Signals

What an agent reports before a merge rests on reading these signals
correctly. Each one is about what to report, not a new merge gate.

- **A new HEAD is not a fix by itself.** A finding stays open until a
  change between the reviewed commit and HEAD addresses it — in any
  file, including commits a rebase brought in — or a thread reply
  answers it. A newer SHA alone answers nothing.
- **A "just a rebase" claim does not carry the review forward.** A PR
  body or reply saying the new head only rebased reviewed work is
  prose. Report the review as not run on HEAD unless
  `git range-diff <reviewed-base>..<reviewed-sha> <new-base>..HEAD`
  shows every patch unchanged.
- **A base retarget changes what was reviewed without moving HEAD.**
  When a stacked PR is retargeted onto `develop` after its dependency
  merges, the PR's diff can cover content no round saw. A retarget
  fires `pull_request: edited`, which the code review does not run on.
  Compare the changed files against the old and the new base; if they
  differ, report the review as not run on the current diff.
- **A later review supersedes an earlier all-clear.** A wrap-up comment
  saying a PR is ready, or that the bots found nothing, is a snapshot.
  A request for changes or a CRITICAL finding that lands after it is
  what gets reported.
- **A workflow-file PR cannot be reviewed by the Claude bots.** A PR
  editing `.github/workflows/claude*.yml` runs those workflows from its
  own copy, and `claude-code-action` refuses a copy that differs from
  the default branch, so no Claude review runs. With GH-1691's "Fail if
  the review never ran" step, `claude-review` and `hygiene-review` go
  red; without it they read green with nothing behind them. The red is
  the expected signal, not a defect, and no commit can clear it before
  merge. Such a
  PR uses the two-PR convention: its body says the change cannot be
  exercised pre-merge and names where the behaviour will first be
  observed after merge. Say plainly that no bot reviewed it; whether to
  wait for a human read is the author's call.
- **The checklist's sha says which head the last round read
  (GH-1694).** The code review stamps `run <id> · sha <sha>` into the
  `claude-review-checklist` block of the PR body. When that sha is not
  HEAD, report the review as not run on HEAD, even with every check
  green: the draft-on-push workflow cannot draft a fork PR or a push
  made with the workflow token. A PR with no checklist block has no
  review on record. Format: `references/review-checklist-format.md`.
- **A skipped Claude check is a switched-off review, not a failed one
  (GH-1756).** `claude-review` / `hygiene-review` read `skipped` when
  `CLAUDE_REVIEW_ENABLED` is `false` or the PR carries
  `skip-claude-review` (`.claude/rules/claude-ci-cost.md` § Switching
  the reviews off). Report "Claude review disabled", expect no
  checklist block, and do not hold the merge for it — like the
  workflow-file case above, whether to wait for a human read is the
  author's call.

## Merge Configuration (Fanout / Work-On)

When `dev10x:fanout` or `dev10x:work-on` orchestrate PR merges,
two playbook-level fields control behavior.

### `merge_mode`

Controls whether PRs are merged autonomously after CI passes.

| Mode | Behavior |
|------|----------|
| `manual` | Mark ready, stop. User merges explicitly. |
| `autonomous` | After CI green + no comments → auto-merge |
| `cascade` | Autonomous + auto-rebase downstream PRs |

**Resolution order** (first match wins):
1. Session friction level — `adaptive` defaults to `cascade`
2. Playbook override — `merge_mode` in `work-on.yaml`
3. Default — `manual`

### `merge_strategy`

Controls the `gh pr merge` flag passed during merge.

| Strategy | Flag | When to use |
|----------|------|-------------|
| Rebase | `--rebase` | Default — atomic commits preserved |
| Squash | `--squash` | Single-commit PRs or messy history |
| Merge commit | `--merge` | Protected branches requiring merge |

**Resolution order** (first match wins):
1. Playbook override — `merge_strategy` in `work-on.yaml`
2. Memory note — user feedback memory mentioning preference
3. Default — `--rebase`

### Playbook Configuration

Add these fields to your playbook override (see
`references/config-resolution.md` for paths):

```yaml
merge_mode: cascade
merge_strategy: squash
```

## References

- PR body format rules: `references/git-pr.md` § PR Body
- Commit format rules: `references/git-commits.md`
- Job Story format: `references/git-jtbd.md` § Voice Requirement
