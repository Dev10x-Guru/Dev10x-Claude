# MCP Tool Naming and Invocation

Central reference for MCP tool naming conventions and invocation patterns.

## Name Format

MCP tools follow a consistent naming convention from Python function to MCP
registration:

- **Python function**: `snake_case` (e.g., `detect_tracker`)
- **MCP registration**: `mcp__plugin_<PluginName>_<ServerName>__<snake_case>`
  - `<PluginName>`: Title-case plugin name from plugin.json (e.g., `Dev10x`)
  - `<ServerName>`: Server name in plugin.json (e.g., `cli`, `db`)
  - `<snake_case>`: Unchanged function name

## Examples

| Server | Function | MCP Name |
|--------|----------|----------|
| `cli` | `detect_tracker()` | `mcp__plugin_Dev10x_cli__detect_tracker` |
| `cli` | `pr_comments()` | `mcp__plugin_Dev10x_cli__pr_comments` |
| `cli` | `pr_comment_reply()` | `mcp__plugin_Dev10x_cli__pr_comment_reply` |
| `cli` | `get_commit_log()` | `mcp__plugin_Dev10x_cli__get_commit_log` |
| `cli` | `mktmp()` | `mcp__plugin_Dev10x_cli__mktmp` |
| `db` | `list_tables()` | `mcp__plugin_Dev10x_db__list_tables` |

## Tool Declaration Pattern

All MCP tools follow a two-layer pattern: internal functions return a
typed `Result[T]` (`SuccessResult` or `ErrorResult` from
`dev10x.domain.common.result`), and the `@server.tool()` handler at the
MCP boundary routes the result through `to_wire()` — which asserts
`isinstance(result, ResultProtocol)` then calls `.to_dict()` — to
produce the wire-format dict (ADR-0009).

```python
# Internal module (audit/release/monitor/permission/plan/skill_index/
# utilities/github/db): public functions return Result[T].
from dev10x.domain.common.result import Result, err, ok

async def collect_prs(...) -> Result[dict[str, Any]]:
    if error_occurs:
        return err("descriptive message")
    return ok({tool-specific fields})

# MCP server boundary (src/dev10x/mcp/server_cli.py): route through
# to_wire() so external consumers see the uniform wire format and a
# handler that forgot to return a Result fails loud at the boundary.
from dev10x.domain.common.result import to_wire

@server.tool()
async def collect_prs(...) -> dict:
    """Brief description of what the tool does."""
    return to_wire(await rel.collect_prs(...))
```

**Wire format** (what callers see):
- `SuccessResult.to_dict()` → `{tool-specific fields}` (no `success` flag
  is added automatically — keep success payloads tool-specific).
- `ErrorResult.to_dict()` → `{"error": "descriptive message", ...}`
  (extra metadata like `messages`/`errors` is preserved).

**Why two layers**: internal callers branch on `isinstance(result,
SuccessResult)` for type-safe error handling; the MCP boundary keeps
the legacy dict shape so existing tool consumers don't break. New
modules MUST mirror the pattern — return `Result[T]` internally, route
through `to_wire()` at the `@server.tool()` boundary.

**Tool-specific success payloads**:
- `mktmp`: returns `{"path": "/tmp/file"}`
- Some tools return `{"success": True, "data": result}`
- Some tools return only tool-specific fields without a `success` flag
- `push_safe`: returns `{"pushed": true, "ref": "...", "remote":
  "...", "sha": "...", "tracking": "...", "ci_run_url": null}` on a
  successful push (GH-188). On a blocked or failed push, `pushed` is
  `false` and `blocked_reason` names the cause. Only `{"error": ...}`
  signals an MCP-level failure. Older callers that treat any non-error
  payload as success continue to work.

Callers must know each tool's specific success response format. Branch
on the presence of an `"error"` key, never on whether the dict is
empty.

### Concurrency conventions for new tools (GH-827, ADR-0011)

MCP tools run in a long-lived daemon and are hit concurrently by
parallel worktrees and agents. When a new tool (or the domain module
behind it) touches shared state, it MUST follow the write-safety model:

