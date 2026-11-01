# MCP Tool Naming and Invocation

Central reference for MCP tool naming conventions and invocation patterns.

> **[OVERRIDE DETECTED]** — over the 200-line rule budget in
> `.claude/rules/INDEX.md`. Kept as one file under § Budget Overrides
> because it is one contract read as a unit: the naming format, the
> `Result`/`to_wire` declaration pattern, the canonical parameter
> shapes and the routed-CLI map all answer "how do I call this tool
> correctly".
>
> **This rule has no `paths:` front matter, so it loads in every
> session** (GH-1606). An earlier note justified its size by calling it
> "path-scoped and read on demand"; it never was, and at 56k characters
> it was a third of the always-loaded instruction total. GH-1606 moved
> the bulk out instead: the per-tool behavioural caveats and the
> version-history table now live under
> [`references/mcp-tools/`](../../references/mcp-tools/), read when a
> caller reaches for the tool they describe.
> `tests/test_always_loaded_instruction_budget.py` fails when the
> always-loaded total grows past its budget again.
>
> **Conditional split plan.** If this file passes ~600 lines, split
> along the authoring/calling seam: `mcp-tool-authoring.md` (name
> format, declaration pattern, concurrency, server registration, the
> three edits a new tool needs) and `mcp-tool-calling.md` (parameter
> shapes, write-receipt rule, routed-CLI map), with this file left as a
> thin index. New caveats go to `references/mcp-tools/`, not here.

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
| `cli` | `detect_tracker()` | `mcp__plugin_dev10x_cli__detect_tracker` |
| `cli` | `pr_comments()` | `mcp__plugin_dev10x_cli__pr_comments` |
| `cli` | `pr_comment_reply()` | `mcp__plugin_dev10x_cli__pr_comment_reply` |
| `cli` | `get_commit_log()` | `mcp__plugin_dev10x_cli__get_commit_log` |
| `cli` | `mktmp()` | `mcp__plugin_dev10x_cli__mktmp` |
| `db` | `list_tables()` | `mcp__plugin_dev10x_db__list_tables` |

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
- **Fan-out is bounded for you (GH-1422).** `async_run` holds a permit
  from a per-event-loop `asyncio.Semaphore` for the child's whole life,
  capped by `DEV10X_MCP_MAX_SUBPROCESSES` (default 12). Several
  worktrees running crews could otherwise launch dozens of concurrent
  `gh` children, and GitHub's secondary rate limits key off burst
  volume — a lockout hits the whole install, not the worktree that
  caused it. A new tool that goes through the Gateway inherits this;
  one that spawns its own subprocess does not, which is another reason
  not to.
- **Transient external failures retry once or twice (GH-1423).**
  `dev10x.domain.retry` holds the policy — `is_retryable`,
  `is_retryable_status`, `RetryPolicy.delay_for` — and `_gh_api_raw`
  and `call_slack_api` adopt it. It is pure policy, not a driver,
  because the two paths are async-over-subprocess and sync-urllib
  respectively. Retry 408/429/5xx and network faults only, honour
  `Retry-After` clamped to `max_delay`, and jitter the backoff. Never
  retry a bounded timeout of our own: GH-1288's principle is that the
  transport ceiling sets the limit, and re-running multiplies it.

### A write is a request, not a receipt (GH-1099)

The MCP transport can drop mid-call and lose a **state-changing** call
with no error payload — a field-observed `update_pr` never landed and
returned nothing to say so. No `ErrorResult` is possible in that case,
and the caller cannot tell it apart from a call that returned nothing;
`skills/foreman/references/mcp-connectivity.md` has the full argument.

So callers must not treat a write wrapper's return as proof of effect.
After `update_pr`, `create_pr`, `pr_ready`, `push_safe`, `pr_labels`,
`issue_*`, or `merge_pr`, re-read the specific field that was set —
`pr_get` for a body or `isDraft`, the remote SHA for a push, `state`
for an issue close — rather than checking only that the object exists.
The branch-on-`"error"` rule above still holds; it just does not cover
the case where nothing comes back at all. Dev10x owns no keepalive on
that hop and cannot add one, so reconnect-on-demand is not
implementable in this repo (GH-1072).

