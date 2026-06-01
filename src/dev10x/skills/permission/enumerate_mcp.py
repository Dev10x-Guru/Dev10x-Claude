"""Enumerate MCP tool glob patterns in settings files.

Claude Code's permission system does not expand `mcp__plugin_Dev10x_*`
globs — the rule must name each tool explicitly. When a settings file
contains a glob-shaped MCP allow rule, every MCP call still triggers a
manual approval prompt because the glob silently matches nothing.

This module discovers Dev10x MCP tools from the plugin's own MCP
servers and replaces matching wildcards in settings files with
enumerated tool names.

**Runtime discovery (GH-371):** `discover_all_mcp_servers` extends
`discover_mcp_tools` (plugin-only) with all MCP servers connected to
the current Claude session, regardless of source type:

- ``mcp__claude_ai_<Service>__*``  — claude.ai-hosted servers
- ``mcp__<service>__*``            — user-installed via ``claude mcp add``
- ``mcp__plugin_<plugin>_<srv>__*`` — plugin-distributed servers

**capability_group annotation (GH-371):** When the same capability is
offered by multiple prefixes (horizontal duplicates), an annotation
links the policy entries so the doctor can surface consolidation
opportunities without forcing them.
"""

from __future__ import annotations

import ast
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
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


@dataclass
class McpServerEntry:
    """Represents one discovered MCP server with its tool list.

    Attributes:
        prefix: The MCP prefix pattern, e.g. ``mcp__claude_ai_Sentry__``.
        source_type: One of ``claude_ai``, ``user_installed``, ``plugin``.
        service_name: Human-readable service label, e.g. ``Sentry``.
        tools: Fully-qualified tool names under this prefix.
    """

    prefix: str
    source_type: str
    service_name: str
    tools: list[str] = field(default_factory=list)


@dataclass
class CapabilityGroupEntry:
    """Links policy entries that share the same logical capability.

    Used by the ``mcp-horizontal-duplicates`` doctor strategy to surface
    cases where N servers each offer the same capability under different
    prefixes. The annotation does not force consolidation; it surfaces
    the duplication for user awareness.

    Attributes:
        capability_group: Stable slug for the capability, e.g.
            ``sentry-search-issues``.
        tool_name: Short tool name without the prefix, e.g.
            ``search_issues``.
        entries: (prefix, full_tool_name) pairs for each server that
            offers this capability.
    """

    capability_group: str
    tool_name: str
    entries: list[tuple[str, str]] = field(default_factory=list)

    @property
    def server_count(self) -> int:
        return len(self.entries)

    def is_duplicate(self) -> bool:
        return self.server_count > 1


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


def _server_prefix_from_tool(tool_name: str) -> str | None:
    """Return the server prefix for a fully-qualified MCP tool name.

    ``mcp__claude_ai_Sentry__search_issues``
      → ``mcp__claude_ai_Sentry__``

    ``mcp__sentry__search_issues``
      → ``mcp__sentry__``
    """
    # Split on __ (double underscore); the prefix ends before the final segment
    parts = tool_name.split("__")
    # Valid names: mcp  <server>  <func_name>
    if len(parts) < 3:
        return None
    # Re-join the middle segment(s) with __ and append the trailing __
    return "__".join(parts[:-1]) + "__"


def _source_type_from_prefix(prefix: str) -> tuple[str, str]:
    """Return (source_type, service_name) for a server prefix.

    Examples::

        mcp__claude_ai_Sentry__  → ("claude_ai", "Sentry")
        mcp__sentry__            → ("user_installed", "sentry")
        mcp__plugin_sentry_sentry__ → ("plugin", "sentry_sentry")
    """
    # Strip leading mcp__ and trailing __
    inner = prefix.removeprefix("mcp__").removesuffix("__")
    if inner.startswith("claude_ai_"):
        return "claude_ai", inner.removeprefix("claude_ai_")
    if inner.startswith("plugin_"):
        return "plugin", inner.removeprefix("plugin_")
    return "user_installed", inner


