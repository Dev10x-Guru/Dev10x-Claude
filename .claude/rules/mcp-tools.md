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
MCP boundary calls `.to_dict()` to produce the wire-format dict.

```python
# Internal module (audit/release/monitor/permission/plan/skill_index/
# utilities/github/db): public functions return Result[T].
from dev10x.domain.common.result import Result, err, ok

async def collect_prs(...) -> Result[dict[str, Any]]:
    if error_occurs:
        return err("descriptive message")
    return ok({tool-specific fields})

# MCP server boundary (src/dev10x/mcp/server_cli.py): unwrap via
# .to_dict() so external consumers see the uniform wire format.
@server.tool()
async def collect_prs(...) -> dict:
    """Brief description of what the tool does."""
    return (await rel.collect_prs(...)).to_dict()
```

**Wire format** (what callers see):
- `SuccessResult.to_dict()` → `{tool-specific fields}` (no `success` flag
  is added automatically — keep success payloads tool-specific).
- `ErrorResult.to_dict()` → `{"error": "descriptive message", ...}`
  (extra metadata like `messages`/`errors` is preserved).

**Why two layers**: internal callers branch on `isinstance(result,
SuccessResult)` for type-safe error handling; the MCP boundary keeps
the legacy dict shape so existing tool consumers don't break. New
modules MUST mirror the pattern — return `Result[T]` internally, call
`.to_dict()` at the `@server.tool()` boundary.

**Tool-specific success payloads**:
- `mktmp`: returns `{"path": "/tmp/file"}`
- Some tools return `{"success": True, "data": result}`
- Some tools return only tool-specific fields without a `success` flag
- `push_safe`: returns `{}` on a clean fast-forward push (GH-152) —
  emptiness is NOT failure; only `{"error": ...}` is failure. Verify
  the remote with `git ls-remote --heads origin <branch>` if a
  payload is needed.

Callers must know each tool's specific success response format. Branch
on the presence of an `"error"` key, never on whether the dict is
empty.

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
| `pr_comments` | `cli` | PR #126 | v0.25.0+ |
| `pr_comment_reply` | `cli` | PR #399 | v0.37.0+ |
| `pr_issue_comment` | `cli` | GH-205 | v0.72.0+ |
| `request_review` | `cli` | PR #126 | v0.25.0+ |
| `detect_base_branch` | `cli` | PR #191 | v0.30.0+ |
| `verify_pr_state` | `cli` | PR #191 | v0.30.0+ |
| `pre_pr_checks` | `cli` | PR #191 | v0.30.0+ |
| `create_pr` | `cli` | PR #191 | v0.30.0+ |
| `update_pr` | `cli` | GH-60 | v0.70.0+ |
| `milestone_close` | `cli` | GH-187 | v0.71.0+ |
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
