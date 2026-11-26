# Fixup Source: Who Signs Off the Squash (GH-2008)

Both review processes leave `fixup!` commits, and both end in an
autosquash.
They differ only in **who signs off** that squash.

| Source | Made by | Sign-off | Squashed |
|--------|---------|----------|----------|
| Agent-owned | `dev10x-coding:review --loop` → `review-fix`, CI fixes, bot-comment fixes, standalone `git-fixup` | The loop's clean round, or the pipeline itself | Before the PR is handed to a human |
| Human round | `gh-pr-respond` / `gh-pr-fixup` answering a supervisor or teammate comment | That human, asked | After that human says yes |

A PR that still carries agent-owned fixups is not ready for the
supervisor or the team.
Human-round fixups stay for the round, so the reviewer reads only the
fix and not the whole diff again.

## The rule (the one marker)

**A `fixup!` commit is human-round when a reply by the PR author on a
human (non-bot) review thread or comment links its SHA.**
`gh-pr-respond` always posts that "Fixed in `<sha>`" reply, so the
marker exists without a trailer, label or extra file.
Every other `fixup!` is agent-owned.

Two consequences follow:

1. **Deferral keys on the source, never on PR state.**
   A published PR, a human review on it, or `supervisor_review:
   required` defers nothing by itself.
   Only human-round fixups whose reviewer has not signed off are kept.
2. **Agent-owned fixups never outlive the process that made them.**
   The review loop squashes its own at loop end (see
   `dev10x-coding:review` `references/loop-mode.md` § Loop end).
   The shipping Groom step squashes the rest before the first review
   request.

To classify, list the branch's fixups with
`git log --format='%H %s' origin/<base>..HEAD` and keep the `fixup!` /
`squash!` subjects.
Then read the PR's thread comments
(`mcp__plugin_dev10x_cli__pr_comments(action="list", pr_number=N)`)
and top-level comments, and mark a fixup human-round when a non-bot
thread holds an author reply containing its SHA (7 to 40 characters).
No open PR means no human round: every fixup is agent-owned.

## Squashing only agent-owned fixups

When no human-round fixup exists, squash with the Fixup strategy
(plain autosquash).
When one does, build a `rebase_groom` sequence that marks `fixup` only
the agent-owned commits, moved under their targets, and keeps every
human-round `fixup!` as `pick`.
The rewrite moves SHAs after the earliest target, so Phase 4 rewrites
the permalinks in thread replies as usual.
Both cases are deterministic and fixup-only, so pass
`provably_safe: true` to `resolve_gate(gate="history_rewrite")`.

## Asking the human to sign off

Run this once per human round, when that round's fixups are pushed and
every thread from it has a reply.
The asker is whoever finished the round: `gh-pr-respond`, standalone
or under a parent, or the `work-on` Groom step when git-groom kept
human-round fixups.

A sign-off already exists, so skip the ask and squash, when any of
these holds:

1. That reviewer approved the PR at the current head (`pr_get`
   `reviews`, `commit.oid` equal to `headRefOid`).
2. That reviewer replied yes to an earlier ask for this round.
3. The supervisor said yes in this session.

Otherwise resolve the run mode the way
`references/review-readiness.md` § When the PR is not ready orders it.

- **Attended** → **REQUIRED: Call `AskUserQuestion`** (do NOT use
  plain text), header `Squash`.
  Exactly one option carries `(Recommended)` and leads.
  It is **Squash now** when every thread of the round is resolved, and
  **Keep the fixups for now** while any is still open.
  - **Squash now** — run `Skill(dev10x-coding:git-groom)`, push with
    `--force-with-lease`, re-monitor CI.
  - **Keep the fixups for now** — leave the step pending and ask again
    after the next round.
- **Unattended** → post one top-level PR comment with
  `mcp__plugin_dev10x_cli__pr_issue_comment`, addressed to the round's
  human reviewers by login: the round's fixups are pushed, every
  thread is answered, are they satisfied, and may the agent squash now
  (reply "squash" to approve).
  Before posting, read the PR's comments and skip when an ask for the
  current head already exists.
  Leave the groom pending: the next session or monitor reads the reply
  and squashes on a yes.

Never wait silently for an approval nobody was asked for.
