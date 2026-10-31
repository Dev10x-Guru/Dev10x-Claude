# Review Checklist Format (GH-1694)

The CI code review keeps one checklist in the PR body, refreshed on
every run, so a reader sees what the last round checked and which head
it read without opening the review history. Ported from tt-pos
PAY-1689.

The workflow fails the run when the body lacks a block stamped with
that run's id and reviewed sha ("Fail if the review left no fresh
checklist" in `claude-code-review.yml`), so the checklist is part of
the run's output, not an optional extra.

## Block

The block sits between two sentinel comments and nothing outside them
is ever edited:

```markdown
<!-- BEGIN claude-review-checklist -->
## Review checklist

_Auto-maintained by claude-code-review.yml. Round 2 · run 1234567890 · sha 0123456789abcdef0123456789abcdef01234567._

**reviewer-infra**
- [x] Concurrency group on the new workflow — `pr-draft-on-push.yml:11`
- [ ] Action pinned to a SHA — `some-action@v2` is a tag (inline comment)
- [~] Fork PR handling — not applicable: same-repo guard skips forks

**Cross-cutting**
- [x] No secret echoed to logs — only `::notice` with the head sha
<!-- END claude-review-checklist -->
```

## Header

`_Auto-maintained by claude-code-review.yml. Round N · run <RUN_ID> · sha <SHA>._`

- `Round N` matches the round number of this run's summary. A run that
  posts no summary uses the highest existing round + 1.
- `run` and `sha` are copied from the prompt's RUN CONTEXT
  (`github.run_id` and the PR head sha the run was triggered for).
  They are never derived or invented: the guard step matches them
  literally, and the merge policy compares the sha with HEAD.

## Items

- One group per reviewer agent the run dispatched, named after its
  spec in `.claude/agents/`, plus a final **Cross-cutting** group for
  `references/review-checks-common.md`.
- Each item is `- [state] <summary, at most 60 chars> — <evidence>`.
  Evidence is mandatory: a `file:line`, a quoted fragment, or a
  pointer to the inline comment that carries the finding.
- States:

| Mark | Meaning |
|------|---------|
| `[x]` | Checked and satisfied |
| `[ ]` | Checked and failing — a blocking finding this round |
| `[~]` | Not applicable to this diff, with the reason as evidence |

An unchecked `[ ]` item and a request for changes go together: a round
that leaves any `[ ]` submits its review as blocking.

## Update protocol

1. Read the current body: `gh pr view <PR> --json body -q .body`.
2. When the sentinel pair exists, replace everything between them;
   otherwise append a blank line and the whole block to the body.
3. Write the full new body with the Write tool to
   `review-checklist-body.md`.
4. Apply it: `gh api -X PATCH repos/<REPO>/pulls/<PR> -F body=@review-checklist-body.md`.

The body edit fires `pull_request: edited`, which the code review does
not run on, so the refresh cannot start another round.

## Reading it

- The sha is the head the round read. When it differs from HEAD, the
  current head has no review on record — see
  `references/pr-merge-policy.md` § Reading Review Signals.
- An author may edit anything outside the markers. An edit inside
  them is overwritten by the next round.
