# Review Readiness (GH-1834)

A reviewer should never open a PR that was not ready when they were
asked to look at it. Red CI, an open review thread, a bot that never saw
the head, a draft flag, or fixups an AI review left behind each waste
the reviewer's time and teach the team to ignore review requests. One
field-tested workflow sent PRs out in that state twice in one day.

This file defines the readiness check that `dev10x-coding:request-review` and
`dev10x-coding:gh-pr-request-review` run before any reviewer is pinged. The
audit that looks back at PRs already sent lives in
[`review-readiness-audit.md`](review-readiness-audit.md).

## The five conditions

Run them in this order. Each is one read-only call.

1. **Draft** — `mcp__plugin_dev10x_cli__pr_get(number=N, repo=R)`;
   not ready when `isDraft` is true.
2. **CI** — `mcp__plugin_dev10x_cli__ci_check_status(pr_number=N,
   repo=R)`; not ready unless `verdict` is `green`. A `pending` verdict
   is not green. The one exception is a PR that runs no CI at all:
   `verdict: "empty"` with `checks_source: "confirmed-zero"` passes.
3. **Review threads** — `mcp__plugin_dev10x_cli__unresolved_threads(
   pr_number=N, repo=R)`; not ready when `count` is above zero.
4. **Bots at head** — `mcp__plugin_dev10x_cli__bot_review_status(
   pr_number=N, repo=R)`; not ready when `ready` is false. Its `reasons`
   name the bot. With no `blocking_bots` configured no bot can block,
   but `ready` is still false when the bot data was cut off past 100
   items (`truncated`) — read the PR by hand then.
5. **Fixups** (GH-2008) — `git log --format='%H %s'
   origin/<base>..HEAD` in the PR's checkout; not ready when an
   agent-owned `fixup!` or `squash!` commit is present.
   Classify with `dev10x-coding:git-groom` `references/fixup-source.md`:
   a fixup an author reply on a non-bot thread links belongs to the
   human round already under review and does not count.
   Without a checkout of the PR branch the condition is unknown.

Read each tool's payload caveats before trusting a field:
`references/mcp-tools/caveats-ci-check-status.md` for CI and
`references/mcp-tools/caveats-issues-and-push.md` for threads and bots.
A tool that returns `{"error": ...}` makes that condition **unknown**,
which counts as not ready — being unable to check is not evidence the
PR is fine.

## A draft is not ready

The check never marks a draft ready itself: that would publish the PR
and notify code owners even when the check then refuses, and it would
jump ahead of a `supervisor_review: required` park. In
`dev10x-coding:request-review` a draft fails like any other condition, and the
fix is the caller's: mark it ready with
`mcp__plugin_dev10x_cli__pr_ready`, let CI and the bots run, then
request review again.

`dev10x-coding:gh-pr-request-review` keeps its own Draft State Check, which
flips a draft with `pr_ready` before reviewer resolution because GitHub
drops review requests on drafts. When a run flipped the draft, its
readiness step first waits once for CI with
`ci_check_status(wait=true)` — CI and many bots skip drafts, so the
checks may not even be registered yet. The wait turns a final `empty`
verdict into `infra_unavailable`, so that result is read once more
without `wait` and judged by the rule above; otherwise a PR with no CI
could never pass. It then checks CI, threads, bots
and fixups, even if the caller passed `--readiness-checked`, because the
caller checked a PR that was not ready yet. The request therefore never
goes out in the same breath as the flip. When that check then fails and
the run stops — an unattended refusal or "Stop — fix it first" — the
skill returns the PR to draft with `pr_ready(undo=true)`, so a refusal
does not leave it published with a known problem. Code owners were
already notified by the flip; that cannot be undone.

## When the PR is not ready

List every failing condition with its reason, one line each, then
branch on the run mode. Resolve it in this order (GH-1921):

1. The `--unattended` flag was passed → **unattended**.
2. Otherwise read `run_mode.mode` from a
   `mcp__plugin_dev10x_cli__resolve_gate` payload — every payload
   carries it, whatever gate was asked, so reuse one the skill already
   resolved. It is derived from structured state, never from prose:
   the `afk` overlay, or a `dev10x-coding:work-on` plan step `in_progress` in
   the plan-sync mirror, is `unattended`; mirrored tasks with no plan
   step running is `attended`.
3. `run_mode.mode` is `undetermined` (no mirror, no mirrored tasks, a
   mirror from another branch), or the call returned `{"error": ...}`
   → treat the run as **attended**, and print
   `Run mode: undetermined ({basis}) — treated as attended` so the
   caller sees that nothing settled it.

`references/mcp-tools/caveats-config-pins.md` lists every `basis`.
`dev10x-coding:request-review` is a single skill, not a plan step: it passes
`--unattended` to `gh-pr-request-review` only when it resolved
unattended itself. `--readiness-checked` is not a mode: it tells
`gh-pr-request-review` that `request-review` already ran this check,
so it is not run twice.

The run mode decides what happens **after** a failure, never whether
the conditions are read: an unattended run reads all of them like an
attended one.

- **Unattended**: when the Fixups condition fails, groom instead of
  refusing on it — `Skill(dev10x-coding:git-groom)` (an autosquash is
  provably safe, so `history_rewrite` auto-advances), push with
  `--force-with-lease`, wait for CI once with
  `ci_check_status(wait=true)`, and run the check again.
  Then, for any condition still failing, **refuse**. Do not assign
  reviewers, do not post a chat notification
  and do not comment on the PR. Report the reasons and stop, so the
  caller can fix them and invoke the skill again. Never request review
  "anyway" on a caller's behalf.
- **Attended**: the calling skill fires its readiness gate (the
  `AskUserQuestion` call is spelled out inline in each SKILL.md).
  "Stop — fix it first" is recommended and listed first, because
  every option that reaches this gate has a known problem.
  When the Fixups condition is among the failures, "Groom first"
  leads instead and carries the recommendation: groom, push, re-run
  the check.
  "Request review anyway" is the explicit override.

When every condition the skill checks passes, print one line naming
them — `Readiness: ready (draft no, CI green, 0 open threads, bots at
head, no agent fixups)`; `gh-pr-request-review` leaves out the draft —
and continue.

`--force` skips only the approval precheck, never this check. A flag
that silently skipped readiness would recreate the problem it exists to
stop.

## Result for callers

`dev10x-coding:request-review` and `dev10x-coding:gh-pr-request-review` end every
run with one machine-readable line, after any prose (GH-1921):

```
review_request_result: {"status": "stopped", "pr": 42, "reasons": ["CI failure: pytest (failure)"]}
```

`reasons` lists the failing conditions (empty when none). `status` is
`requested` (ready, sent), `requested_anyway` (attended override sent
it), `stopped` (nobody was asked), `skipped` (config, an approval
short-circuit or a cancel sent nothing) or `error`. With the task tools
present, the skill also stores the object on its own task:
`TaskUpdate(taskId, metadata={"review_request_result": {...}})`.

A caller parses the JSON after `review_request_result:` and branches on
`status`. It never matches the prose: `Readiness: stopped — …` stays as
a line for humans, not as a contract. A missing or unparseable result
line counts as `error` — the caller cannot tell whether anyone was
asked, so it must not report that review was requested.
