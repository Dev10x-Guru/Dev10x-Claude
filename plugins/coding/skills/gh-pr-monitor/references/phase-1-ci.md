# Phase 1: CI Monitoring

## Phase 1: CI Monitoring (server-side wait, preferred)

The supervisor does not loop on CI itself.

### Primary mechanism: `ci_check_status(wait=true)` (GH-675)

**Preferred — call `mcp__plugin_dev10x_cli__ci_check_status`
directly with `wait=true`.** It polls **server-side** to a
terminal verdict (`green` / `failing` / `conflicting`) with no
Bash, no `sleep`, and no background sub-agent:

```
mcp__plugin_dev10x_cli__ci_check_status(
    pr_number={pr_number}, repo="{repo}", wait=True)
```

This returns the same verdict JSON the `haiku-ci-poll` micro-agent
emits, so the **Interpret verdict** table below applies unchanged.

**A red advisory check no longer cuts the wait short (GH-1065).**
The wait used to end the moment ANY check failed, so with a
non-required bot check environmentally red — `claude-review` during
an org-wide API cap, say — every call returned `failing` instantly
while `test` / `axe` / `check` were still pending. That verdict is
unactionable: pending is not green, so the only response was to
poll again by hand, precisely the work this call exists to absorb.
The wait now settles the remaining legs first and returns the full
verdict with the failed leg named in `checks` and `pending: 0`. A
failed **required** check still returns immediately — it blocks the
merge regardless of the other legs. Pass
`wait_out_pending=False` for the old return-on-first-failure
behaviour; the poll budget still bounds the loop either way.

**Why this is preferred over the haiku-ci-poll micro-agent:** the
micro-agent's `sleep 30` loop hits a permission boundary in some
environments and returns after a **single** poll with a
non-terminal verdict, reporting "I can execute immediate Bash
commands but not long-running background polling loops" (GH-675).
The orchestrator then never receives a terminal verdict. Polling
server-side via `ci_check_status(wait=true)` removes the `sleep`
loop, the Bash dependency, and the `gh-pr-checks-watch` friction
class entirely.

### Fallback: dispatch the `haiku-ci-poll` micro-agent

Use the micro-agent (see "Micro-agent A" in
[`phase-micro-agents.md`](phase-micro-agents.md)) only when
`ci_check_status(wait=true)` is unavailable (older plugin version)
or you specifically want the poll to run in the background while
the supervisor works on Phase 2. It loops `ci-check-status.py`
until the verdict changes from `"pending"` and returns the final
JSON.

```
Agent(
    subagent_type="general-purpose",
    model="haiku",
    run_in_background=True,
    max_turns=50,
    description="Poll CI for PR #{pr_number}",
    allowed_tools=[<see Micro-agent A spec>],
    disallowed_tools=[<see Micro-agent A spec>],
    prompt=<see Micro-agent A prompt, with {pr_number}, {repo} filled in>
)
```

Because `run_in_background=True`, the supervisor receives a
completion notification when the poll ends — but that notification
carries NO content, so the micro-agent must deliver the verdict JSON
via `SendMessage(to="main", …)` (GH-776); bare stdout is never read.
A completion notification with no `SendMessage` means the poll
finished WITHOUT delivering — nudge it once, then fall back to
`ci_check_status(wait=true)`. The supervisor can work on Phase 2
(thread scan) or other unrelated tasks in the meantime. If the
micro-agent returns after a single poll with a non-terminal verdict
(the GH-675 sleep-permission limitation), fall back to
`ci_check_status(wait=true)`.

### Interpret verdict

When the micro-agent returns, parse the JSON. The `verdict` field
drives the next action:

| `verdict`       | Supervisor action |
|-----------------|-------------------|
| `green`         | Run Post-CI comment re-check (below), then Phase 2 |
| `failing`       | Read `checks` array, branch on failure type (see CI Failure Handling) |
| `conflicting`   | Rebase onto base branch (see Conflict Handling) |
| `empty`         | Re-dispatch ci-poll after 60s — GitHub hasn't registered checks yet |
| `timeout`       | Micro-agent hit the 50-turn cap. Re-dispatch with note "session #2"; if it times out twice, surface to user |

**A `green` verdict does not mean every check ran (GH-1410 Finding
2).** A check bucketed `skipping` is excluded from the verdict
computation entirely, so a review workflow that never fired — most
commonly because the PR was still a draft (see Phase 0.5) — reads as
`green` exactly like one that ran and passed. Before treating `green`
as "reviewed", read the `skipping_checks` array in the verdict JSON
(names of every skipped check) and confirm none of them is a review
gate this PR needed. This is a payload-level guard independent of
Phase 0.5 — Phase 0.5 catches the whole-run case; this catches a
single unexpectedly-skipped check later in the same run.

**A deliberately skipped Claude review is not a missing gate
(GH-1756, GH-1764).** Read `disabled_checks` from the same verdict
JSON: a `claude-review` / `hygiene-review` listed there was switched
off on purpose (the `skip-claude-review` label, or
`CLAUDE_REVIEW_ENABLED=false` as a repo or org variable), and
`review_disabled_reason` names which. Report "Claude review disabled
(<reason>)" and continue to Phase 2; it never blocks the merge
(`references/pr-merge-policy.md` § Reading Review Signals). Do not
probe labels or variables yourself — `ci_check_status` owns that
lookup. A review name in `skipping_checks` but absent from
`disabled_checks` is a review that never fired: flag it. A skipped job
still settles, so a `wait_for=["claude-review", "hygiene-review"]`
wait ends normally.

