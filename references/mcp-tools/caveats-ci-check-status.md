# MCP Tool Caveats — `ci_check_status`

Behavioural caveats for the only sanctioned CI-wait path, moved out of
`.claude/rules/mcp-tools.md` § Canonical Parameter Shapes (GH-1606).

- `ci_check_status(wait=true)` no longer ends its wait on a failed
  NON-required check while other legs are pending (GH-1065). The
  blended `verdict` flips to `failing` the moment ANY check fails, so
  one environmentally-red advisory bot — `claude-review` during an
  org-wide API cap — returned `failing` instantly with three legs still
  pending, and the caller could only re-poll by hand. `wait_out_pending`
  (default `true`) settles the remaining legs first, then returns the
  full verdict with the failed leg named in `checks` and `pending: 0`. A
  failed **required** check still returns immediately — it blocks the
  merge however the other legs land — and the poll budget still bounds
  the loop, so a leg that never settles ends the wait rather than
  hanging it. Pass `wait_out_pending=false` for the old
  return-on-first-failure behaviour.
- `ci_check_status(wait=true)` takes `wait_for`, a list of check names
  that must settle before the wait ends **even when a REQUIRED check
  has already failed** (GH-1138). `wait_out_pending` does not cover
  that case by design — a failed required leg blocks the merge however
  the rest land, so returning at once is right for a caller deciding
  whether to merge. It is wrong for a caller that must not rewrite
  history until the review bots have anchored their comments: on any
  branch carrying `fixup!` commits the required `git-history-linting`
  leg fails **by design** until squash, so "required red + advisory
  legs pending" is a routine mid-review state, not an edge case. A
  Phase 4.6 dispatcher hit exactly that, read the contract correctly as
  "this will not wait", and hand-rolled a `while … gh pr checks …
  sleep 30` loop through the `Monitor` tool — which no Dev10x hook
  validated — then stalled on a prompt. Pass
  `wait_for=["claude-review", "hygiene-review"]` instead. The poll
  budget still bounds the wait, and `conflicting` still returns
  immediately. `Monitor` is on the same PreToolUse validator chain
  as `Bash`, and both `ci-loop-handrolled` and `watch-loop-handrolled`
  are `hook_block: true`.

  **Regression window — GH-1138 through v0.96.0 (GH-1211, GH-1212).**
  For that span the sentence above was aspirational. `hooks.json`
  registered the `Monitor` matcher, but `_validate_bash_body` exited on
  `tool_name != "Bash"` before a single validator ran, so the
  registration was inert: DX001–DX016 never saw a Monitor command, and a
  hand-rolled poll loop routed through `Monitor` reached the supervisor
  as a raw permission prompt that no allow rule can answer. Two narrower
  gaps closed alongside it — the loop patterns were single-line, so a
  `sleep` several lines below `do` could not match (patterns compile
  without `DOTALL`), and `skill_redirect.should_run`'s fast-path token
  filter dropped any command naming none of `commit`/`push`/`checks`/…
  before the rule engine saw it. A loop is matched on its shape now, not
  on the command inside it. Which steer a *PR-shaped* loop receives is a
  separate, still-open question: `gh pr view` is matched by an earlier
  rule, so such a loop gets the one-shot `pr_get` steer rather than
  `dev10x:gh-pr-monitor` (tracked on #1100 E21).
- `ci_check_status(wait=true)` budgets its own wait against the
  transport ceiling, and `max_polls` is a request rather than a grant
  (GH-1288). The cap used to be summed inline as `initial_wait +
  poll_interval * max_polls + 60` with nothing bounding it: the default
  came to 1320s — above both deaths GH-1288 reports at ~1137s — and
  `max_polls=500` bought a four-hour one. `dev10x.monitor` now asks
  `polls_within_budget` what `MAX_TOOL_CALL_SECONDS` affords and passes
  that down, so the default 40 is served as 32 (990s of polling under a
  1080s cap). **A slow PR is covered by calling twice, not by asking for
  longer** — the poll count is reduced rather than the subprocess merely
  capped, precisely so the loop ends on its own terms and returns a
  verdict instead of being killed mid-poll and surfacing as a non-zero
  exit. This is the same clamp `run_tests` and `run_node_tests` take,
  reaching the one long-running tool that had been left restating the
  budget in prose.

- `ci_check_status(wait=true)` survives a transient `gh` failure
  mid-poll (GH-1420). `read_checks` exits on any unrecognised non-zero
  `gh pr checks` exit and the loop called it every iteration, so one
  rate limit at poll 30 of 40 discarded `initial_wait` plus thirty
  intervals and reported a transient condition as an infrastructure
  failure. A failed probe is now treated as "no news": the last good
  result is kept and the wait continues, giving up only after **three
  consecutive** failures — tolerating a blip is the goal, outlasting an
  outage is not, and the poll budget still bounds the whole loop. The
  up-front fast-path probe is tolerated on the same terms. A run where
  *every* probe failed reports that explicitly rather than reporting
  `empty`, which would read as "CI registered no checks at all".
  A probe whose `gh` call hits its 30s subprocess timeout is tolerated
  the same way (GH-1518). This is the one bounded exception to "never
  retry a bounded timeout of our own": the next poll was already
  scheduled, so nothing is re-run that the loop would not have run
  anyway. Because a timed-out probe costs seconds the poll count never
  budgeted, the loop also holds a wall-clock deadline (the poll budget
  plus 60s grace, still under the 1080s cap), so alternating timeouts
  end the wait on time instead of outliving the transport.

- `ci_check_status(wait=true)`'s up-front probe honors `wait_for`
  (GH-1609).
  A required red on the first probe no longer ends the wait while a
  named leg is unsettled.
  The payload also carries `is_draft`.
  A draft with skipped checks adds `verdict_caveat` (GH-1604).
  The `verdict` itself is unchanged, so a draft can still read
  `green` — check the caveat.

- `ci_check_status(wait=true)` probes once before sleeping and returns
  straight away when the verdict is already terminal (GH-1088; see the
  GH-1609 `wait_for` exception above). A call
  that lands after CI finished costs one API round trip instead of the
  60s `initial_wait` it used to pay unconditionally, so a worker that
  reaches the check late is no longer parked behind a wait for a
  verdict GitHub had already decided. Checks that have not registered
  yet summarize as `empty`, which is not terminal — a genuine
  post-push call still waits normally.

- `ci_check_status` corroborates a zero before reporting one, and says
  which source produced it in `checks_source` (GH-1376). `gh pr checks`
  under-reports: PR #1372 had a completed, successful `PR Hygiene
  Review` run that the Actions runs API listed and the CLI did not,
  persistently and across two sessions. Because this tool is the only
  sanctioned CI-wait path — `ci-loop-handrolled` and
  `watch-loop-handrolled` are `hook_block: true` — an uncorroborated
  zero gets acted on. So a zero read is now cross-checked against
  `repos/{repo}/actions/runs?branch=<head>`, filtered to the PR's head
  SHA, and `checks_source` reports `confirmed-zero` (both sources
  agree), `runs-api` (the CLI was wrong and the verdict is built from
  the runs), or `gh-pr-checks`. A runs-API call that cannot be made
  returns `{"error": …, "undetermined": true}` rather than a zero — an
  unreadable second source is not evidence about the first. The two
  extra calls are paid only on the zero path and on a green (next
  bullet), so a pending or failing poll costs exactly what it did
  before. `required_only` reads are exempt: an empty required set is
  normal on an unprotected base (ADR-0024) and the runs API cannot say
  which runs the host requires.

- `ci_check_status` corroborates a **green** too (GH-1679). Right after
  a force-push `gh pr checks` listed 8 of a head's 13 checks, all
  passing, while the CI Gate run for that head was still `in_progress`
  — a `wait=true` call returned `green` and an unattended merge would
  have shipped ahead of the test suite. A green is now checked against
  the Actions runs for the head SHA: any run not yet `completed` turns
  it into `pending`, with `checks_source: "runs-api-pending"` and the
  run names in `running_runs`, and the wait continues. A cross-check
  that cannot be made leaves the green standing with a stderr note —
  unlike the zero path, the green was itself observed. Separately, the
  up-front fast-path probe now honours `wait_for` (it used to ignore
  it, so a partial green returned before the named legs registered),
  and a `wait_for` call reports `unregistered`: the named legs no check
  carried, so a wait that ended on the budget does not read as settled.

- **`required_verdict: "empty"` is a normal merge-time state on this
  repo, not a pending one (GH-1381).** `develop` registers no required
  status checks (ADR-0024), so `required_verdict` is `"empty"` on every
  green, mergeable PR — it is the terminal value the field settles on,
  never a step on the way to `"green"`. Two workers each sat on a
  fully-passed PR without merging (#1362 at 7/7, #1360 at 6/6) because
  they read `empty` as "required checks haven't passed yet"; both
  needed orchestrator intervention. The blended `verdict` — not
  `required_verdict` — is what a merge decision branches on here:
  `verdict: "green"` means merge, regardless of what `required_verdict`
  says. This is distinct from the transient `empty` two bullets up,
  which describes `verdict` before GitHub has registered any checks at
  all; `required_verdict: "empty"` persists for the PR's whole life on
  an unprotected base.