- **New shared-state file** — a JSON/YAML store or log under
  `~/.config/Dev10x/`, a repo's `.claude/`, or a home cache — routes
  through `dev10x.domain.file_locks`, never a bare `Path.write_text` /
  `open(…, "w"|"a")`: `locked_json_update` / `locked_yaml_update` for a
  read-modify-write cycle (or `file_lock` wrapping a typed load/save
  when the store deserializes to a dataclass), `atomic_write_text` for
  a full overwrite, `atomic_append_line` for an append. An unlocked
  load→mutate→save is a lost-update race; a bare `write_text` truncates
  on crash. Two writers on the SAME file must lock on the same sidecar
  — `file_lock` appends `.lock` to the full name while
  `locked_json_update` replaces the suffix, so mixing them on one path
  silently fails to exclude.
- **New subprocess call** passes `timeout=` (in-package code via
  `subprocess_utils`, which bounds it; standalone uv-scripts via a
  local `_SUBPROCESS_TIMEOUT_SECONDS` constant since they cannot import
  `dev10x`).

The `reviewer-generic` checklist enforces both on `**/*.py` changes.

## Canonical Parameter Shapes

Parameter naming is not uniform across tools, which defeats agent
first-call inference (GH-462 F4 — 7 first-call validation errors in
one session). Use these shapes verbatim:

| Tool | Required parameters | Common wrong guess |
|------|---------------------|--------------------|
| `issue_get` | `number` | `issue_id` |
| `pr_get` | `number` | `pr_number` |
| `pr_comments` | `pr_number`, `action` (no default) | omitting `action` |
| `unresolved_threads` | `repo` (no CWD default); pass `pr_number` for a single PR | omitting `repo`; omitting `pr_number` for a per-PR check |
| `check_top_level_comments` | `repo` (no CWD default) | omitting `repo` |
| `push_safe` | `args` list, e.g. `["-u", "origin", "<branch>"]` | bare call; passing `protected_branches=[]` expecting protection off — an empty list reads as "no override" (GH-1031) |
| `resolve_review_thread` | `thread_ids` (list) | singular `thread_id` |
| `resolve_gate` | `gate` (toggle name); optional `context` dict of gate facts | passing preset/friction values — the tool reads session policy itself (ADR-0016 D-2); passing `human_review` on `gate="merge"` — durable policy, read unconditionally and echoed back in `ignored_context_fields` (GH-1000) |
| `pr_close` | `pr_number` | `number` (that's `issue_close`'s param name) |
| `resolve_plugin_origin` | `skill_paths` (list of absolute paths) | singular `skill_path` |
| `pin_gate_preset` | `preset`; optional `scope` (`repo` default / `repo-only` / `dir`) | passing a `match` or a path — the tool derives the repo stem itself |
| `human_review_status` | none (optional `cwd`) | reading `friction.yaml` directly instead — the tool owns the precedence |
| `tracker_status` | none (optional `cwd`) | treating `pinned: false` as "no tracker" — it still reports a resolved `tracker` (the default) |
| `pin_tracker` | `tracker` (`linear`/`jira`/`github`); optional `scope` | passing `gitlab`/`clickup` — not in v1 scope, and an unknown value errors rather than defaulting |
| `task_index_append` | `entry` dict with required `subject` + `source` | reading the store and writing it back by hand — the tool owns the locked read-append-write |
| `pr_labels` | `pr_number`; `action` (`list` default / `add` / `remove`), plus `labels` for the two writes | separate `pr_label_add` / `pr_label_remove` names — it is one tool with an action selector, like `pr_comments` |
| `task_index_get` | none (optional `cwd`) | `Read`ing `.claude/Dev10x/session.yaml` — retired by ADR-0018 D5; the tool probes it as a fallback |
| `pr_ready` | `pr_number`; optional `undo` (bool) | assuming it only publishes — `undo=true` returns a PR to draft |

Behavioral caveats:

- The `task_index_*` trio is the park family's only sanctioned write
  path (GH-1009, ADR-0018 D5). The store lives at
  `~/.config/Dev10x/task-index/<repo-stem>.yaml`, keyed by the git
  **common dir**, so one index serves a repo and every worktree of it.
  Reaching the file with `Write`/`Edit` — at the new path or the retired
  `.claude/Dev10x/session.yaml` — is a defect twice over: under a repo's
  `.claude/` it trips the self-settings consent gate that no allow rule
  suppresses, and anywhere it bypasses the file lock, so two parallel
  worktrees parking at once lose an entry. `task_index_get` reads the
  retired path as a fallback for one release (`legacy_read: true`), and
  the next append folds it forward (`folded_legacy`).