**Three wrappers now verify themselves (GH-1424).** `create_pr`,
`update_pr` and `pr_ready` re-read the PR and report the observed
value, so a caller of those three does not have to. The rule above was
prose for six releases and only `create_pr` ever implemented it; the
sharpest miss was `pr_ready` returning `{"draft": undo}` — its own
argument handed back, a field that could not disagree with the request
and so confirmed nothing. Each carries a verification flag
(`fixes_trailer_verified` / `write_verified` / `draft_verified`), a
disagreement is an `ErrorResult` naming the PR, and an *unreadable*
read-back warns rather than fails — being unable to check is not
evidence the write failed. `tests/github/test_write_verification.py`
is an AST guard, so a wrapper cannot quietly go back to building its
payload from its own arguments. **Every other write wrapper still
needs the caller to re-read.**

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
| `unresolved_threads` | none; optional `repo` (defaults from `cwd`, GH-1683); pass `pr_number` for a single PR | omitting `pr_number` for a per-PR check |
| `check_top_level_comments` | `pr_number`; optional `repo` (defaults from `cwd`, GH-1683) | expecting `unresolved_threads`'s sweep-all-PRs mode — this tool has none (GH-1285) |
| `push_safe` | `args` list, e.g. `["-u", "origin", "<branch>"]` | bare call; passing `protected_branches=[]` expecting protection off — an empty list reads as "no override" (GH-1031) |
| `resolve_review_thread` | `thread_ids` (list) | singular `thread_id` |
| `resolve_gate` | `gate` (toggle name); optional `context` dict of gate facts | passing preset/friction values — the tool reads session policy itself (ADR-0016 D-2); passing `human_review` on `gate="merge"` — durable policy, read unconditionally and echoed back in `ignored_context_fields` (GH-1000) |
| `pr_close` | `pr_number` | `number` (that's `issue_close`'s param name) |
| `resolve_plugin_origin` | `skill_paths` (list of absolute paths) | singular `skill_path` |
| `pin_gate_preset` | `preset`; optional `scope` (`repo` default / `repo-only` / `dir`) | passing a `match` or a path — the tool derives the repo stem itself; passing `gate_overrides={"supervisor_review": ...}` — it is not a per-gate toggle (absent from `_ENUM_TOGGLES`), use `pin_supervisor_review` instead (GH-1165) |
| `supervisor_review_status` | none (optional `cwd`) | reading `friction.yaml` directly instead — the tool owns the precedence; calling `human_review_status` — that alias was removed in v0.109.0, and the payload no longer carries the boolean `human_review` key (ADR-0022 D-2, ADR-0028) |
| `pin_supervisor_review` | `supervisor_review` (`required`/`none`); optional `scope` (`repo` default / `repo-only` / `dir`) | reaching for `pin_gate_preset`'s `gate_overrides` — `supervisor_review` is a project-wide fact, not a gate toggle (GH-1165) |
| `tracker_status` | none (optional `cwd`) | treating `pinned: false` as "no tracker" — it still reports a resolved `tracker` (the default) |
| `pin_tracker` | `tracker` (`linear`/`jira`/`github`); optional `scope` | passing `gitlab`/`clickup` — not in v1 scope, and an unknown value errors rather than defaulting |
| `ide_status` | none (optional `cwd`) | reading a resolved `none` as "unanswered" — most checkouts genuinely run no IDE server, so `none` is an answer; `pinned` is the unanswered flag |
| `pin_ide` | `ide` (`pycharm`/`none`); optional `scope` | passing `vscode`/`intellij` — not in v1 scope, and an unknown value errors rather than defaulting |
| `task_index_append` | `entry` dict with required `subject` + `source` | reading the store and writing it back by hand — the tool owns the locked read-append-write |
| `pr_labels` | `pr_number`; `action` (`list` default / `add` / `remove`), plus `labels` for the two writes | separate `pr_label_add` / `pr_label_remove` names — it is one tool with an action selector, like `pr_comments` |
| `issue_labels` | `number`; `action` (`list` default / `add` / `remove`), plus `labels` for the two writes | `issue_edit(labels=...)` for anything but adding — that parameter's docstring used to claim replacement semantics it never had (GH-1322); `pr_number` (that's `pr_labels`'s param name) |
| `ci_rerun` | exactly one of `pr_number` / `head_sha`; optional `checks` (names), `failed_only` (default `true`), `repo` | passing both targets or neither — an error; assuming a third-party suite is unbounded across calls — its re-requests are counted in `~/.config/Dev10x/ci-rerun-attempts.json` per repo + PR (or head SHA) and stop at the same cap of 3 as Actions runs (GH-1724); reading a short listing as complete — check `truncated`, set when the 10-page ceiling is hit; raw `gh api --method POST .../rerequest` — routed here |
| `task_index_get` | none (optional `cwd`) | `Read`ing `.claude/Dev10x/session.yaml` — retired by ADR-0018 D5; the tool's fallback read was removed in 0.112.0 (GH-1771) |
| `pr_ready` | `pr_number`; optional `undo` (bool) | assuming it only publishes — `undo=true` returns a PR to draft |
| `ci_check_status` | `pr_number`; optional `repo` (defaults from `cwd`, GH-1683), `wait`, `wait_out_pending` (default `true`), `wait_for` (list of check names) | reading a `wait=true` `failing` as "every leg finished" — check `pending` (GH-1065); expecting `wait_out_pending` to cover a failed REQUIRED leg — it does not, use `wait_for` (GH-1138); raising `max_polls` to cover a slow PR — the grant is capped by the transport budget, so ask twice rather than once for longer (GH-1288) |
| `create_pr` | `title`, `issue_id`, plus either `job_story` or `body`; optional `head`, `milestone`, `repo` | passing a long `job_story` and expecting the extra paragraphs to survive — only `body` is used verbatim (GH-1073); assuming `repo` is rejected — it is accepted since GH-1269 |
| `merge_pr` | `pr_number`; optional `expected_head_sha`, `use_bot` | omitting `expected_head_sha` after a pre-merge gate read `headRefOid` — the merge then takes whatever the head is *now* (GH-1267); reading `merged_as` as a request rather than a result — it reports which identity actually merged (GH-1272); passing an abbreviated `expected_head_sha` — only the full 40-character `headRefOid` is accepted, refused before any network call (GH-1681) |
| `run_node_tests` | none; optional `runner` (detected from `cwd` when omitted, GH-1683), `script`, `env` | passing `runner="jest"` in a vitest repo — jest ran zero tests and reported passed 0 / failed 0 with only `returncode: 1` as the signal |
| `gchat_watch_arm` | `thread` (full name) or `space`; plus `notify` / `notify_roles` (lists) or `route=true` | singular `notify="<mailbox>"`; expecting it to read Chat — only `dev10x skill notify gchat-watch poll` reads (GH-1682) |
| `update_pr` | `pr_number`, plus at least one of `body` / `title` / `base_branch` / `milestone` | `gh pr edit --milestone` — routed here (GH-1098) |
| `permission_triage` / `permission_grant` | `target` (the prompted command, or a rule); grant also needs `rule`, the triage rule echoed back so the approval prompt names it; optional `working_dirs` (absolute), and `dry_run` / `remember` on grant | expecting a grant to reach a worktree created later without `remember=true`, which also records the rule in `~/.config/Dev10x/granted-permissions.yaml` for `ensure-base` / `seed-worktree` (GH-1677); passing a hand-built rule for a command — pass the command so triage can see its shape (GH-1676); expecting grant to write on a non-`grant` verdict, or with a `rule` triage did not derive — it refuses and returns the triage; relative `working_dirs` — rejected (GH-1264) |