def discover_all_mcp_servers(
    *,
    settings_paths: Iterable[Path] | None = None,
) -> list[McpServerEntry]:
    """Enumerate ALL MCP servers by scanning allow rules in settings files.

    Unlike ``discover_mcp_tools`` (which only knows about this plugin's
    servers), this function discovers every MCP server whose tools appear
    in the user's allow rules — regardless of source type.

    The three source types (GH-371):

    - ``claude_ai``      — ``mcp__claude_ai_<Service>__*``
    - ``user_installed`` — ``mcp__<service>__*``
    - ``plugin``         — ``mcp__plugin_<plugin>_<server>__*``

    Args:
        settings_paths: Settings files to scan. Defaults to the standard
            user and global settings locations when omitted.

    Returns:
        Deduplicated list of :class:`McpServerEntry` objects, one per
        distinct server prefix found in any allow rule.
    """
    if settings_paths is None:
        home = Path.home()
        settings_paths = [
            home / ".claude" / "settings.json",
            home / ".claude" / "settings.local.json",
        ]

    prefix_to_entry: dict[str, McpServerEntry] = {}

    for path in settings_paths:
        if not Path(path).is_file():
            continue
        try:
            data = json.loads(Path(path).read_text())
        except (OSError, json.JSONDecodeError):
            continue

        all_rules: list[str] = []
        perms = data.get("permissions", {})
        for bucket in ("allow", "deny", "ask"):
            bucket_rules = perms.get(bucket, [])
            if isinstance(bucket_rules, list):
                all_rules.extend(r for r in bucket_rules if isinstance(r, str))

        for rule in all_rules:
            if not rule.startswith("mcp__"):
                continue
            prefix = _server_prefix_from_tool(rule)
            if prefix is None:
                continue
            if prefix in prefix_to_entry:
                if rule not in prefix_to_entry[prefix].tools:
                    prefix_to_entry[prefix].tools.append(rule)
                continue
            source_type, service_name = _source_type_from_prefix(prefix)
            entry = McpServerEntry(
                prefix=prefix,
                source_type=source_type,
                service_name=service_name,
                tools=[rule],
            )
            prefix_to_entry[prefix] = entry

    return sorted(prefix_to_entry.values(), key=lambda e: e.prefix)


def build_capability_groups(
    servers: Iterable[McpServerEntry],
) -> list[CapabilityGroupEntry]:
    """Detect horizontal duplicates across MCP servers (GH-371).

    Two tool entries share a ``capability_group`` when they have the
    same short tool name (the part after the last ``__``) AND appear
    under different server prefixes.

    This function only groups tool names that actually appear in at
    least two distinct server entries — single-server tools are
    omitted.

    Returns:
        List of :class:`CapabilityGroupEntry` objects for each
        capability that spans more than one server.
    """
    # tool_name → [(prefix, full_tool_name)]
    by_short_name: dict[str, list[tuple[str, str]]] = {}

    for server_entry in servers:
        for full_name in server_entry.tools:
            parts = full_name.split("__")
            if len(parts) < 3:
                continue
            short_name = parts[-1]
            by_short_name.setdefault(short_name, []).append((server_entry.prefix, full_name))

    groups: list[CapabilityGroupEntry] = []
    for short_name, pairs in sorted(by_short_name.items()):
        # Deduplicate by prefix — keep only one entry per server
        seen_prefixes: set[str] = set()
        deduped: list[tuple[str, str]] = []
        for prefix, full_name in pairs:
            if prefix not in seen_prefixes:
                seen_prefixes.add(prefix)
                deduped.append((prefix, full_name))
        if len(deduped) < 2:
            continue
        # Derive a stable capability_group slug from the short name
        capability_group = short_name.replace("_", "-")
        groups.append(
            CapabilityGroupEntry(
                capability_group=capability_group,
                tool_name=short_name,
                entries=deduped,
            )
        )
    return groups


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
