# MCP Tool Caveats — Writes, Labels, Notifications, PR Creation

Behavioural caveats for the write-side tools, moved out of
`.claude/rules/mcp-tools.md` § Canonical Parameter Shapes (GH-1606).
The rule keeps the parameter table; read this file before calling a
tool it names.

- The `task_index_*` trio is the park family's only sanctioned write
  path (GH-1009, ADR-0018 D5). The store lives at
  `~/.config/Dev10x/task-index/<repo-stem>.yaml`, keyed by the git
  **common dir**, so one index serves a repo and every worktree of it.
  Reaching the file with `Write`/`Edit` — at the new path or the retired
  `.claude/Dev10x/session.yaml` — is a defect twice over: under a repo's
  `.claude/` it trips the self-settings consent gate that no allow rule
  suppresses, and anywhere it bypasses the file lock, so two parallel
  worktrees parking at once lose an entry.
  The retired path is no longer read: the `task_index_get` fallback and the append fold-forward were removed in 0.112.0 (GH-1771).

- `pr_labels` carries the durable `review:cleared` signal (GH-1008).
  `dev10x:gh-pr-request-review` reads it before the stand-by clearance
  gate and skips asking when present; the two "I reviewed it" answers
  write it. Because a sign-off covers the commits that were read,
  `dev10x:git-groom` removes it after a force-push — a clearance must
  not survive the rewrite that invalidated it. Both writes are
  idempotent (`add` skips present labels, `remove` intersects against
  the current set first, so clearing an unset label is a no-op rather
  than a 404), so call them unconditionally instead of probing.

  `remove` issues **one `PUT` of the surviving set** rather than a
  `DELETE` per label (GH-1446) — the old loop paid a subprocess plus an
  HTTP round trip each time, on a path `dev10x:git-groom` runs after
  every force-push. Idempotence is unchanged. One property is: a `PUT`
  is a read-modify-write, so a label added by another process between
  the read and the write is dropped, where a per-label `DELETE` was
  immune. The window is one round trip and the no-op guard keeps a
  remove-nothing call from issuing a `PUT` at all — do not remove that
  guard. `issue_labels` still uses the `DELETE` loop; it is not on a
  hot path.

- `notify_slack`, `notify_gchat`, and `pr_notify(action="send")` append
  a failed notification to
  `~/.config/Dev10x/undelivered-notifications.jsonl` (GH-1421,
  GH-1479). The error used to exist only in the call's return value,
  which is fine when an agent surfaces it to a user and useless under
  `foreman`'s unattended crews — the one mode where a lost "crew
  stalled" costs most and nobody is watching. **It is a dead-letter
  log, not a retry queue**: nothing re-sends, nothing reads the file, a
  person greps it. `record_undelivered` never raises, because losing
  the caller on top of the notification turns a missed message into a
  broken crew. `pr_notify(action="prepare")` dispatches nothing and so
  records nothing. `notify_gchat` mirrors `notify_slack`'s retry loop
  (`domain/retry.py`) and dead-letter call through the same shared
  `domain/` policy modules — ADR-0029 deliberately keeps the two
  provider transports as separate modules with no shared base class,
  so `tests/skills/notifications/test_transport_parity.py` guards
  against the next protocol-level fix landing on only one provider.

- `issue_labels` is `pr_labels`'s issue-side counterpart (GH-1322),
  with the same idempotence contract. `issue_edit`'s `labels`
  parameter is additive-only — it calls `gh issue edit --add-label`,
  which never removes or replaces — so its docstring no longer claims
  "replacement label list" semantics. Use `issue_labels(action=
  "remove", ...)` to remove a label and `issue_labels(action="list",
  ...)` to read the current set; `issue_edit` still owns title, body,
  and milestone writes.

- `pr_ready` flips a PR in both directions: omit `undo` to publish a
  draft, pass `undo=true` to convert a published PR back to draft
  (GH-931). Raw `gh pr ready --undo` is hook-blocked like every other
  form, so this parameter is the only sanctioned way to un-publish —
  which is the *safe* direction when a problem surfaces after marking
  ready. The success payload's `draft` is **read back from GitHub**
  since GH-1424, with `draft_verified: true` alongside it; it used to
  be the `undo` argument echoed back, which could never disagree with
  the request. A PR still in the wrong state returns an `ErrorResult`
  naming it, rather than a plausible receipt the caller acts on and
  then fails to merge.

