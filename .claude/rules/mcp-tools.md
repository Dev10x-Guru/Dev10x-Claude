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

## Canonical Parameter Shapes

Parameter naming is not uniform across tools, which defeats agent
first-call inference (GH-462 F4 — 7 first-call validation errors in
one session). Use these shapes verbatim:

| Tool | Required parameters | Common wrong guess |
|------|---------------------|--------------------|
| `issue_get` | `number` | `issue_id` |
| `pr_get` | `number` | `pr_number` |
| `pr_comments` | `pr_number`, `action` (no default) | omitting `action` |
| `unresolved_threads` | `repo` (no CWD default) | omitting `repo` |
| `check_top_level_comments` | `repo` (no CWD default) | omitting `repo` |
| `push_safe` | `args` list, e.g. `["-u", "origin", "<branch>"]` | bare call |
| `resolve_review_thread` | `thread_ids` (list) | singular `thread_id` |

Behavioral caveats:

- `push_safe` failure returns `{"pushed": false, "blocked_reason":
  "push_failed"}` with no further diagnostic; a successful push may
  return `{}` — treat any non-`error` payload without
  `"pushed": false` as success.
- `unresolved_threads` has timed out where the equivalent raw GraphQL
  query returned in under 2s; retry once before falling back per
  skill guidance.

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
| `gh pr edit` | `mcp__plugin_Dev10x_cli__update_pr` |
| `gh pr create` | `Dev10x:gh-pr-create` (wraps `create_pr`) |
| `gh pr merge` | `Dev10x:gh-pr-merge` (wraps `merge_pr`) |

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
