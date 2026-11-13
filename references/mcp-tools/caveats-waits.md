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
| `bot_at_head` | `bot_review_status` reports a bot (or the named `bot`) at the current head | the PR is no longer open |

- `observed` always carries `state`, `merged` and `head_sha`, plus the
  condition's own evidence: `baseline_sha`, `review_states` or
  `bot_review`.
- A poll that cannot read the PR is recorded in `probe_errors` and the
  wait continues; the Gateway already retried transient `gh` failures.
- `approved` reads review verdicts only.
  It does not know about branch protection, CODEOWNERS or required
  reviewer counts; `merge_pr` remains the authority on mergeability.

### `bot_at_head` delegates to `bot_review_status` (GH-1857)

There is one definition of "a bot reviewed the head", and it lives in
`bot_review_status` (see `caveats-issues-and-push.md`).
`bot_at_head` reads the same GraphQL node each poll and is met when a
bot's row says `at_head: true`:

- a bot that submits reviews is at head when its newest review's commit
  is the head (`at_head_basis: "sha"`);
- a bot that only comments is at head when its last activity is not
  older than the head (`at_head_basis: "timestamp"`).

Bot-ness comes from the GraphQL account type alone, so a human login
such as `claude-fan` never counts.
`bot` is a login or glob, `[bot]` suffix optional; without it any bot
counts.
`observed.bot_review` carries the matching row and `observed.bots` the
logins considered.
`observed.truncated` names each connection that ran past its page
(GH-1885).
A `reviews`, `reviewThreads` or `comments` entry means a bot outside
that 100-item window is invisible, so a timeout means "not seen", not
"not reviewed".
A `checkSuites` entry hides no bot: it means only that the head-push
time may be later than the real push, which makes "at head" stricter.
It still does not judge a review's verdict or whether findings were
addressed — `bot_review_status`'s `ready` and `reasons` do that.

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
- `http` never follows a redirect: a 3xx is reported as its own status,
  and counts as met when no `expect_status` is set (GH-1885).
- `http` refuses link-local addresses (169.254.0.0/16, fe80::/10), home
  of the 169.254.169.254 metadata address most clouds use.
  A literal link-local host is a rejected argument.
  For a name, the address the socket actually connected to is checked,
  and a link-local one is closed before any request is written.
  That ends the wait `unreachable` however the name resolved earlier.
  Loopback and private addresses stay allowed, and so do metadata
  addresses outside link-local such as AWS's IPv6 `fd00:ec2::254`.
  `HTTP_PROXY` / `HTTPS_PROXY` are ignored: the probe always connects
  directly, so the checked address is the target's, never a proxy's.
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