- `pr_labels` carries the durable `review:cleared` signal (GH-1008).
  `Dev10x:gh-pr-request-review` reads it before the stand-by clearance
  gate and skips asking when present; the two "I reviewed it" answers
  write it. Because a sign-off covers the commits that were read,
  `Dev10x:git-groom` removes it after a force-push — a clearance must
  not survive the rewrite that invalidated it. Both writes are
  idempotent (`add` skips present labels, `remove` intersects against
  the current set first, so clearing an unset label is a no-op rather
  than a 404), so call them unconditionally instead of probing.

- `pr_ready` flips a PR in both directions: omit `undo` to publish a
  draft, pass `undo=true` to convert a published PR back to draft
  (GH-931). Raw `gh pr ready --undo` is hook-blocked like every other
  form, so this parameter is the only sanctioned way to un-publish —
  which is the *safe* direction when a problem surfaces after marking
  ready. The success payload carries `draft` reflecting the new state.

- `pr_ready` must be re-run after ANY force-push (GH-958). A
  `--force-with-lease` push resets a published PR back to draft, so a
  ready call that succeeded earlier — including a
  `create_pr(draft=false)` — does not survive a later rebase, amend, or
  groom. Call `pr_ready` after the FINAL push and confirm with a fresh
  `pr_get` that `isDraft` is `false`; otherwise `merge_pr` fails with
  `GraphQL: Pull Request is still a draft`, and the re-ready costs
  another bot-CI round.

- `create_pr` rejects a `job_story` missing any of `**When**` /
  `**<actor> wants to**` / `**so <beneficiary> can**` with an
  actionable error before the PR is opened, and `update_pr` moves any
  content trailing the `Fixes:` line above it (GH-945) — so neither
  path can emit a body that trips the hygiene bot.

- `create_pr(closes=[...])` is NON-CLOSING (GH-958). The parameter
  emits `Closes #N` lines into the PR body *above* the `Fixes:`
  trailer, and GitHub's auto-close automation never fires on them on a
  merge to `develop` — only the `Fixes:` trailer auto-closes its issue.
  Treat `closes=` as informational cross-referencing: for a
  milestone-bundle PR, close every non-`Fixes:` issue manually with
  `issue_close` after the merge, and verify each one rather than
  assuming the bundle self-closed.

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
  REPLACES the one below rather than adding to it, and only
  `--force` is blocked — a plain push and `--force-with-lease` are
  always allowed. Prefer the durable pref over a per-call list: an
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
- `pin_tracker` / `tracker_status` carry the project's issue-tracker
  choice (GH-768). `ensure-base` and `seed_worktree` seed only that
  tracker's MCP rules, so a Jira user stops collecting ~35 inert
  `mcp__claude_ai_Linear__*` allows while their own Atlassian tools
  prompt on first use. The choice is a durable `tracker:` key in the
  matching `projects[]` entry of `~/.config/Dev10x/friction.yaml` —
  same repo-stem keying as `pin_gate_preset`, so one answer covers a
  repo and every worktree of it. Gate the onboarding ask on
  `tracker_status` → `pinned: false`; note that `pinned` reports
  whether a *project entry* names one, while `tracker` always reports a
  resolved value (defaulting to `linear`, the pre-GH-768 behaviour, so
  upgrades lose nothing). v1 covers Linear / Jira / GitHub Issues;
  GitLab and ClickUp are deliberately unsupported rather than shipped
  as empty blocks.

- `pin_gate_preset` persists a Phase-0 preset pick into the global
  `~/.config/Dev10x/friction.yaml`, keyed by the repo stem read from the
  git **common dir** — so a pick made inside worktree `<repo>-3` also
  covers `<repo>` and a `<repo>-9` created later (GH-855). It is
  idempotent: an entry already covering the checkout is replaced, never
  duplicated. Gate the ask on `preset_pin_status` → `pinned: false`
  (the first-pick condition); asking on every pick is the friction the
  pair exists to remove. Nothing is written under a repo's `.claude/`
  (ADR-0018), so the self-settings gate never fires.