### Behavioral caveats

The per-tool caveats live in `references/mcp-tools/` (GH-1606). Read
the file for the tool before relying on a payload field or a
non-obvious default:

| File | Tools |
|------|-------|
| [`caveats-writes.md`](../../references/mcp-tools/caveats-writes.md) | `task_index_*`, `pr_labels`, `issue_labels`, `notify_*` / `pr_notify` dead-letter log, `pr_ready`, `create_pr` (body, trailer, `head`, `milestone`, partial delivery), `merge_pr(use_bot)`, `pr_get` `files` |
| [`caveats-issues-and-push.md`](../../references/mcp-tools/caveats-issues-and-push.md) | `run_node_tests` runner detection, `create_pr(closes=…)`, `issue_create` / `issues_bulk_create`, `issue_close`, `push_safe` payload and protection tiers, `unresolved_threads` modes |
| [`caveats-ci-check-status.md`](../../references/mcp-tools/caveats-ci-check-status.md) | `ci_check_status` — `wait_out_pending`, `wait_for`, poll budget, transient failures, zero/green corroboration, `required_verdict: "empty"` |
| [`caveats-config-pins.md`](../../references/mcp-tools/caveats-config-pins.md) | `pin_tracker`, `pin_ide`, `pin_gate_preset`, `pin_supervisor_review` and their `*_status` readers, `resolve_gate` payload |

