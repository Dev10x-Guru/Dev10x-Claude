"""Every registered read-only MCP tool must be in the permission catalog.

GH-1153: ``triage_roster`` was registered as an MCP tool, declared in
``Dev10x:ticket-create``'s ``allowed-tools`` front matter, and listed in
``.claude/rules/mcp-tools.md`` — and still prompted on every call,
because none of those three grants anything. Only a catalog entry does:
``ensure-base`` seeds settings files from ``base_permissions``, so a tool
absent from the catalog can never be pre-approved.

Nothing mechanical caught the omission. Registering a tool and
cataloguing it are separate edits in separate files, and the gap is
invisible until a user hits the prompt. This test closes that by
diffing the registered ``@server.tool`` names against the catalog.

Write tools are deliberately NOT seeded — a destructive operation should
keep prompting — so they are named individually in
``WRITE_TOOLS_NOT_SEEDED`` rather than filtered by a verb heuristic. An
explicit list means adding a write tool is a conscious edit, while a
heuristic would silently absorb a read tool whose name happens to start
with a write-ish verb.

That list is imported from ``enumerate_mcp`` rather than restated here:
``permission enumerate-mcp`` reports the same gap at runtime, and two
copies of the exclusion set would eventually disagree about which tools
are writes.

``test_exclusion_list_names_only_registered_tools`` doubles as a canary:
if tool discovery ever returns nothing, it fails rather than letting its
sibling pass vacuously on an empty set.

That canary was not enough. GH-1215: discovery can return *most* of the
surface and still be blind to the rest, which reads as a healthy pass.
``test_discovery_sees_every_registration`` closes it by counting the
registration decorators in ``src/dev10x/mcp/`` directly and asserting
discovery found at least that many — so narrowing the module list or the
decorator shapes fails loudly instead of shrinking the guard's field of
view.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

import dev10x.skills.permission as permission_pkg
from dev10x.skills.permission.enumerate_mcp import (
    WRITE_TOOLS_NOT_SEEDED,
    discover_mcp_tools,
)

REPO_ROOT = Path(permission_pkg.__file__).resolve().parents[4]
PROJECTS_YAML = REPO_ROOT / "skills" / "upgrade-cleanup" / "projects.yaml"
MCP_DIR = REPO_ROOT / "src" / "dev10x" / "mcp"

#: A decorator line that registers an MCP tool: the direct FastMCP form
#: (``@server.tool()``) or a module-level wrapper around it, which this
#: codebase names with a ``_tool`` suffix (``@github_tool``). Resources
#: and prompts (``@server.resource``/``@server.prompt``) are excluded —
#: they carry no permission rule.
_REGISTRATION_DECORATOR = re.compile(r"^@(?:\w+\.tool\(|\w+_tool\s*$)", re.MULTILINE)


def _catalogued_rules() -> set[str]:
    config = yaml.safe_load(PROJECTS_YAML.read_text())
    rules: set[str] = set(config.get("base_permissions") or [])
    for tracker_rules in (config.get("tracker_permissions") or {}).values():
        rules.update(tracker_rules or [])
    return rules


def _registered_tools() -> set[str]:
    # Pinned to this checkout. discover_mcp_tools() defaults to
    # resolve_plugin_root(), whose fallback chain reaches $CLAUDE_PLUGIN_ROOT
    # and then the newest installed copy — so an unpinned call could diff an
    # INSTALLED plugin's registrations against this tree's catalog and report
    # a gap, or a clean pass, that describes neither.
    return {tool for tools in discover_mcp_tools(root=REPO_ROOT).values() for tool in tools}


def test_every_registered_tool_is_catalogued_or_explicitly_excluded() -> None:
    uncatalogued = _registered_tools() - _catalogued_rules() - WRITE_TOOLS_NOT_SEEDED
    assert not uncatalogued, (
        "these MCP tools are registered but absent from base_permissions, so "
        "ensure-base cannot seed them and every caller will prompt — add them "
        "to skills/upgrade-cleanup/projects.yaml, or to WRITE_TOOLS_NOT_SEEDED "
        "if they mutate state and should keep prompting:\n" + "\n".join(sorted(uncatalogued))
    )


def test_exclusion_list_names_only_registered_tools() -> None:
    stale = WRITE_TOOLS_NOT_SEEDED - _registered_tools()
    assert not stale, (
        "WRITE_TOOLS_NOT_SEEDED names tools that are no longer registered — "
        "a renamed or deleted tool left behind here would mask a real "
        "catalog gap for its replacement:\n" + "\n".join(sorted(stale))
    )


def _registration_decorator_count() -> int:
    return sum(
        len(_REGISTRATION_DECORATOR.findall(module.read_text())) for module in MCP_DIR.glob("*.py")
    )


def test_discovery_sees_every_registration() -> None:
    declared = _registration_decorator_count()
    discovered = len(_registered_tools())
    assert declared > 0, f"no MCP registration decorators found under {MCP_DIR}"
    assert discovered >= declared, (
        f"discovery found {discovered} MCP tools but {declared} registration "
        f"decorators exist under {MCP_DIR}. discover_mcp_tools() is scanning a "
        "subset — widen _SERVER_GLOBS or _is_server_tool_decorator in "
        "enumerate_mcp.py. A narrowed discovery makes the catalog guard below "
        "pass green while blind to the tools it cannot see (GH-1215)."
    )


def test_gate_tools_are_discovered() -> None:
    # resolve_gate lives in gate_tools.py, one of the seven modules the old
    # hard-coded _SERVER_FILES list never scanned — and it is called by every
    # skill gate, so its absence from the catalog cost a prompt per checkout.
    assert "mcp__plugin_Dev10x_cli__resolve_gate" in _registered_tools()


def test_github_tool_wrapped_handlers_are_discovered() -> None:
    # pr_get is registered through the @github_tool wrapper, the shape the
    # old AST matcher could not see (48 of ~50 GitHub handlers use it).
    assert "mcp__plugin_Dev10x_cli__pr_get" in _registered_tools()


def test_triage_roster_is_catalogued() -> None:
    assert "mcp__plugin_Dev10x_cli__triage_roster" in _catalogued_rules()