- `resolve_gate` returns `{gate, effect (ask|auto-advance|skip),
  resolved_option, log_to, reason, floors_applied,
  anchor_recommendations}`; on an `auto-advance` it adds a `record`
  key carrying the visible D-7 line (`⚙ gate:… → "…" (reason)`),
  absent for `ask`/`skip` (ADR-0016 #754). Session policy is read
  from `.claude/Dev10x/session.yaml` — the new-style `gate_preset`
  / `gate_overlays` / `gate_overrides` keys take precedence over the
  legacy `friction_level` / `active_modes` / `walk_away` mapping
  (#753); the durable project pin lives at git-tracked
  `.dev10x/gate-policy.yaml` (legacy `.claude/Dev10x/gate-policy.yaml`
  still read as a fallback, #752).

Parameter normalization (accepting aliases, defaulting `repo` from
CWD, richer `push_safe` diagnostics) is tracked as follow-up work;
until it lands, the table above is the contract.

## Tool Availability by Plugin Version

MCP tools are added incrementally. Document the minimum plugin version
supporting each tool:

| Tool | Server | Introduced | Availability |
|------|--------|------------|--------------|
| `detect_tracker` | `cli` | PR #126 | v0.25.0+ |
| `pr_detect` | `cli` | PR #126 | v0.25.0+ |
| `issue_get` | `cli` | PR #126 | v0.25.0+ |
| `issue_comments` | `cli` | PR #126 | v0.25.0+ |
| `issue_create` | `cli` | PR #552 | v0.44.0+ |
| `issue_close` | `cli` | GH-268 | v0.74.0+ |
| `issue_reopen` | `cli` | GH-268 | v0.74.0+ |
| `pr_get` | `cli` | GH-267 | v0.74.0+ |
| `pr_comments` | `cli` | PR #126 | v0.25.0+ |
| `pr_comment_reply` | `cli` | PR #399 | v0.37.0+ |
| `pr_review_comment_edit` | `cli` | GH-304 | v0.76.0+ |
| `pr_review_edit` | `cli` | GH-778 | v0.86.0+ |
| `pr_ready` | `cli` | GH-779 | v0.86.0+ |
| `pr_close` | `cli` | GH-924 | v0.92.0+ |
| `pr_issue_comment` | `cli` | GH-205 | v0.72.0+ |
| `request_review` | `cli` | PR #126 | v0.25.0+ |
| `detect_base_branch` | `cli` | PR #191 | v0.30.0+ |
| `verify_pr_state` | `cli` | PR #191 | v0.30.0+ |
| `pre_pr_checks` | `cli` | PR #191 | v0.30.0+ |
| `create_pr` | `cli` | PR #191 | v0.30.0+ |
| `update_pr` | `cli` | GH-60 | v0.70.0+ |
| `merge_pr` | `cli` | GH-232 | v0.73.0+ |
| `run_tests` | `cli` | GH-238 | v0.74.0+ |
| `run_node_tests` | `cli` | GH-703 | v0.80.0+ |
| `milestone_close` | `cli` | GH-187 | v0.71.0+ |
| `milestone_create` | `cli` | GH-220 | v0.73.0+ |
| `milestone_reopen` | `cli` | GH-850 | v0.90.0+ |
| `milestone_edit` | `cli` | GH-850 | v0.90.0+ |
| `issue_edit` | `cli` | GH-220 | v0.73.0+ |
| `issue_comment` | `cli` | GH-220 | v0.73.0+ |
| `issue_comment_edit` | `cli` | GH-283 | v0.75.0+ |
| `issue_comment_delete` | `cli` | GH-283 | v0.75.0+ |
| `issue_list` | `cli` | GH-220 | v0.73.0+ |
| `slack_thread_is_forward` | `cli` | GH-218 | v0.73.0+ |
| `milestones_bulk_create` | `cli` | GH-222 | v0.73.0+ |
| `issues_bulk_create` | `cli` | GH-222 | v0.73.0+ |
| `issues_bulk_edit` | `cli` | GH-222 | v0.73.0+ |
| `generate_commit_list` | `cli` | PR #191 | v0.30.0+ |
| `post_summary_comment` | `cli` | PR #191 | v0.30.0+ |
| `pr_notify` | `cli` | PR #191 | v0.30.0+ |
| `push_safe` | `cli` | PR #126 | v0.25.0+ |
| `rebase_groom` | `cli` | PR #126 | v0.25.0+ |
| `create_worktree` | `cli` | PR #126 | v0.25.0+ |
| `mass_rewrite` | `cli` | PR #288 | v0.30.0+ |
| `start_split_rebase` | `cli` | PR #288 | v0.30.0+ |
| `next_worktree_name` | `cli` | PR #126 | v0.25.0+ |
| `setup_aliases` | `cli` | PR #288 | v0.30.0+ |
| `mktmp` | `cli` | PR #160 | v0.26.0+ |
| `resolve_plugin_origin` | `cli` | GH-816 | v0.92.0+ |
| `audit_hook_log_path` | `cli` | GH-29 | v0.69.0+ |
| `audit_hook_recent` | `cli` | GH-29 | v0.69.0+ |
| `record_upgrade` | `cli` | GH-109 | v0.72.0+ |
| `cluster_review_comments` | `cli` | GH-346 | v0.80.0+ |
| `candidate_rules_report` | `cli` | GH-347 | v0.80.0+ |
| `validate_candidate_patterns` | `cli` | GH-348 | v0.80.0+ |
| `author_reference_rules` | `cli` | GH-349 | v0.80.0+ |
| `rule_confidence_report` | `cli` | GH-350 | v0.80.0+ |
| `record_rule_feedback` | `cli` | GH-350 | v0.80.0+ |
| `request_sampling` | `cli` | GH-343 | v0.80.0+ |
| `background_preamble` | `cli` | GH-610 | v0.80.0+ |
| `resolve_gate` | `cli` | GH-742 (ADR-0016 spike) | v0.83.0+ |
| `preset_pin_status` | `cli` | GH-855 | v0.92.0+ |
| `pin_gate_preset` | `cli` | GH-855 | v0.92.0+ |
| `human_review_status` | `cli` | GH-950 | v0.93.0+ |
| `tracker_status` | `cli` | GH-768 | v0.95.0+ |
| `pin_tracker` | `cli` | GH-768 | v0.95.0+ |
| `pr_labels` | `cli` | GH-1008 | v0.94.0+ |
| `task_index_get` | `cli` | GH-1009 | v0.94.0+ |
| `task_index_append` | `cli` | GH-1009 | v0.94.0+ |
| `task_index_set` | `cli` | GH-1009 | v0.94.0+ |
| `usage_blocks` | `cli` | GH-878 | v0.90.0+ |
| `query` | `db` | PR #126 | v0.25.0+ |

When adding a new tool, update this table and note any dependencies on
specific CLI commands or external programs. Skills should declare required
tools explicitly in `allowed-tools:` to catch availability mismatches early.

## Skill Usage

In SKILL.md, declare MCP tool access via `allowed-tools:`:

```yaml
allowed-tools:
  - mcp__plugin_Dev10x_cli__detect_tracker
  - mcp__plugin_Dev10x_cli__pr_comments
  - Bash(/path/to/script:*)
```

Use wildcard sparingly: `mcp__plugin_Dev10x_cli__*` grants access to all cli
server tools. Prefer explicit tool names for security and clarity.

## Server Registration

Each MCP server must be registered in `.claude-plugin/plugin.json`:

```json
"mcpServers": {
  "cli": {
    "command": "${CLAUDE_PLUGIN_ROOT}/servers/cli_server.py",
    "env": { "PYTHONUNBUFFERED": "1" }
  }
}
```

- Use `${CLAUDE_PLUGIN_ROOT}` for relative paths (not hardcoded paths)
- Server names must not conflict with existing tool or skill names
- All referenced command paths must exist and be executable

## Common Mistakes

### Prefer MCP tool calls over direct script invocation

When an MCP tool wraps a CLI script, **use the MCP tool call** as
the primary invocation method. MCP calls avoid permission friction
(no `Bash()` allow-rule needed) and provide structured responses.

```
# ✅ PREFERRED — MCP tool call (no permission prompt)
mcp__plugin_Dev10x_cli__mktmp(namespace="git", prefix="msg", ext=".txt")

# ⚠️ FALLBACK — direct script (needs Bash allow-rule)
/tmp/Dev10x/bin/mktmp.sh git msg .txt
```

Use the direct script only when the MCP server is unavailable
(e.g., inside a shell script that runs outside Claude's tool-use
protocol).

### MCP tool names cannot appear in shell scripts

MCP tool names (e.g., `mcp__plugin_Dev10x_cli__mktmp`) are
Claude tool-call primitives. They cannot be used inside bash
code blocks, shell scripts, or Makefiles — only via Claude's
tool-use protocol.

```bash
# ❌ WRONG — MCP name in a bash block (not a shell command)
mcp__plugin_Dev10x_cli__mktmp git commit-msg .txt

# ✅ CORRECT — use the underlying CLI script in shell contexts
/tmp/Dev10x/bin/mktmp.sh git commit-msg .txt
```

MCP tool names belong only in:
- `allowed-tools:` declarations in SKILL.md front matter
- Claude tool-call invocations (the agent calls the tool directly)
- Documentation describing which tools a skill uses

### Routed GitHub CLI operations

The skill-redirect hook routes documented `gh` operations to MCP
wrappers. Use the MCP tool; the raw CLI is a fallback only when
the MCP server is unavailable.

| Raw CLI | MCP tool |
|---------|----------|
| `gh issue view` | `mcp__plugin_Dev10x_cli__issue_get` |
| `gh issue create` | `mcp__plugin_Dev10x_cli__issue_create` |
| `gh issue edit` | `mcp__plugin_Dev10x_cli__issue_edit` |
| `gh issue close` | `mcp__plugin_Dev10x_cli__issue_close` |
| `gh issue reopen` | `mcp__plugin_Dev10x_cli__issue_reopen` |
| `gh issue comment` | `mcp__plugin_Dev10x_cli__issue_comment` |
| `gh issue list` | `mcp__plugin_Dev10x_cli__issue_list` (advisory) |
| `gh pr view` | `mcp__plugin_Dev10x_cli__pr_get` |
| `gh api .../milestones POST` | `mcp__plugin_Dev10x_cli__milestone_create` |
| `gh api .../milestones/{n} PATCH state=open` | `mcp__plugin_Dev10x_cli__milestone_reopen` |
| `gh api .../milestones/{n} PATCH` (title/desc/state/due) | `mcp__plugin_Dev10x_cli__milestone_edit` |
| `gh pr edit` | `mcp__plugin_Dev10x_cli__update_pr` |
| `gh pr ready` | `mcp__plugin_Dev10x_cli__pr_ready` |
| `gh pr edit --add-label` / `--remove-label` | `mcp__plugin_Dev10x_cli__pr_labels` (GH-1008) |
| `gh pr close` | `mcp__plugin_Dev10x_cli__pr_close` (GH-924) |
| `gh pr create` | `Dev10x:gh-pr-create` (wraps `create_pr`) |
| `gh pr merge` | `Dev10x:gh-pr-merge` (wraps `merge_pr`) |

For a stale severity token in a **review body** (state=COMMENTED)
that trips gh-pr-merge Check 1b, edit it via
`mcp__plugin_Dev10x_cli__pr_review_edit` (GH-778) — the review-body
counterpart to `pr_review_comment_edit` (inline) and
`issue_comment_edit` (top-level).

### Routed test commands (S12 map)

The `diag-friction` command-skill map (`command-skill-map.yaml`)
advisorily routes test runners to MCP wrappers so they run off the
Bash layer — sidestepping the core-harness brace-expansion block that
no allow-rule can suppress (GH-703).

| Raw command | MCP tool |
|-------------|----------|
| `pytest` / `uv run pytest` | `Dev10x:py-test` (wraps `run_tests`) |
| `jest` / `yarn … test` / `npm test` / `pnpm test` / `vitest` | `mcp__plugin_Dev10x_cli__run_node_tests` |

`run_node_tests` accepts a `runner` arg (`jest` default, plus
`vitest`/`yarn`/`npm`/`pnpm`); `jest`/`vitest` get `--coverage` when
`coverage=true`.

It also takes `script` and `env` (GH-1029). `script` names the
`package.json` script to run — default `"test"`, which keeps the
historical `yarn test` / `npm test` shape; any other value becomes
`<pm> run <script>`, so a `lint:tsc` or `lint` check runs inside the
wrapper instead of as a raw `tsc`/`node` invocation on the Bash
layer. Only `yarn`/`npm`/`pnpm` resolve a script name — pairing
`script` with `jest`/`vitest` returns an error rather than silently
ignoring it, since those are invoked directly through `npx` and have
no script table. `env` is overlaid on the inherited environment (not
substituted for it), for a script whose own definition pins something
the wrapper would otherwise drop — e.g. a `TZ` that snapshot tests
depend on.

## Official GitHub MCP Server

We do **not** use [`github/github-mcp-server`](https://github.com/github/github-mcp-server).
The internal `Dev10x:cli` server is the sole GitHub surface — its
composite tools are shaped to Dev10x workflows rather than mirroring
the REST/GraphQL primitives.

When a new GitHub capability is needed (Actions, code scanning,
notifications, etc.), add a Dev10x-shaped composite tool to this
server rather than pulling in the official one. The official server's
source is a useful reference for endpoints and GraphQL queries; it
is not a runtime dependency.

Full rationale, overlap map, and implementation plan:
[`docs/adr/0006-keep-internal-github-mcp-over-official-server.md`](../../docs/adr/0006-keep-internal-github-mcp-over-official-server.md).
