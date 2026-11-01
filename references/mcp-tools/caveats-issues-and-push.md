# MCP Tool Caveats — Node Tests, Issues, Push, Review Threads

Behavioural caveats moved out of `.claude/rules/mcp-tools.md`
§ Canonical Parameter Shapes (GH-1606): `run_node_tests`,
`create_pr(closes=…)`, `issue_create` / `issue_close`, `push_safe`,
`unresolved_threads`.

- `run_node_tests` detects its runner when `runner` is omitted (GH-1683):
  `vitest.config.*` → vitest; `jest.config.*` or a `jest` key in
  `package.json` → jest; a `test` script → the lockfile's package manager;
  otherwise jest.
  The payload's `runner` reports what actually ran.
  A non-zero exit of the default `test` script with no executed test is an
  `ErrorResult` with `verdict: "no_tests_ran"` — a run that executed
  nothing must not look clean.
  Parsed test failures and a failing named script stay ordinary results.

- `create_pr(closes=[...])` is NON-CLOSING (GH-958). The parameter
  emits `Closes #N` lines into the PR body *above* the `Fixes:`
  trailer, and GitHub's auto-close automation never fires on them on a
  merge to `develop` — only the `Fixes:` trailer auto-closes its issue.
  Treat `closes=` as informational cross-referencing: for a
  milestone-bundle PR, close every non-`Fixes:` issue manually with
  `issue_close` after the merge, and verify each one rather than
  assuming the bundle self-closed.

- `issue_create` / `issues_bulk_create` accept `milestone` and
  `labels`, and filing is expected to POPULATE them (GH-1102). Reach
  them through `dev10x:ticket-create`, whose Step 4 reads the live
  roster via `triage_roster` and proposes a milestone plus label set;
  calling `issue_create` bare is what left 11 of 16 open issues
  unmilestoned and 10 of 13 unlabeled in the 2026-08-30 sweep. When no
  milestone fits confidently, the skill files `needs-triage` rather
  than nothing, so strays stay findable with one query. `triage_roster`
  is read-only and returns `{"milestones": [...], "labels": [...]}` —
  open milestones only.

- `issue_close` called with a pull-request number fails loud with
  `"N is a pull request; use pr_close"` instead of surfacing the raw
  `gh issue close` rejection (GH-924) — reach for `pr_close` instead
  of retrying `issue_close` with a different `reason`/`comment`.
- `push_safe` failure returns `{"pushed": false, "blocked_reason":
  "push_failed"}` with no further diagnostic; a successful push may
  return `{}` — treat any non-`error` payload without
  `"pushed": false` as success.

- `push_safe` protection resolves in three tiers (GH-1031): a
  non-empty `protected_branches` argument, else the durable
  `protected_branches` key in the matching `projects[]` entry of
  `~/.config/Dev10x/friction.yaml`, else the script default
  `main master develop development staging trunk`. Each tier
  REPLACES the one below rather than adding to it. A plain push is
  always allowed and `--force` is blocked on a protected branch;
  `--force-with-lease` is allowed on any branch, but a protected
  target is fetched first and refused as `base_behind_remote` unless
  the remote tip is already an ancestor of the pushed ref (GH-1270) —
  a lease alone compares against the local remote-tracking ref, so a
  stale one leases cleanly and drops every merge landed since. Prefer
  the durable pref over a per-call list: an
  unattended agent never passes one, which is when an unprotected
  force-push costs the most. Three docs previously stated three
  different defaults ("main, develop", "main master", and the real
  six) — `tests/git/test_git.py` now pins the documented list to the
  shell script so that drift cannot recur.
- `unresolved_threads` runs in two modes: with `pr_number` it issues
  a single per-PR `reviewThreads` GraphQL query (sub-2s, returns
  `{"unresolved_threads": [...], "count": N}`); without it, it sweeps
  up to `limit` merged PRs (slower — one subprocess pair per PR —
  returns `{"prs": [...], "count": N}`). For a single-PR check always
  pass `pr_number` (GH-710).
