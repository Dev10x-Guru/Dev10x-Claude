"""Enumerate MCP tool glob patterns in settings files.

Claude Code's permission system does not expand `mcp__plugin_Dev10x_*`
globs — the rule must name each tool explicitly. When a settings file
contains a glob-shaped MCP allow rule, every MCP call still triggers a
manual approval prompt because the glob silently matches nothing.

This module discovers Dev10x MCP tools from the plugin's own MCP
servers and replaces matching wildcards in settings files with
enumerated tool names.
"""

from __future__ import annotations

import ast
import json
import re
from collections.abc import Iterable
from pathlib import Path

# Wildcard shapes that silently fail: `mcp__plugin_Dev10x_*`,
# `mcp__plugin_Dev10x_cli_*`, `mcp__<family>__*`, etc.
MCP_WILDCARD_RE = re.compile(r"^mcp__[A-Za-z0-9_]+\*$")

# MCP server registration file convention.
# For the cli server, all handlers live in per-domain modules (GH-243/A6).
# Each entry maps a plugin server key to one or more relative file paths.
_SERVER_FILES: dict[str, list[str]] = {
    "Dev10x_cli": [
        "src/dev10x/mcp/github_tools.py",
        "src/dev10x/mcp/git_tools.py",
        "src/dev10x/mcp/plan_tools.py",
        "src/dev10x/mcp/audit_tools.py",
        "src/dev10x/mcp/misc_tools.py",
    ],
    "Dev10x_db": ["src/dev10x/mcp/server_db.py"],
}


def plugin_root() -> Path:
    """Return the plugin root containing `src/`, `servers/`, and `skills/`."""
    return Path(__file__).resolve().parents[4]


def _parse_tool_names(server_file: Path) -> list[str]:
    """Extract @server.tool() function names from a server registration file.

    Uses ast so it works even when the file imports modules we don't have
    at cleanup time (e.g., the mcp library on a machine without mcp
    installed).
    """
    if not server_file.is_file():
        return []
    source = server_file.read_text()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    names: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
            continue
        for decorator in node.decorator_list:
            if _is_server_tool_decorator(decorator):
                names.append(node.name)
                break
    return names


def _is_server_tool_decorator(node: ast.expr) -> bool:
    """Detect `@server.tool()` decorators without importing mcp."""
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Attribute):
        return node.attr == "tool" and isinstance(node.value, ast.Name)
    return False


def discover_mcp_tools(*, root: Path | None = None) -> dict[str, list[str]]:
    """Return `{plugin_server: [fully-qualified tool names]}` for this plugin.

    Example key/value::

        {
            "Dev10x_cli": [
                "mcp__plugin_Dev10x_cli__detect_tracker",
                "mcp__plugin_Dev10x_cli__pr_detect",
                ...
            ],
        }
    """
    root = root or plugin_root()
    catalog: dict[str, list[str]] = {}
    for server, rel_paths in _SERVER_FILES.items():
        names: list[str] = []
        for rel_path in rel_paths:
            names.extend(_parse_tool_names(root / rel_path))
        if not names:
            continue
        server_key = server.split("_", 1)[1] if "_" in server else server
        prefix = f"mcp__plugin_Dev10x_{server_key}__"
        catalog[server] = sorted(f"{prefix}{name}" for name in names)
    return catalog


def _matches_wildcard(rule: str, catalog: dict[str, list[str]]) -> list[str] | None:
    """Return enumerated tools if `rule` is a Dev10x MCP wildcard, else None.

    - `mcp__plugin_Dev10x_*` matches every server in the catalog
    - `mcp__plugin_Dev10x_cli_*` matches only the cli server
    """
    if not MCP_WILDCARD_RE.match(rule):
        return None

    matched: list[str] = []
    for server, tools in catalog.items():
        server_key = server.split("_", 1)[1] if "_" in server else server
        server_specific = f"mcp__plugin_Dev10x_{server_key}_*"
        if rule == server_specific:
            return list(tools)
        if rule.startswith("mcp__plugin_Dev10x_") and "_cli" not in rule and "_db" not in rule:
            matched.extend(tools)
    return matched or None


def expand_rules(
    allow: list[str],
    catalog: dict[str, list[str]],
) -> tuple[list[str], list[str], list[str]]:
    """Expand wildcard MCP rules in `allow`.

    Returns `(new_allow, removed_wildcards, added_tools)`.

    - Preserves ordering: wildcards are replaced in place with their
      enumerated tools, except tools already present elsewhere in
      `allow` are deduplicated.
    - If multiple wildcards in the same file expand to overlapping
      tool sets, the later duplicates are dropped.
    """
    new_allow: list[str] = []
    removed_wildcards: list[str] = []
    added_tools: list[str] = []
    seen: set[str] = set()

    for rule in allow:
        expanded = _matches_wildcard(rule, catalog)
        if expanded is None:
            if rule not in seen:
                new_allow.append(rule)
                seen.add(rule)
            continue

        removed_wildcards.append(rule)
        for tool in expanded:
            if tool not in seen:
                new_allow.append(tool)
                seen.add(tool)
                added_tools.append(tool)

    return new_allow, removed_wildcards, added_tools


def expand_settings_file(
    path: Path,
    catalog: dict[str, list[str]],
    *,
    dry_run: bool = False,
) -> tuple[int, list[str]]:
    """Apply `expand_rules` to a settings.local.json file.

    Returns `(changes, messages)` where `changes == removed + added`.
    """
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        return 0, [f"  SKIP (unreadable): {e}"]

    allow_list: list[str] = data.get("permissions", {}).get("allow", [])
    new_allow, removed, added = expand_rules(allow_list, catalog)

    if not removed and not added and new_allow == allow_list:
        return 0, []

    messages: list[str] = []
    for wc in removed:
        messages.append(f"  - {wc}  (wildcard removed — Claude Code does not expand MCP globs)")
    for tool in added:
        messages.append(f"  + {tool}")

    if not dry_run:
        from dev10x.skills.permission.backup import create_backup
        from dev10x.skills.permission.file_lock import locked_json_update

        create_backup(path)
        with locked_json_update(path=path) as live:
            permissions = live.setdefault("permissions", {})
            live_allow = permissions.setdefault("allow", [])
            live_new, _, _ = expand_rules(live_allow, catalog)
            permissions["allow"] = live_new

    return len(removed) + len(added), messages


def enumerate_settings(
    settings_files: Iterable[Path],
    *,
    dry_run: bool = False,
    quiet: bool = False,
) -> int:
    """Expand MCP wildcards across a collection of settings files.

    Returns the total count of rules changed (removed + added).
    """
    catalog = discover_mcp_tools()
    if not catalog:
        print("No Dev10x MCP tools discovered — is the plugin checked out?")
        return 0

    total = 0
    changed_files = 0
    for path in sorted(settings_files):
        count, messages = expand_settings_file(path, catalog, dry_run=dry_run)
        if count == 0:
            continue
        if not quiet:
            print(f"\n{path}")
            for msg in messages:
                print(msg)
        total += count
        changed_files += 1

    if total == 0:
        print("No MCP wildcards found — all settings files already enumerated.")
    else:
        verb = "Would expand" if dry_run else "Expanded"
        print(f"{verb} {total} rules across {changed_files} files.")
    return total
