# Wait for Blocking Review Bots at Head (GH-1832)

Read this from `instructions.md` § Post-CI Comment Re-check, before
reading empty `haiku-thread-scan` arrays as clean. It also sets one
exit condition of the Phase 2 loop.

## Why empty arrays are not a clean review

Comment scans read text. Empty text does not mean a bot reviewed the
PR:

- review bots skip draft PRs, so nothing ran;
- some bots submit an empty review body and put every finding in
  inline comments;
- some bots post an issue comment instead of a review, so there is no
  reviewed commit to compare;
- a review of an earlier push says nothing about the current head.

## The check

```
mcp__plugin_dev10x_cli__bot_review_status(pr_number={pr_number}, repo="{repo}")
```

Which bots block is per-repo: `blocking_bots` login globs in
`<Dev10x config>/settings-pr-merge.yaml`. With none configured,
`ready` is always `true`.

| Result | Action |
|--------|--------|
| `ready: true` | The scan arrays are trustworthy; continue. |
| `is_draft: true` and a `missing_blocking_bots` entry | The bots never ran. Re-run Phase 0.5 (mark ready), then wait. |
| A blocking bot missing or not at `head_sha` | It has not caught up with the latest push. Wait as described below, then call `bot_review_status` again. Once `bot_review_status` reports `ready: true`, re-dispatch `haiku-thread-scan` — the bot's findings land with its review. |
| Still not ready after 10 calls | A bot that never answers is a deadlock, not a pass. Stop waiting and put `reasons` in the status report so the merge gate (gh-pr-merge Check 1e) decides. Never wait forever, never call it clean. |

## How to wait

`bot_review_status` is one read; it does not wait. Never write a
`sleep`, `while` or `until` loop, in Bash or the Monitor tool — the
monitor forbids hand-rolled polling (`instructions.md` § Micro-agent A,
GH-1138). Between calls, wait server-side instead:

1. When the bot submits PR reviews (`kind: review`), call
   `pr_wait(pr_number={pr_number}, until="bot_at_head", bot="<login>")`.
   It returns once that bot's review is anchored to the head.
2. When the bot runs as a check run (for example `claude-review`),
   call `ci_check_status(pr_number={pr_number}, repo="{repo}",
   wait=true, wait_for=["<bot check name>"])`. It returns once that
   check settles, which is when the bot's output lands.
3. When the bot only comments and has no check run, call
   `bot_review_status` once per later monitor pass — after the next
   `ci_check_status(wait=true)` or Phase 2 cycle — rather than in a
   tight loop.

Count every `bot_review_status` call; stop after the tenth.

For a bot with `kind: comment`, `at_head` rests on time
(`at_head_basis: timestamp`): it spoke after the head commit.
`at_head: null` means it cannot be told — treat it as not at head.

## Phase 2 exit condition

Phase 2 may move to Phase 2.5 only when `bot_review_status` reports
`ready: true`, or the bounded wait above ran out and its `reasons`
are in the status report.
