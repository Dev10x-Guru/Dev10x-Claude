# Review Readiness (GH-1834)

A reviewer should never open a PR that was not ready when they were
asked to look at it. Red CI, an open review thread, a bot that never saw
the head, or a draft flag each waste the reviewer's time and teach the
team to ignore review requests. One field-tested workflow sent PRs out
in that state twice in one day.

This file defines the readiness check that `dev10x:request-review` and
`dev10x:gh-pr-request-review` run before any reviewer is pinged, and the
audit that looks back at PRs already sent.

## The four conditions

Run them in this order. Each is one read-only MCP call.

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
`dev10x:request-review` a draft fails like any other condition, and the
fix is the caller's: mark it ready with
`mcp__plugin_dev10x_cli__pr_ready`, let CI and the bots run, then
request review again.

`dev10x:gh-pr-request-review` keeps its own Draft State Check, which
flips a draft with `pr_ready` before reviewer resolution because GitHub
drops review requests on drafts. When a run flipped the draft, its
readiness step first waits once for CI with
`ci_check_status(wait=true)` — CI and many bots skip drafts, so the
checks may not even be registered yet. The wait turns a final `empty`
verdict into `infra_unavailable`, so that result is read once more
without `wait` and judged by the rule above; otherwise a PR with no CI
could never pass. It then checks CI, threads
and bots, even if the caller passed `--readiness-checked`, because the
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
   the `afk` overlay, or a `dev10x:work-on` plan step `in_progress` in
   the plan-sync mirror, is `unattended`; mirrored tasks with no plan
   step running is `attended`.
3. `run_mode.mode` is `undetermined` (no mirror, no mirrored tasks, a
   mirror from another branch), or the call returned `{"error": ...}`
   → treat the run as **attended**, and print
   `Run mode: undetermined ({basis}) — treated as attended` so the
   caller sees that nothing settled it.

`references/mcp-tools/caveats-config-pins.md` lists every `basis`.
`dev10x:request-review` is a single skill, not a plan step: it passes
`--unattended` to `gh-pr-request-review` only when it resolved
unattended itself. `--readiness-checked` is not a mode: it tells
`gh-pr-request-review` that `request-review` already ran this check,
so it is not run twice.

- **Unattended**: **refuse**. Do not assign reviewers, do not post a chat notification
  and do not comment on the PR. Report the reasons and stop, so the
  caller can fix them and invoke the skill again. Never request review
  "anyway" on a caller's behalf.
- **Attended**: the calling skill fires its readiness gate (the
  `AskUserQuestion` call is spelled out inline in each SKILL.md).
  "Stop — fix it first" is recommended and listed first, because
  every option that reaches this gate has a known problem.
  "Request review anyway" is the explicit override.

When every condition the skill checks passes, print one line naming
them — `Readiness: ready (draft no, CI green, 0 open threads, bots at
head)`; `gh-pr-request-review` leaves out the draft — and continue.

`--force` skips only the approval precheck, never this check. A flag
that silently skipped readiness would recreate the problem it exists to
stop.

## Result for callers

`dev10x:request-review` and `dev10x:gh-pr-request-review` end every
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

## Audit: sent not ready, or went red after?

`mcp__plugin_dev10x_cli__review_readiness_audit(repo=R)` looks at open
PRs that carry a review request and compares when each current problem
began with the latest request. It scans only the `limit` most recently
updated open PRs (default 20, at most 50) and sets `more_open_prs` when
more exist; `pr_number` names one PR instead.

| Verdict | Meaning | Who acts |
|---------|---------|----------|
| `SENT-NOT-READY` | A current problem already existed at the request | The requester — the check above should have stopped it |
| `WENT-RED-AFTER` | Every current problem appeared after the request | The PR owner — a later push, a re-draft or a new thread broke it; or a blocking bot has not yet reviewed a later push |
| `READY` | No current problem | Nobody |
| `UNKNOWN` | A problem's start time could not be read (and none predates the request), or a PR named with `pr_number` has problems but was never sent for review | Read the PR by hand |

A known problem that predates the request wins over an unknown one, so
`SENT-NOT-READY` is reported even when another start time is missing.

The audit judges CI from GitHub's `statusCheckRollup` state on the
head, not from the gate's `ci_check_status` verdict: it has no
required-check or runs-API corroboration, and a head with no checks at
all counts as green. A PR the gate would refuse can therefore read
`READY` here — confirm with the gate before acting on it.

The start times are approximations. Each problem carries `since` but no
basis; the row's `head_arrived_basis` names the basis for the head's
arrival only, which dates bot problems:

- a draft starts at the last conversion to draft, else PR creation;
- a CI problem reads each not-green check's run history (every attempt,
  not only the latest) and starts where its current unbroken streak of
  not-green attempts began. A check already red at the request and
  re-run since is dated before the request; one that was green and went
  red on a re-run after it is dated after. A run still in progress at
  the request and red now counts from its start. The history covers
  20 check suites of 50 runs each on the head. A check whose history
  is missing, or may have been cut off by that window, has an unknown
  start rather than one dated from the attempts that happen to be
  visible, and the row's `truncated` lists `checkSuites` or
  `checkRuns`. A cut in any one suite makes every check's start
  unknown, since the hidden runs could belong to any of them. The head's
  check list itself is read 100 at a time; past that, `truncated` lists
  `contexts` and a failing check may not be named at all. A check with an undated attempt, or a not-green status
  context with no start time, also becomes a separate problem with an
  unknown start, and so does a rollup that is not green but names no
  check;
- a bot problem starts when the head commit reached the PR
  (`head_arrived_basis`: the force-push that produced it, else the
  first CI start on it, else its committed date — GitHub keeps no push
  time);
- a thread starts at its first comment; undated open threads become a
  separate problem with an unknown start.

Treat the verdict as a lead to check against the PR, not a judgement.

Run the audit with `/dev10x:request-review --audit [--repo R]`. It
writes nothing.

## Periodic sweep under foreman

A foreman run can add the audit as an optional, read-only sweep: call
`review_readiness_audit` once per repo in the manifest when the overseer
writes its periodic status, and list `SENT-NOT-READY` rows in the
status. It must not comment on PRs, request review or change labels —
the sweep reports, the supervisor decides. Leave it off unless the
supervisor asked for it; it costs one GraphQL query per repo per sweep.