Defaulting `repo` from CWD has landed for `unresolved_threads`,
`check_top_level_comments` and `ci_check_status` (GH-1683). Parameter
normalization for aliases, `repo` defaulting on the remaining tools
and richer `push_safe` diagnostics is tracked as follow-up work;
until it lands, the table above is the contract.

## Tool Availability

The minimum plugin version for each tool is recorded in
[`references/mcp-tools/availability.md`](../../references/mcp-tools/availability.md).
When adding a new tool, add its row there.

### A Bash guardrail does not constrain an MCP tool that shells out (GH-1261)

`_validate_bash_body` returns on `tool_name != "Bash"` before a single
validator runs. So an MCP tool that executes a shell command or evaluates
arbitrary code — `execute_terminal_command`, `execute_code_on_kernel`,
`execute_tool`, or whatever the next server calls its equivalent — is a
Bash call that the Bash layer never sees. Allowing one voids **all** of:

- DX001–DX016, the entire PreToolUse validator chain (the same early
  return GH-1211/GH-1212 documented for `Monitor`);
- every `Bash()` deny in settings — `sudo`, `git push --force`,
  `rm -rf /`, `gh api --method DELETE`, `git config --global`;
- the skill-redirect hook, so nothing routes `gh pr edit` to `update_pr`.

This is GH-1260's sharpest case: rules and hooks match a **tool name and
a command string**, never an **effect**. Assess every new server against
it — a shell or eval tool belongs in `deny`, not in the allow catalog,
and that deny is unconditional rather than keyed to whether the user
picked that IDE. `plugin-doctor`'s `shell-equivalent-mcp-tools` strategy
flags them, but detection is by name and so is a floor, not a guarantee.

### A registered tool is not a pre-approved tool (GH-1153)

Neither the availability table nor a skill's `allowed-tools:` grants
permission.
The only thing `ensure-base` seeds into settings files is
`base_permissions` in `skills/upgrade-cleanup/projects.yaml`, so a tool
missing from that catalog prompts on **every** call, in every project,
forever — while looking fully wired up everywhere a reader would think
to check.

`triage_roster` was the worked example: registered, declared in
`dev10x:ticket-create`'s front matter, and present in the availability
table — and still prompting. The guard that found six more of them
(`audit_hook_log_path`, `audit_hook_recent`, `background_preamble`,
`resolve_plugin_origin`, `slack_thread_is_forward`, all read-only and
all now catalogued) is
`tests/skills/permission/test_catalog_covers_mcp_tools.py`.

