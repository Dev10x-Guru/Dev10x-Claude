# 24. One always-runs check gates `develop`; a path-filtered check cannot

Date: 2026-09-14

## Status

Proposed

Every existing ADR in this repo is `Accepted`; this is the first
`Proposed` one, and the status is load-bearing rather than
decorative. What the decision *rules out* is settled and actionable
today. What it rules *in* depends on a prerequisite that does not
exist yet (§ Prerequisite), so recording it as Accepted would assert
a protection posture the repository does not have. Flip to
**Accepted** once the prerequisite lands and § Verifying it confirms
the rule is live. If that has not happened within a release cycle,
the right move is to amend this ADR — not to leave it drifting.

Records the decision on
[GH-1283](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1283),
including the finding that the ticket's own proposed fix is unsafe.

Answers — rather than closes — the repo-configuration finding that
[`skills/gh-pr-merge/instructions.md`](../../skills/gh-pr-merge/instructions.md)
Check 2b has re-reported on every bundle since GH-1107.

## Context

`develop` has no branch-protection rule at all. This is not a matter
of degree — `GET /repos/Dev10x-Guru/Dev10x-Claude/branches/develop/protection`
answers `404 Branch not protected`. Consequently
`ci_check_status` reports `required_verdict: "empty"` and tags every
leg `required: false`, exactly as
[`src/dev10x/skills/monitor/ci_check_status.py`](../../src/dev10x/skills/monitor/ci_check_status.py)
documents it should when the host marks nothing required.

The cost is not that CI is unwatched — it is watched, and
`Dev10x:gh-pr-merge` runs nine pre-merge validations against it. The
cost is that **those validations gate nothing**. With no required
check, GitHub merges an armed PR the instant CI settles, and that
instant can fall between "mark ready" and the gate's first call. In
the run behind GH-1107 finding 3, a PR merged before the child
session invoked the skill at all, so none of the nine ran. Check 2b
correctly short-circuits to post-merge verification in that case, but
by then the merge has happened. A convention that a race can skip is
not a gate.

