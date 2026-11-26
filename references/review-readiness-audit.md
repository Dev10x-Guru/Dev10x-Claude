# Review Readiness Audit (GH-1834)

Split out of [`review-readiness.md`](review-readiness.md) when the
Fixups condition (GH-2008) pushed that file past the 200-line budget.
That file defines the check run before a reviewer is pinged; this one
looks back at PRs already sent.

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
It also does not read the Fixups condition, which needs a checkout of
the PR branch.

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

Run the audit with `/dev10x-coding:request-review --audit [--repo R]`. It
writes nothing.

## Periodic sweep under foreman

A foreman run can add the audit as an optional, read-only sweep: call
`review_readiness_audit` once per repo in the manifest when the overseer
writes its periodic status, and list `SENT-NOT-READY` rows in the
status. It must not comment on PRs, request review or change labels —
the sweep reports, the supervisor decides. Leave it off unless the
supervisor asked for it; it costs one GraphQL query per repo per sweep.
