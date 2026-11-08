# Caveats: `pr_wait` and `wait_for`

Read before relying on a wait tool's payload (GH-1833).
Both tools replace the one-off polling scripts sessions used to write
per condition, which skipped the transport budget (GH-1288), the retry
policy (GH-1423) and the subprocess cap (GH-1422).
`pr_wait` reads GitHub through the Gateway, so it also inherits the
retry policy and the subprocess cap; `wait_for` makes one attempt per
probe and reports a failed probe in `observed`.

## Both tools

- **One call never outlives the transport.**
  `pr_wait` grants only the polls that fit under `MAX_TOOL_CALL_SECONDS`
  (`polls_granted`, `budget_clamped`) and also stops at that wall-clock
  ceiling when slow GitHub calls eat into it, so `polls` can end below
  `polls_granted`; `wait_for` clamps `timeout` to the same ceiling
  (`timeout`, `timeout_requested`, `clamped`).
  Asking for more does not buy more.
- **A wait longer than the budget is a background job, not a bigger
  number.**
  Re-call the tool, or arm a background Monitor that re-invokes it and
  wakes the session when `met` turns true.
  Do not write a polling script to get around the cap.
- **`met: false` is an answer, not an error.**
  An `{"error": ...}` payload means the arguments were invalid or, for
  `pr_wait`, no poll could read the PR at all.
  Branch on `met` / `timed_out` / `unreachable`, never on the presence
  of `observed`.
- **Both run on one poll loop** (GH-1852): `dev10x.domain.polling`
  holds the deadline, the loop and the `_sleep` / `_clock` test seams.

## `pr_wait`

| `until` | Met when | Ends early (`unreachable`) when |
|---------|----------|---------------------------------|
| `merged` | the PR is merged | closed without merge |
| `closed` | closed **without** merge | merged |
| `merged_or_closed` | closed either way | never |
| `head_changed` | head SHA differs from `since_sha` (default: first head read) | the PR is no longer open |
| `approved` | some reviewer's latest verdict is `APPROVED` and none is `CHANGES_REQUESTED` | the PR is no longer open |
| `bot_at_head` | a bot-authored PR review's `commit_id` equals the current head | the PR is no longer open |

- `observed` always carries `state`, `merged` and `head_sha`, plus the
  condition's own evidence: `baseline_sha`, `review_states` or
  `bot_review`.
- A poll that cannot read the PR is recorded in `probe_errors` and the
  wait continues; the Gateway already retried transient `gh` failures.
- `approved` reads review verdicts only.
  It does not know about branch protection, CODEOWNERS or required
  reviewer counts; `merge_pr` remains the authority on mergeability.

### `bot_at_head` is deliberately narrow

It answers one question: has a bot submitted a **PR review** anchored
to the current head commit?
`bot` names the login (the `[bot]` suffix is optional); without it, any
reviewer whose account type is `Bot`, or whose login ends in `[bot]`,
counts.

It does not read issue comments, check runs, or a review's verdict, and
it does not decide whether the bot's findings were addressed.
A bot that comments instead of reviewing never satisfies it.
Richer bot-review state is expected from a dedicated status tool; when
that lands, `bot_at_head` should delegate to it rather than grow a
second definition.

## `wait_for`

| `kind` | `target` | Met when |
|--------|----------|----------|
| `file` | path | the path exists |
| `file_text` | path, plus `pattern` | the file contains `pattern` literally |
| `regex` | path, plus `pattern` | `pattern` matches (multiline) |
| `http` | http(s) URL | exactly `expect_status` when set, else any 2xx/3xx |
| `process_gone` | PID, or a `pgrep -f` pattern | the PID is gone / no process matches |
| `time` | ISO-8601 timestamp (naive = UTC) | the moment has passed |

- Relative paths resolve against the caller's `cwd` (GH-979), never the
  server's own directory.
- Text probes (`file_text`, `regex`) read at most the first 4 MiB of the
  file; `file` only checks that the path exists.
- Each `http` probe has its own 10s socket timeout; a refused connection
  is `status: null` with the reason in `error`, and polling continues.
- `process_gone` with a pattern needs `pgrep` on the host.
  A missing `pgrep`, or a `pgrep` failure other than "no match", is
  reported in `observed.error` and does not count as gone.
- **A probe that can never succeed ends the wait at once** (GH-1852):
  `unreachable: true`, `timed_out: false`.
  That covers a missing `pgrep`, a pattern `pgrep` rejects, and a text
  target that is not a readable regular file.
  A file that does not exist yet, a refused connection and a `pgrep`
  timeout are not unreachable — the wait continues.
  A URL with no host or a malformed port is refused as an argument.
- A pattern that matches nothing — a typo included — is met at once.
  Check `observed.pids` on an earlier call when that matters.
- `time` sleeps once, up to the clamped timeout; a moment further away
  returns `timed_out: true`.
