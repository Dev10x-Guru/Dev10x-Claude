"""CLI for playbook diagnostics (GH-192).

``dev10x playbook diff`` compares every user playbook override visible
from the current working directory against the matching plugin default
and prints a markdown report of upstream changes. User customizations
are preserved — the diff reports them but never writes.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import click
import yaml

from dev10x.skills.playbook import (
    compare_playbooks,
    find_user_playbooks,
    plugin_default_path,
    render_markdown_report,
)


def _resolve_plugin_root() -> Path | None:
    """Locate the active plugin root.

    Honors ``$CLAUDE_PLUGIN_ROOT`` first (set by Claude Code when invoking
    skills) and falls back to walking up from this file. Returns ``None``
    when no plausible root is found so callers can emit a useful error.
    """
    env_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if env_root:
        root = Path(env_root)
        if root.is_dir():
            return root
    candidate = Path(__file__).resolve().parent.parent.parent.parent
    if (candidate / "skills").is_dir() and (candidate / ".claude-plugin").is_dir():
        return candidate
    return None


def _load_yaml(path: Path) -> dict:
    """Load a YAML file. Empty files return ``{}``."""
    text = path.read_text()
    data = yaml.safe_load(text)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise click.ClickException(
            f"Expected a mapping at the top of {path}, got {type(data).__name__}"
        )
    return data


@click.group()
def playbook() -> None:
    """Inspect user playbook overrides against plugin defaults."""


@playbook.command(name="diff")
@click.option(
    "--skill",
    "skill_key",
    default=None,
    help="Limit the diff to one skill key (e.g., work-on). Default: all overrides.",
)
@click.option(
    "--plugin-root",
    type=click.Path(file_okay=False, exists=True),
    default=None,
    help="Override the auto-detected plugin root (debug aid).",
)
def playbook_diff(*, skill_key: str | None, plugin_root: str | None) -> None:
    """Diff user playbook overrides against plugin defaults.

    Surfaces upstream additions, removals, and field changes that the user
    may want to pull into their override. User customizations are preserved
    — the diff is read-only.
    """
    root = Path(plugin_root) if plugin_root else _resolve_plugin_root()
    if root is None:
        click.echo(
            "ERROR: Could not resolve plugin root. Set $CLAUDE_PLUGIN_ROOT or pass --plugin-root.",
            err=True,
        )
        sys.exit(1)

    overrides = find_user_playbooks()
    if skill_key:
        overrides = [o for o in overrides if o.skill_key == skill_key]

    if not overrides:
        if skill_key:
            click.echo(f"No user override found for skill {skill_key!r}.")
        else:
            click.echo("No user playbook overrides found.")
        return

    findings_count = 0
    for override in overrides:
        default_path = plugin_default_path(skill_key=override.skill_key, plugin_root=root)
        if not default_path.is_file():
            click.echo(
                f"\n## Skipping `{override.skill_key}` ({override.scope})\n"
                f"  No plugin default at {default_path}\n"
            )
            continue
        default_doc = _load_yaml(default_path)
        user_doc = _load_yaml(override.path)
        diff = compare_playbooks(
            default_doc=default_doc,
            user_doc=user_doc,
            skill_key=f"{override.skill_key} ({override.scope})",
            user_path=str(override.path),
            default_path=str(default_path),
        )
        click.echo(render_markdown_report(diff))
        if diff.has_findings:
            findings_count += 1

    if findings_count == 0:
        click.echo("All user overrides are up to date with plugin defaults.")
    else:
        click.echo(f"{findings_count} override(s) have upstream changes worth reviewing.")