- **`pr_ready` after a push (GH-958, GH-1731).** A
  `--force-with-lease` push resets a published PR back to draft, so a
  ready call that succeeded earlier — including a
  `create_pr(draft=false)` — does not survive a later rebase, amend, or
  groom. Call `pr_ready` after the FINAL push and confirm with a fresh
  `pr_get` that `isDraft` is `false`; otherwise `merge_pr` fails with
  `GraphQL: Pull Request is still a draft`, and the re-ready costs
  another bot-CI round.

  `pr-draft-on-push.yml` (GH-1694) extends this to **every** push, and
  a draft gets no CI here. So any push path — a fixup push, a groom
  force-push, a conflict rebase — reads `isDraft` via `pr_get` before
  the push and again after it, and calls `pr_ready` only when the PR
  was ready before and is a draft now. The rule is conditional on
  purpose: it is a no-op while the workflow lacks its App credentials,
  and a PR that was a draft before the push stays one, because
  readiness was not the push's to grant (under `supervisor_review:
  required` that call belongs to the supervisor). `push_safe` does not
  report the draft state; reading it is the caller's job, since only
  the caller knows which PR the branch belongs to.

- `create_pr` rejects a `job_story` missing any of `**When**` /
  `**<actor> wants**` / `**so <beneficiary> can**` with an
  actionable error before the PR is opened, and `update_pr` moves any
  content trailing the `Fixes:` line above it (GH-945) — so neither
  path can emit a body that trips the hygiene bot.

- `create_pr` always emits at least one `Fixes:` reference (GH-1256).
  The trailer used to be derived from `fixes_url` alone, so linking an
  issue the documented way — `issue_id` — produced a body with no
  trailer, which the hygiene bot rejects. `issue_id` now seeds the
  reference and every `closes=` member is added alongside it, because
  `Closes #N` never fires on a merge to `develop` (GH-958). An explicit
  `fixes_url` still leads, and prose such as `none — self-motivated`
  passes through untouched.

- `create_pr` now reads the created body back and refuses a PR whose
  body carries no `Fixes:` trailer (GH-1274). Deriving a reference was
  never proof one arrived, and a write is a request, not a receipt — so
  the check is a fresh `pr_get`, not a local assertion. The refusal
  names the PR number and URL, because the PR is already open at that
  point and an error that does not identify it strands it; repair the
  body with `update_pr` rather than opening a second PR. A successful
  call carries `fixes_trailer_verified: true`. When the read-back
  itself fails the call still succeeds, with
  `fixes_trailer_verified: false` and a `warning` — an unreadable
  verification is not evidence of a bad body.

- **The trailer closes issues unreliably on a merge to `develop`**
  (GH-1274). One merge closed two of three identical trailers, a later
  session recorded 0 of 7 across two merges, and a third closed two of
  three; both the full-URL and bare-`#N` spellings failed in the 0-of-7
  run, so the form is not the variable. Never treat a merged bundle as
  self-closing: `dev10x:gh-pr-monitor` Phase 3.6 reconciles each link
  against the issue's real state after the merge
  (`fixes_scope.reconcile_link_closure`), and a straggler is reported
  for the supervisor to confirm — not closed silently.

- `merge_pr(use_bot=…)` executes the merge under the GitHub App
  identity so `merged_by` distinguishes a gated merge from a human one
  (GH-1272). Omit it to read the durable `github_app.merge_bot` key.
  It never fails the merge: the payload's `merged_as` is `"bot"` or
  `"engineer"`, and `bot_fallback` names the reason whenever the bot
  path was skipped — `not requested`, `admin/auto merge has no bot
  transport` (neither flag has a REST equivalent), `no installation
  token`, or `bot merge refused: …` when a ruleset excludes the bot.
  Trust `merged_as`, not the parameter you passed: the installation
  token is minted once and threaded into the request precisely so a
  second resolution cannot fail into engineer credentials while the
  payload still claims the bot merged. The bot path also reports
  `branch_deletion_error`, since the REST merge does not delete the
  head ref and a protected ref refuses the follow-up `DELETE`.

- `pr_get` returns `files`, the complete changed-file list (GH-1265).
  Callers previously hand-rolled `gh api repos/.../pulls/N/files`, whose
  30-item default page silently truncated a 41-file PR and produced a
  false-negative "did the frontend change?" merge gate. The field is
  GraphQL-backed, so the REST page size does not apply.

- `create_pr` assembles the body from `job_story` plus a generated
  commit list — anything else the caller wanted in the body has
  nowhere to go, so it was silently dropped (GH-1073). Pass `body=`
  to supply the whole body instead: it is used verbatim, the
  two-pass commit-list rewrite is skipped, and the JTBD marker check
  runs against your text rather than `job_story`. `Fixes:` is still
  normalized to the last line. Keep using `job_story=` for an
  ordinary PR — `body=` is for callers that own the full body.

- `create_pr(head=…)` names the branch to open the PR from (GH-1073).
  Without it the branch comes from the invoking process's CWD, so a
  caller acting for another checkout — the foreman watchdog opening a
  PR for a worker, any cross-worktree orchestrator — had no way to
  say which branch it meant. `head=` is honoured regardless of CWD,
  and the base-branch refusal (GH-873 F1) applies to it. Omitting it
  keeps the CWD-derived behaviour.

- `create_pr(milestone=…)` / `update_pr(milestone=…)` assign a
  milestone by title or number (GH-1098). Nothing on the MCP surface
  could write that field before, so a PR opened through the
  sanctioned path always had `milestone: null` and
  `dev10x:gh-pr-monitor` Phase 3.5 (post-merge milestone cleanup)
  silently took its skip branch on every milestone-bundle PR. The
  write goes through the `issues/{n}` endpoint — the `pulls/{n}`
  endpoint has no milestone field — so `gh pr edit --milestone` stays
  routed to `update_pr`. Clearing a milestone is not supported.

- For a PR that delivers only part of issue #N (GH-1604), pass
  `fixes_url="none — part of #N"` (or end `body=` with that line).
  The trailer is present, so the GH-1274 read-back passes.
  It carries no closing reference, so #N stays open on merge.
  Add `Part of #N` and the remaining steps to the body.