**Pending verdict is impossible** at this layer — the micro-agent's
contract is "loop until verdict ≠ pending". If the supervisor ever
sees `"pending"` in the returned JSON, something is wrong with the
micro-agent prompt; treat as `BLOCKED: ci-poll-protocol-violation`
and stop.

**Draft-to-ready SKIPPED guard (GH-774):** The script returns
`"empty"` when all checks are SKIPPED (non_skipping == 0). The
supervisor must re-dispatch after 60s rather than treating this
as green — GitHub re-registers checks after `gh pr ready`. The
micro-agent already returns `"empty"` not `"green"` in this case.

**Why not loop in the supervisor's session?** Because each loop
iteration costs a supervisor turn, and supervisor turns are
expensive context. Pushing the loop into a haiku sub-process
saves cost AND removes any chance of the loop "deciding" to do
something else mid-wait.

### CI Failure Handling

The supervisor handles CI failures directly — it has full
reasoning context, sees the BLOCKED OPERATIONS list and memory
guardrails loaded in Step 0, and can ask the user before any
ambiguous change. There is no `BLOCKED:` status line in this
architecture; the supervisor is the parent, and it decides
in-band.

Anti-pattern (the incident in GH-68 incident #2): a background
haiku agent received `verdict: failing`, ran `Edit` to "fix" a
test it had no business changing, created a fixup that
re-introduced reviewer-rejected code, then auto-grooved the
regression. The new architecture removes this failure surface
because the supervisor's reasoning capacity is in the loop.

| Failure Type | Supervisor action |
|---|---|
| ruff/black/isort | Run the formatter; commit via `Skill(dev10x:git-commit)` |
| mypy / flake8 / import errors | Apply fix; commit via `Skill(dev10x:git-commit)` |
| pytest failures | Read the test + code; decide between fix and ticket; act |
| Coverage < 100% | Add tests for uncovered lines |
| gitlint (title > 72 chars) | Reword via `git commit --amend` or `Skill(dev10x:git-groom)` |
| git-history-linting (fixup! only) | Delegate to `Skill(dev10x:git-groom)` — groom enforces its own preconditions, including the thread-open refusal (GH-68, Fix E) |

**Before any commit/groom**, the supervisor MUST:

1. Re-read the BLOCKED OPERATIONS extracted in Step 0. If the
   intended action matches any directive (e.g., `leave UNSQUASHED`
   vs. an autosquash plan), stop and ask the user.
2. Apply the self-introduced regression guard (GH-68, Fix C):
   read `git reflog`, identify commits authored within this
   monitoring session. If HEAD is one of them AND the failing
   test was passing on `HEAD~1`, recover with `git reset --hard
   HEAD~1` or `git revert HEAD` instead of a counter-fixup. This
   guard exists because the supervisor itself might have just
   pushed the regression a few turns ago.
3. Re-dispatch `haiku-ci-poll` after the fix lands; wait 60s
   first so GitHub registers new check suites.

### Conflict Handling

**Merge-state check first (GH-904 F4).** On ANY unexpected
branch-head change (e.g. a maintainer ran GitHub's "Update
branch", or the local HEAD sha no longer matches what this
monitor last observed), resolve the PR merge state via
`mcp__plugin_dev10x_cli__pr_get` (read `state` / `mergedAt`) —
same pattern as `dev10x:gh-pr-respond`'s Merge-State Check
preamble — BEFORE re-dispatching `haiku-ci-poll` or delegating to
`dev10x:git-groom` for a rebase. If `state == "MERGED"`, stop:
do not rebase or force-push a branch whose PR already merged.

When `gh pr view` reports `mergeable: CONFLICTING` (and the PR is
confirmed not merged):

1. Resolve the base branch via `mcp__plugin_dev10x_cli__pr_detect`
   (returns `baseRefName`).

2. Delegate the rebase + force-push to `Skill(dev10x:git-groom)` —
   it fetches the base, rebases, and runs the protected-branch
   safety checks before force-pushing. Do NOT call `git rebase` or
   `git push --force-with-lease` directly from this skill: routing
   through the wrapper preserves the autosquash, gitmoji, and
   protected-branch guardrails (see Skill Routing Enforcement in
   `skills/work-on/instructions.md`).

3. If `dev10x:git-groom` reports unresolved conflicts, stop the
   monitor and report the conflicting files to the user.

4. After the wrapper completes the force-push, re-run the Phase 0.5
   readiness check: a push can draft a ready PR (GH-1731), and a draft
   gets no CI. Then wait 30 seconds for GitHub to re-compute
   mergeability and re-run CI, and restart the Phase 1 loop.

### Post-CI Comment Re-check (REQUIRED)

**Hard rule (GH-465):** After CI returns `green`, the supervisor
re-scans for review comments before marking the PR ready. CI
hygiene reviews post comments during the CI run, so the initial
comment scan at session start can miss them.

Dispatch `haiku-thread-scan` (Micro-agent B). It returns:

```json
{
  "unresolved_threads": [...],
  "body_findings": [...],
  "top_level_findings": [...],
  "needs_disposition": [...]
}
```

Sum ALL FOUR arrays (incl. `needs_disposition`, GH-808 F1). If any
are non-empty → enter Phase 2. If all four are empty AND blocking
bots are at head (`references/bot-review-wait.md`, GH-1832) → mark
the PR ready (`gh pr ready {pr_number}`) and proceed to Phase 2.5. A
non-blocking INFO in `needs_disposition` counts — it must be
addressed or explicitly deferred before the PR reads clean.
