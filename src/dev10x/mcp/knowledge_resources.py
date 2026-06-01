"""MCP resource registrations for Dev10x knowledge primitives (GH-339).

Exposes playbooks, rules/INDEX.md + references/rules/*, and the skill
index as addressable MCP resources so consumers can read them via URI
instead of issuing Bash tool-calls or searching the filesystem.

Resource URIs:
    dev10x://skills/{skill_name}/playbook
        - YAML playbook for the named skill
        - 404-style error text when no playbook.yaml exists

    dev10x://rules/index
        - Contents of .claude/rules/INDEX.md

    dev10x://rules/{rule_name}
        - Contents of .claude/rules/{rule_name}.md

    dev10x://references/{ref_name}
        - Contents of references/{ref_name}.md

    dev10x://skills/index
        - Contents of SKILLS.md (generated skill index)

All resources are served from the plugin root resolved at request time
via ``get_plugin_root()`` so the live working-tree copy is used during
development and the cached install is used in production.  See
``subprocess_utils.get_plugin_root`` for the resolution logic.
"""

from __future__ import annotations

from pathlib import Path

from dev10x.mcp._app import server
from dev10x.subprocess_utils import get_plugin_root


def _read_file(path: Path) -> str:
    """Return file contents or a descriptive error string when missing."""
    if not path.exists():
        return f"# Not found\n\nNo file at `{path}`."
    return path.read_text(encoding="utf-8")


def _reject_traversal(name: str) -> str | None:
    """Return an error string when *name* could escape its resource root.

    The MCP framework constrains URI template segments, but resource
    names are interpolated into filesystem paths, so reject traversal
    sequences explicitly as defense-in-depth (GH-339 review).
    """
    if ".." in name or "/" in name or "\\" in name:
        return f"# Invalid name\n\n`{name}` contains path-traversal characters."
    return None


# ── skill playbooks ────────────────────────────────────────────────


@server.resource(
    uri="dev10x://skills/{skill_name}/playbook",
    name="skill-playbook",
    description="YAML playbook for a named Dev10x skill",
    mime_type="application/yaml",
)
def skill_playbook(skill_name: str) -> str:
    """Return the playbook.yaml for *skill_name*, or an error string."""
    if invalid := _reject_traversal(name=skill_name):
        return invalid
    path = get_plugin_root() / "skills" / skill_name / "references" / "playbook.yaml"
    return _read_file(path)


# ── rules ─────────────────────────────────────────────────────────


@server.resource(
    uri="dev10x://rules/index",
    name="rules-index",
    description="Dev10x .claude/rules/INDEX.md — agent routing and rule directory",
    mime_type="text/markdown",
)
def rules_index() -> str:
    """Return the contents of .claude/rules/INDEX.md."""
    path = get_plugin_root() / ".claude" / "rules" / "INDEX.md"
    return _read_file(path)


@server.resource(
    uri="dev10x://rules/{rule_name}",
    name="rule-file",
    description="A single Dev10x rule file from .claude/rules/",
    mime_type="text/markdown",
)
def rule_file(rule_name: str) -> str:
    """Return the contents of .claude/rules/{rule_name}.md."""
    if invalid := _reject_traversal(name=rule_name):
        return invalid
    path = get_plugin_root() / ".claude" / "rules" / f"{rule_name}.md"
    return _read_file(path)


# ── shared references ──────────────────────────────────────────────


@server.resource(
    uri="dev10x://references/{ref_name}",
    name="reference-file",
    description="A Dev10x shared reference document from references/",
    mime_type="text/markdown",
)
def reference_file(ref_name: str) -> str:
    """Return the contents of references/{ref_name}.md."""
    if invalid := _reject_traversal(name=ref_name):
        return invalid
    path = get_plugin_root() / "references" / f"{ref_name}.md"
    return _read_file(path)


# ── skill index ────────────────────────────────────────────────────


@server.resource(
    uri="dev10x://skills/index",
    name="skills-index",
    description="Dev10x SKILLS.md — the generated skill index",
    mime_type="text/markdown",
)
def skills_index() -> str:
    """Return the contents of SKILLS.md from the plugin root."""
    path = get_plugin_root() / "SKILLS.md"
    return _read_file(path)
