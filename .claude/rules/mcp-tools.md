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

All MCP tools must follow this structure:

```python
@server.tool()
async def function_name(param: str, optional: str | None = None) -> dict:
    """Brief description of what the tool does."""
    # implementation
    if error_occurs:
        return {"error": "descriptive message"}
    return {tool-specific fields}  # see examples below
```

**Important**: Error responses are uniform (`{"error": msg}`), but success
responses are **tool-specific**. Document your tool's return structure in
its docstring. Examples:
- `mktmp`: returns `{"path": "/tmp/file"}`
- Some tools return `{"success": True, "data": result}`
- Some tools return only tool-specific fields without a `success` flag

Callers must know each tool's specific success response format.

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
| `request_review` | `cli` | PR #126 | v0.25.0+ |
| `detect_base_branch` | `cli` | PR #191 | v0.30.0+ |
| `verify_pr_state` | `cli` | PR #191 | v0.30.0+ |
| `pre_pr_checks` | `cli` | PR #191 | v0.30.0+ |
| `create_pr` | `cli` | PR #191 | v0.30.0+ |
| `update_pr` | `cli` | GH-60 | v0.70.0+ |
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