So a new tool needs **three** edits, not two:

1. the `@server.tool()` registration,
2. a row in `references/mcp-tools/availability.md`,
3. an entry in `base_permissions` — or, for a tool that mutates state,
   an entry in `dev10x.skills.permission.enumerate_mcp.WRITE_TOOLS_NOT_SEEDED`
   so it keeps prompting on purpose.

`permission enumerate-mcp` reports un-catalogued tools at runtime from
that same exclusion set, so the CLI and the test cannot disagree.

**Not every write is excluded (GH-1215).** A write whose raw-CLI
equivalent the skill-redirect hook *blocks* — everything in the routed
map below (`gh pr edit` → `update_pr`, `gh pr ready` → `pr_ready`, the
`milestone_*` family, and the `task_index_*` trio, which is the park
family's only sanctioned write path) — belongs in `base_permissions`
alongside the already-catalogued `create_pr` / `issue_create` /
`push_safe`. Declining to seed the only remaining route does not add a
safety margin; it makes the sanctioned path prompt while the
unsanctioned one is denied, leaving the caller nowhere to go.
`WRITE_TOOLS_NOT_SEEDED` is for writes a caller can reasonably be
stopped on: `merge_pr`, the three `pin_*` policy writers,
`request_sampling`, `record_rule_feedback`, `record_upgrade`.

**The guard only sees what discovery sees (GH-1215).** `discover_mcp_tools()`
scanned a hard-coded five-module list against twelve tool modules and
matched only `@server.tool()`, so `@github_tool`-wrapped handlers —
48 of ~50 GitHub tools — were invisible along with all of
`gate_tools.py`. The guard passed 3/3 on develop while blind to roughly
four fifths of the surface, `resolve_gate` included. Discovery now globs
`src/dev10x/mcp/*_tools.py` and accepts any decorator named `*_tool`,
and `test_discovery_sees_every_registration` counts registration
decorators in the tree and fails when discovery finds fewer — so
narrowing the scan fails loudly instead of shrinking the guard's field
of view. A new registration wrapper must keep the `_tool` suffix.

## Skill Usage

In SKILL.md, declare MCP tool access via `allowed-tools:`:

```yaml
allowed-tools:
  - mcp__plugin_dev10x_cli__detect_tracker
  - mcp__plugin_dev10x_cli__pr_comments
  - Bash(/path/to/script:*)
```

Use wildcard sparingly: `mcp__plugin_dev10x_cli__*` grants access to all cli
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
mcp__plugin_dev10x_cli__mktmp(namespace="git", prefix="msg", ext=".txt")

# ⚠️ FALLBACK — direct script (needs Bash allow-rule)
/tmp/Dev10x/bin/mktmp.sh git msg .txt
```

Use the direct script only when the MCP server is unavailable
(e.g., inside a shell script that runs outside Claude's tool-use
protocol).

### MCP tool names cannot appear in shell scripts

MCP tool names (e.g., `mcp__plugin_dev10x_cli__mktmp`) are
Claude tool-call primitives. They cannot be used inside bash
code blocks, shell scripts, or Makefiles — only via Claude's
tool-use protocol.

```bash
# ❌ WRONG — MCP name in a bash block (not a shell command)
mcp__plugin_dev10x_cli__mktmp git commit-msg .txt

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
| `gh issue view` | `mcp__plugin_dev10x_cli__issue_get` |
| `gh issue create` | `mcp__plugin_dev10x_cli__issue_create` |
| `gh issue edit` | `mcp__plugin_dev10x_cli__issue_edit` |
| `gh issue edit --add-label` / `--remove-label` | `mcp__plugin_dev10x_cli__issue_labels` (GH-1322) |
| `gh issue close` | `mcp__plugin_dev10x_cli__issue_close` |
| `gh issue reopen` | `mcp__plugin_dev10x_cli__issue_reopen` |
| `gh issue comment` | `mcp__plugin_dev10x_cli__issue_comment` |
| `gh issue list` | `mcp__plugin_dev10x_cli__issue_list` (advisory) |
| `gh pr view` | `mcp__plugin_dev10x_cli__pr_get` |
| `gh pr list` | `mcp__plugin_dev10x_cli__pr_list` (GH-1359, advisory) |
| `gh api .../milestones POST` | `mcp__plugin_dev10x_cli__milestone_create` |
| `gh api .../milestones/{n} PATCH state=open` | `mcp__plugin_dev10x_cli__milestone_reopen` |
| `gh api .../milestones/{n} PATCH` (title/desc/state/due) | `mcp__plugin_dev10x_cli__milestone_edit` |
| `gh api .../milestones GET` | `mcp__plugin_dev10x_cli__milestone_list` (GH-1319) |
| `gh pr edit` | `mcp__plugin_dev10x_cli__update_pr` |
| `gh pr ready` | `mcp__plugin_dev10x_cli__pr_ready` |
| `gh pr edit --add-label` / `--remove-label` | `mcp__plugin_dev10x_cli__pr_labels` (GH-1008) |
| `gh pr close` | `mcp__plugin_dev10x_cli__pr_close` (GH-924) |
| `gh api .../check-suites/{id}/rerequest` / `.../actions/runs/{id}/rerun` (POST) | `mcp__plugin_dev10x_cli__ci_rerun` (GH-1674, advisory) |
| `gh pr create` | `dev10x:gh-pr-create` (wraps `create_pr`) |
| `gh pr merge` | `dev10x:gh-pr-merge` (wraps `merge_pr`) |

For a stale severity token in a **review body** (state=COMMENTED)
that trips gh-pr-merge Check 1b, edit it via
`mcp__plugin_dev10x_cli__pr_review_edit` (GH-778) — the review-body
counterpart to `pr_review_comment_edit` (inline) and
`issue_comment_edit` (top-level).

### Routed test commands (S12 map)

The `diag-friction` command-skill map (`command-skill-map.yaml`)
advisorily routes test runners to MCP wrappers so they run off the
Bash layer — sidestepping the core-harness brace-expansion block that
no allow-rule can suppress (GH-703).

| Raw command | MCP tool |
|-------------|----------|
| `pytest` / `uv run pytest` | `dev10x:py-test` (wraps `run_tests`) |
| `jest` / `yarn … test` / `npm test` / `pnpm test` / `vitest` | `mcp__plugin_dev10x_cli__run_node_tests` |

`run_node_tests` accepts a `runner` arg (`jest`, `vitest`, `yarn`,
`npm`, `pnpm`). When omitted, the runner is detected from `cwd`, with
`jest` only as the final fallback (see the runner-detection caveat in
`references/mcp-tools/caveats-issues-and-push.md`); `jest`/`vitest`
get `--coverage` when `coverage=true`.

Its `cwd` — like every tool's — must be **absolute** (GH-1264). A
relative path is now rejected at the `use_cwd` seam rather than
resolved against the long-lived server's own directory, which is not
the caller's checkout: `cwd="apps/web"` ran somewhere else entirely and
returned green, certifying a tree the worker had never written to. The
success payload also carries `cwd`, the directory the run actually
happened in, so a green result can be audited instead of trusted.

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
The internal `dev10x:cli` server is the sole GitHub surface — its
composite tools are shaped to Dev10x workflows rather than mirroring
the REST/GraphQL primitives.

When a new GitHub capability is needed (Actions, code scanning,
notifications, etc.), add a Dev10x-shaped composite tool to this
server rather than pulling in the official one. The official server's
source is a useful reference for endpoints and GraphQL queries; it
is not a runtime dependency.

Full rationale, overlap map, and implementation plan:
[`docs/adr/0006-keep-internal-github-mcp-over-official-server.md`](../../docs/adr/0006-keep-internal-github-mcp-over-official-server.md).