The finding was observed across four PRs in one session (#1273,
#1276, #1277, #1280) and raised in three consecutive work bundles
without being actioned. Re-reporting it costs a slot in every bundle
and changes nothing, which is its own argument for deciding rather
than deferring again.

### Why "just require everything" is wrong here

The naive fix — mark every leg required — would deadlock this
repository's own shipping pipeline. Two of the legs are red under
normal, correct operation:

- **`hygiene-review` triggers only on `opened` / `ready_for_review`.**
  It never re-runs on a push. Requiring it would leave any
  force-pushed PR permanently missing a required check, with no way
  to re-trigger it short of closing and reopening the PR.
- **`claude-review` is environmentally flaky.** It goes red on an
  org-wide API cap — a condition unrelated to the diff, which the
  author cannot fix and a retry cannot reliably clear. GH-1065 exists
  because that flakiness already distorts the blended verdict.

**`git-history-linting` is not excluded — it does not exist here.**
GH-1283 lists it among this repo's legs, and so do several Dev10x
reference documents, but no workflow under `.github/` defines it and
it appears in no check run on `develop` (`test`, `floors`, `bench`)
or on a PR. The name is inherited from another repository's setup.
Nothing needs deciding about it; a future reader who finds the same
claim in `.claude/rules/mcp-tools.md` or
`skills/gh-pr-monitor/references/ci-failure-patterns.md` should read
those as generic guidance, not as a description of this repo.

A third leg is excluded for a duller but harder reason:
**`Scanner unit tests` is not a usable context name.** Three separate
workflows emit a job by that name — `privacy-audit.yml`,
`skill-eval-gaps.yml`, and `skill-cli-friction.yml` — so it appeared
three times in `gh pr checks 1280`. Branch protection matches
contexts by name, so requiring it would be ambiguous at best.
Renaming those jobs is a prerequisite to ever requiring them, and is
out of scope here.

The remaining legs are `bench`, `lessons-learned`, `close-issues`,
`Audit changed files`, `Scan changed skill docs`, and `Check gated
skills for eval coverage`. `bench` is a backpressure gate whose
baselines are hardware-sensitive — GH-1080 already downgraded its
local behaviour to a warning for that reason — so making it
merge-blocking would import that instability into the merge path.
`close-issues` and `lessons-learned` run *after* merge on this
repo's PRs and so cannot gate one. The three audit scanners are
plausible future candidates; they are left out of the first cut
because `test` and `floors` already carry the correctness and
policy signal, and a gated set is cheaper to widen than to narrow
once people are working around it.

### The ticket's proposed fix would deadlock the repo

GH-1283 names `test` and `floors` as "the obvious candidates". They
are the right *substance*. They cannot be required *directly*, and
finding out why is the main result of this ADR.

**Both are path-filtered.** `floors`
(`pytest-coverage-floors.yml:27-33`) fires only for `src/dev10x/**`,
`tests/**`, `pyproject.toml`, or its own workflow file. `test` fires
only for `hooks/**` / `tests/hooks/**` (`pytest-hooks.yml:11-17`) or
the `servers/**` / MCP paths in `pytest-servers.yml`.

A required status check that never runs does not pass — GitHub holds
it at *Expected — waiting for status to be reported* and the PR
cannot merge, ever. So requiring these two would permanently block
every PR that touches only docs, `skills/`, `references/`,
`.claude/`, or `.github/workflows/` — **including the PR that
introduces this ADR.** The fix as stated converts a gate that
under-blocks into one that over-blocks to the point of deadlock.

**`test` is also an ambiguous context name.** Two workflows define a
job with the id `test` — `pytest-hooks.yml:24` and
`pytest-servers.yml:70` — and neither sets a `name:`, so both emit a
check called `test`. This is the same defect that disqualifies
`Scanner unit tests`; it simply has two claimants instead of three.

## Decision

**D-1. Require exactly one context, and make it a check that always
runs.** The required context must be a small aggregator job — no
`paths:` filter, `if: always()`, `needs:` every substantive leg —
that passes when its dependencies passed or were legitimately
skipped, and fails otherwise. Requiring that one context gives
GitHub something that registers on *every* PR while keeping the
real work path-filtered. This is the standard resolution for
required-plus-path-filtered, and it is a prerequisite, not an
alternative, to the ticket's request.

**D-2. Nothing is required until that job exists.** Today's honest
state is advisory-only, and this ADR is the durable record of *why*
— not an oversight, and not a decision to stay advisory forever.
The work is tracked as
[GH-1298](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1298).

**D-3. The substantive legs behind the aggregator are `test` and
`floors`.** That part of GH-1283's proposal stands: both are
deterministic and fast enough not to distort the pipeline (`test`
~51s, `floors` ~4m19s, as of #1280). `bench`, the audit scanners,
and the two post-merge jobs stay outside it for the reasons above.
Renaming one of the two `test` jobs is part of the prerequisite
work — an aggregator's `needs:` refers to job ids within one
workflow, so the collision must be resolved before the aggregator
can name them unambiguously across workflows.

**D-4. Every other leg stays advisory, deliberately.** This is the
recorded answer to "which legs are merge-blocking", not an omission.
A future session that re-derives "no required checks" as a finding
should read this ADR and stop, unless the *set* is what it disputes.

**D-3. `strict: false` — do not require the branch to be up to date
before merging.** `strict: true` forces every PR to rebase whenever
`develop` moves, which on a repo that merges several bundles a day
means near-continuous forced rebases. Worse, it interacts badly with
the review cycle: a rebase after review fixups exist rewrites the
SHAs that review-thread permalinks reference, which
`Dev10x:git-groom` Phase 0 and the work-on per-batch re-sync rule
both go out of their way to prevent.

**D-4. `enforce_admins: false`.** This is a solo-maintained
repository. An escape hatch that the maintainer can use deliberately
is worth more than the marginal enforcement of closing it, and
closing it would make a broken-CI recovery require deleting the
protection rule rather than overriding it once.

**D-5. No required reviews.** `supervisor_review` is `none` for this
repo (ADR-0022 D-2, confirmed live via `supervisor_review_status()`:
`{"supervisor_review": "none", "pinned": true}`); adding a
GitHub-level review requirement would contradict the durable project
fact and block the solo-maintainer merge path outright.

**D-6. When the rule is applied, use `strict: false` and
`enforce_admins: false`.** `strict: true` forces every PR to rebase
whenever `develop` moves, which on a repo merging several bundles a
day means near-continuous forced rebases — and it interacts badly
with the review cycle, since a rebase after review fixups exist
rewrites the SHAs that review-thread permalinks reference, which
`Dev10x:git-groom` Phase 0 and the work-on per-batch re-sync rule
both go out of their way to prevent. `enforce_admins: false` keeps a
deliberate escape hatch for the sole maintainer; closing it would
make broken-CI recovery require deleting the protection rule rather
than overriding it once.

## Prerequisite

Applying anything was blocked on
[GH-1298](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1298),
which is a code change and therefore out of this ticket's declared
scope ("Files Changed — None in-repo"):

1. Give the two `test` jobs distinct check names.
2. Add an always-runs aggregator job — no `paths:` filter,
   `if: always()`, `needs:` the substantive legs — that fails unless
   each dependency succeeded or was skipped.
3. Then require that single context.

**Steps 1 and 2 have landed.** `.github/workflows/ci-gate.yml` folds
the three legs into one workflow — `needs:` reaches only jobs in the
same file — under the names `hook-tests`, `server-tests` and
`floors`, each gated by a job-level `if:` against a `changes`
classifier rather than an event-level `paths:` filter. The aggregator
is `ci-gate`. Step 3 is a repository-configuration change and remains
the maintainer's to make; until it does, this ADR stays `Proposed`.

The shape:

```json
{
  "required_status_checks": { "strict": false, "contexts": ["ci-gate"] },
  "enforce_admins": false,
  "required_pull_request_reviews": null,
  "restrictions": null
}
```

applied with `gh api -X PUT
repos/Dev10x-Guru/Dev10x-Claude/branches/develop/protection --input
<payload.json>`, reverted symmetrically with `-X DELETE`.

**Do not apply a payload naming `test` or `floors` directly.** `test`
no longer exists as a context at all. `floors` does, and since
GH-1298 it reports `skipped` rather than nothing on a docs-only PR —
so requiring it would no longer deadlock, it would pass *vacuously*,
which is the failure mode that makes a merge gate lie. Require
`ci-gate`, which refuses to go green unless at least one dependency
actually ran.

## Verifying it

Once applied, the write is a request, not a receipt — read the rule
back rather than trusting the `PUT` response:

```bash
gh api repos/Dev10x-Guru/Dev10x-Claude/branches/develop/protection \
  --jq '.required_status_checks.contexts'
```

Then, on the next PR, `ci_check_status` should report
`required_verdict` as something other than `"empty"`, and the
aggregator should carry `required: true`. That second signal is the
one that matters: it is the same field `Dev10x:gh-pr-merge` Check 2
branches on, so it proves the skill can see what the host enforces.
Verify on a **docs-only** PR specifically — that is the case the
naive payload breaks.

## Consequences

**The standing finding is answered, and the merge race is not yet
closed.** Those are separate outcomes and this ADR delivers only the
first. Check 2b now cites a recorded decision instead of re-filing
the symptom every bundle; the timing hole stays open until the
prerequisite lands. Saying so is the point — three bundles re-raised
this because nothing recorded either half.

**A future session must not "just apply" GH-1283.** The obvious
reading of the ticket produces a deadlocked repository. This ADR is
the durable record of that, and it is why the ticket should not be
closed as a one-command fix.

**When the aggregator lands, a red `test` or `floors` blocks the
merge for real**, including for the maintainer, unless they use the
D-6 escape hatch. That is the intent, but a flaky failure in either
leg then becomes a shipping blocker rather than an advisory
annoyance — if that starts happening, fix the flake or drop the leg
from the aggregator's `needs:`, and amend this ADR to say so.

**The two excluded review legs remain unenforced.** Nothing stops a
PR merging with `claude-review` red. That is accepted: their value is
in what they surface to the author, and `Dev10x:gh-pr-monitor`
already routes their comments through `Dev10x:gh-pr-respond`.

**Renaming the three `Scanner unit tests` jobs becomes a
prerequisite** for ever extending the required set to the audit
workflows. Worth a follow-up ticket; not blocking this decision.
