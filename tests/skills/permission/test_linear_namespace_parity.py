"""Linear is served under two MCP namespaces — keep them at parity (GH-1323).

``mcp__claude_ai_Linear__*`` (the claude.ai-hosted connector) and
``mcp__linear-server__*`` (the self-installed linear-server MCP) both
serve the same tracker, but only the second is the one Dev10x sessions
actually call. Before GH-1323 the catalog carried ~28 read-only
``claude_ai_Linear`` rules and only 5 same-shaped ``linear-server``
ones — a comment in ``projects.yaml`` claimed the two were at parity,
and nothing checked that claim, which is exactly how the gap survived
long enough to accumulate 11 ad-hoc per-call approvals in userspace
settings.

This guard replaces the comment with a test: every read-only operation
name catalogued under one Linear namespace's ``tracker_permissions.linear``
block must be catalogued under the other too. Write and delete operations
are excluded — those are a separate, per-tool judgement (GH-1215), not a
parity requirement, and the two namespaces are not expected to seed the
same write surface.
"""

from __future__ import annotations

from pathlib import Path

import yaml

import dev10x.skills.permission as permission_pkg
from dev10x.skills.permission.catalog_paths import CATALOG_RELPATH

PERMISSION_DIR = Path(permission_pkg.__file__).resolve().parent
REPO_ROOT = PERMISSION_DIR.parents[3]
PROJECTS_YAML = REPO_ROOT / CATALOG_RELPATH

CLAUDE_AI_PREFIX = "mcp__claude_ai_Linear__"
LINEAR_SERVER_PREFIX = "mcp__linear-server__"

#: Operation-name prefixes that count as read-only. `save_*` (write) and
#: `delete_*` (destructive) are deliberately excluded from parity — a
#: write on one namespace catalogued and not the other is a documented,
#: intentional judgement call, not a gap.
_WRITE_PREFIXES = ("save_", "delete_")


def _linear_block() -> list[str]:
    config = yaml.safe_load(PROJECTS_YAML.read_text(encoding="utf-8"))
    return list((config.get("tracker_permissions") or {}).get("linear") or [])


def _read_ops(rules: list[str], *, prefix: str) -> set[str]:
    return {
        rule.removeprefix(prefix)
        for rule in rules
        if rule.startswith(prefix) and not rule.removeprefix(prefix).startswith(_WRITE_PREFIXES)
    }


def test_linear_namespace_read_ops_are_at_parity() -> None:
    rules = _linear_block()
    claude_ai_reads = _read_ops(rules, prefix=CLAUDE_AI_PREFIX)
    linear_server_reads = _read_ops(rules, prefix=LINEAR_SERVER_PREFIX)

    missing_from_linear_server = claude_ai_reads - linear_server_reads
    assert not missing_from_linear_server, (
        "mcp__claude_ai_Linear__* catalogues these read ops but "
        "mcp__linear-server__* — the namespace Dev10x sessions actually "
        "call — does not; add the mcp__linear-server__ counterparts to "
        "tracker_permissions.linear in skills/upgrade-cleanup/projects.yaml:\n"
        + "\n".join(f"  {op}" for op in sorted(missing_from_linear_server))
    )


def test_linear_namespace_has_both_variants_present() -> None:
    # A parity check over two empty sets passes vacuously — assert both
    # namespaces are genuinely represented so the guard cannot go blind
    # if one block is ever emptied by accident.
    rules = _linear_block()
    assert any(rule.startswith(CLAUDE_AI_PREFIX) for rule in rules)
    assert any(rule.startswith(LINEAR_SERVER_PREFIX) for rule in rules)


def test_linear_server_only_ops_are_documented_exceptions() -> None:
    # linear-server carries read ops with no claude_ai_Linear counterpart
    # at all (e.g. get_release — the claude.ai connector has no such
    # tool). Those are not a parity gap; they are catalogued because the
    # tool demonstrated real ad-hoc usage (GH-1323 item 4). This test
    # pins the known set so a *new* linear-server-only addition is a
    # conscious edit here, not a silent expansion of the exception.
    rules = _linear_block()
    claude_ai_reads = _read_ops(rules, prefix=CLAUDE_AI_PREFIX)
    linear_server_reads = _read_ops(rules, prefix=LINEAR_SERVER_PREFIX)

    extra = linear_server_reads - claude_ai_reads
    assert extra == {"get_release"}, (
        "mcp__linear-server__* catalogues read ops with no "
        "mcp__claude_ai_Linear__ counterpart beyond the documented "
        "exception set {'get_release'} — update this test's expected "
        f"set if the addition is intentional. Found: {sorted(extra)}"
    )
