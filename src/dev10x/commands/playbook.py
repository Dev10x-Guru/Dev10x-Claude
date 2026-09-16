"""CLI for playbook diagnostics (GH-192).

``dev10x playbook diff`` compares every user playbook override visible
from the current working directory against the matching plugin default
and prints a markdown report of upstream changes. User customizations
are preserved — the diff reports them but never writes.
"""

from __future__ import annotations

import sys
from pathlib import Path

import click
import yaml

from dev10x.domain.plugin_root import resolve_plugin_root
from dev10x.skills.playbook import (
    compare_playbooks,
    find_user_playbooks,
    plugin_default_path,
    render_markdown_report,
)


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


def _report_projects(
    *, document: dict, source: str, target: str | None, reason: str | None
) -> None:
    """Say whether a playbook override's `projects:` list selects this repo.

    `playbook diff` located override *files* by path and never read the
    `projects:` list inside them, so an override addressed at a repo it
    no longer matches diffed clean — reported as up to date while
    applying to nothing (GH-1375). A list that was never evaluated,
    because the repo has no `origin` remote, is reported separately: a
    check that cannot tell "found nothing" from "did not look" is the
    failure ADR-0026 exists to prevent.
    """
    from dev10x.domain.project_match import (
        MatchScheme,
        ProjectsStatus,
        describe,
        evaluate_projects,
    )

    report = evaluate_projects(
        document,
        scheme=MatchScheme.REPO,
        source=source,
        target=target,
        unresolved_reason=reason,
    )
    if report.status is ProjectsStatus.ABSENT:
        return
    if report.status is ProjectsStatus.MATCHED and not report.needs_attention:
        click.echo(f"  `projects:` entry {report.matched_index} selects `{target}`.\n")
        return
    click.echo("  `projects:` list needs attention:")
    for line in describe(report):
        click.echo(line)
    click.echo("")


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
    root = resolve_plugin_root(override=Path(plugin_root) if plugin_root else None)
    if root is None:
        click.echo(
            "ERROR: Could not resolve plugin root. Set $CLAUDE_PLUGIN_ROOT, install "
            "the plugin, or pass --plugin-root.",
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

    from dev10x.domain.common.result import SuccessResult
    from dev10x.session.repo_address import resolve_name_with_owner

    address = resolve_name_with_owner()
    repo_target = address.value if isinstance(address, SuccessResult) else None
    repo_reason = None if isinstance(address, SuccessResult) else address.error

    findings_count = 0
    skipped: list[str] = []
    for override in overrides:
        default_path = plugin_default_path(skill_key=override.skill_key, plugin_root=root)
        if not default_path.is_file():
            skipped.append(override.skill_key)
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
        _report_projects(
            document=user_doc,
            source=str(override.path),
            target=repo_target,
            reason=repo_reason,
        )
        if diff.has_findings:
            findings_count += 1

    checked_count = len(overrides) - len(skipped)
    skipped_note = (
        f" ({len(skipped)} skipped — no plugin default found: {', '.join(skipped)})"
        if skipped
        else ""
    )
    if checked_count == 0:
        # Every override was skipped — a bare "up to date" here would report
        # success for overrides that were never actually checked (GH-1329).
        click.echo(f"{len(skipped)} override(s) skipped — no plugin default found; unchecked.")
    elif findings_count == 0:
        click.echo(
            f"All checked user overrides are up to date with plugin defaults.{skipped_note}"
        )
    else:
        click.echo(
            f"{findings_count} override(s) have upstream changes worth reviewing.{skipped_note}"
        )
