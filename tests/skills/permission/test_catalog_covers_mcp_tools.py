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
"""

from __future__ import annotations

from pathlib import Path

import yaml

import dev10x.skills.permission as permission_pkg
from dev10x.skills.permission.enumerate_mcp import (
    WRITE_TOOLS_NOT_SEEDED,
    discover_mcp_tools,
)

REPO_ROOT = Path(permission_pkg.__file__).resolve().parents[4]
PROJECTS_YAML = REPO_ROOT / "skills" / "upgrade-cleanup" / "projects.yaml"


def _catalogued_rules() -> set[str]:
    config = yaml.safe_load(PROJECTS_YAML.read_text())
    rules: set[str] = set(config.get("base_permissions") or [])
    for tracker_rules in (config.get("tracker_permissions") or {}).values():
        rules.update(tracker_rules or [])
    return rules


def _registered_tools() -> set[str]:
    return {tool for tools in discover_mcp_tools().values() for tool in tools}


def test_every_registered_tool_is_catalogued_or_explicitly_excluded() -> None:
    uncatalogued = _registered_tools() - _catalogued_rules() - WRITE_TOOLS_NOT_SEEDED
    assert "\n".join(sorted(uncatalogued)) == "", (
        "these MCP tools are registered but absent from base_permissions, so "
        "ensure-base cannot seed them and every caller will prompt — add them "
        "to skills/upgrade-cleanup/projects.yaml, or to WRITE_TOOLS_NOT_SEEDED "
        "if they mutate state and should keep prompting"
    )


def test_exclusion_list_names_only_registered_tools() -> None:
    stale = WRITE_TOOLS_NOT_SEEDED - _registered_tools()
    assert "\n".join(sorted(stale)) == "", (
        "WRITE_TOOLS_NOT_SEEDED names tools that are no longer registered — "
        "a renamed or deleted tool left behind here would mask a real "
        "catalog gap for its replacement"
    )


def test_triage_roster_is_catalogued() -> None:
    assert "mcp__plugin_Dev10x_cli__triage_roster" in _catalogued_rules()
