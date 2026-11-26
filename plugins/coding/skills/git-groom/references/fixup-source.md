# Fixup Source: Who Signs Off the Squash (GH-2008)

Both review processes leave `fixup!` commits, and both end in an
autosquash.
They differ only in **who signs off** that squash.

| Source | Made by | Sign-off | Squashed |
|--------|---------|----------|----------|
| Agent-owned | `dev10x-coding:review --loop` → `review-fix`, CI fixes, bot-comment fixes, standalone `git-fixup` | None needed | When the process that made it ends, and always before the PR is handed to a human |
| Human round | `gh-pr-respond` / `gh-pr-fixup` answering a supervisor or teammate comment | The human who wrote that comment | After that human says yes |

A PR that still carries agent-owned fixups is not ready for the
supervisor or the team.
Human-round fixups stay for the round, so the reviewer reads only the
fix and not the whole diff again.

## The rule (the one marker)

**A `fixup!` commit is human-round when a comment by the PR author, on
a review thread or top-level comment started by a human (non-bot),
contains a commit link to that fixup's SHA.**

- A commit link is a `/pull/<N>/commits/<sha>` or `/commit/<sha>` URL,
  or a `` [`<sha>`] `` link label, with at least 7 leading hex
  characters of the SHA.
  `gh-pr-respond`'s bundled template writes it after `Fix commit:`,
  `gh-pr-fixup` after `Fixed in`; both count, whatever the prefix.
- A `/blob/<sha>/` URL never counts.
  The bundled template pins its **Code change** blob link to the
  branch head, which may be an unrelated agent fixup; reading blob
  links would mark that fixup human-round by accident.
- The fixup's **reviewer** is the human who started that thread.

Every other `fixup!` is agent-owned, except for the fail-safe below.

### Fail-safe: anchored lines (W10, W11)

Two windows leave a human-comment fix with no linking reply: the fix
was committed without one, or the groom runs between the push and the
reply.
So, while the PR has an **unresolved** human thread, a fixup is also
treated as human-round when its diff touches a line that thread is
anchored on — the same `path`, and a changed line inside the thread's
`line` / `original_line` range (± 3 lines of context).
Its reviewer is that thread's author.
When a thread's anchor cannot be read, keep every fixup touching its
file.
Keeping a fixup by mistake costs one sign-off question; squashing one
by mistake costs the reviewer the diff they were following.

### The one PR-state exception

git-groom Phase 0 still refuses a **rebase onto a new base** that a
background agent starts while review threads are open (GH-68 Fix E).
That moves the code under the reviewers' anchors, which no source
rule can undo.
A **squash** is never refused on open threads; it follows this file.

### Consequences

1. **Deferral keys on the source, never on PR state.**
   A published PR, a human review on it, open threads or
   `supervisor_review: required` defer nothing by themselves.
   Only human-round fixups whose reviewer has not signed off are kept.
2. **Agent-owned fixups never outlive the process that made them.**
   The review loop squashes its own when it ends, whatever its
   verdict (see `dev10x-coding:review` `references/loop-mode.md` §
   Loop end).
   The shipping Groom step squashes the rest before the first review
   request.

To classify, list the branch's fixups with
`git log --format='%H %s' origin/<base>..HEAD` and keep the `fixup!` /
`squash!` subjects.
Read the PR's thread comments
(`mcp__plugin_dev10x_cli__pr_comments(action="list", pr_number=N)`)
and top-level comments, apply the marker, then the fail-safe.
No open PR means no human round: every fixup is agent-owned.

## Squashing only agent-owned fixups

Every squash path in git-groom — the adaptive auto-select, the
strategy gate's **Fixup** option and Strategy A — goes through this
rule.
When no human-round fixup is kept, the Fixup strategy may use plain
autosquash (`git autosquash-develop` or `--autosquash`).
**When one is kept, never use `--autosquash`**: it squashes every
`fixup!` it finds.
Build a `rebase_groom` sequence instead that marks `fixup` only the
agent-owned and signed-off commits, moved under their targets, and
keeps every unsigned human-round `fixup!` as `pick`.
The rewrite moves SHAs after the earliest target; Phase 4 maps each
kept pick to its own new SHA, so the marker survives.
Both cases are deterministic and fixup-only, so pass
`provably_safe: true` to `resolve_gate(gate="history_rewrite")`.

## Sign-off check

A human-round fixup is signed off when its own reviewer did one of
these, and nobody else's word counts:

1. **Approved the current tree.** A review by that reviewer with
   `state: APPROVED` (`pr_get` `reviews`) whose `commit.oid` has the
   same tree as `HEAD` — compare `git rev-parse <oid>^{tree}` with
   `git rev-parse HEAD^{tree}`, as DX019 does — so a groom that only
   squashes does not void it, while any new content does. An
   approved commit that cannot be read locally after a force-push is
   not a sign-off.
2. **Said yes to an ask for this round** (see § Reading a yes).
3. **Said yes in this session**, only when the supervisor is that
   reviewer. The supervisor never signs off for a teammate's round.

When a round had several reviewers, each reviewer signs off the
fixups linked from their own threads.

## Asking the human to sign off

Run this once per human round, when that round's fixups are pushed and
every thread from it has a reply.
The asker is whoever finished the round: `gh-pr-respond`, standalone
or under a parent; the `work-on` Groom step when git-groom kept
human-round fixups; or git-groom itself when invoked standalone.
Skip when § Sign-off check already holds.
Otherwise resolve the run mode the way
`references/review-readiness.md` § When the PR is not ready orders it.

- **Attended**, with the reviewer present in the session (the
  supervisor ran the round) → **REQUIRED: Call `AskUserQuestion`** (do
  NOT use plain text), header `Squash`, question naming the round's
  fixups.
  Exactly one option carries `(Recommended)` and is listed first:
  - every thread of the round is resolved →
    **Squash now (Recommended)**, then **Keep the fixups for now**;
  - any thread is still open →
    **Keep the fixups for now (Recommended)**, then **Squash now**.

  **Squash now** runs `Skill(dev10x-coding:git-groom)` (it pushes with
  `--force-with-lease`), then re-monitor CI.
  **Keep the fixups for now** leaves the step pending.
- **Unattended**, or the reviewer is a teammate not in the session →
  post one top-level PR comment with
  `mcp__plugin_dev10x_cli__pr_issue_comment`, addressed to the round's
  reviewers by login, that starts with the marker line
  `<!-- squash-ask round=<n> -->`, says the round's fixups are
  pushed and every thread is answered, and asks whether they are
  satisfied and the agent may squash now — reply `squash` to approve.
  Before posting, read the PR's comments and skip when an ask with the
  same round number exists.

### Reading a yes

On the PR-comment path, a yes is a comment posted **after** the ask,
by one of the reviewers it addressed, whose body — trimmed, case
ignored — starts with `squash`, `yes` or `approve`.
An `APPROVED` review by that reviewer after the ask also counts.
Anything else, including silence, a question or a thumbs-up reaction,
is not a yes.

### Who reads the answer

No component watches the PR for the answer yet (GH-2014).
The step stays **pending** until a session reads it: the next run of
`gh-pr-respond`, the `work-on` Groom step or git-groom applies §
Sign-off check, and squashes on a yes.
Never wait silently for an approval nobody was asked for, and never
report the squash as scheduled.
