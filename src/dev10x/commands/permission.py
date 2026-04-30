from __future__ import annotations

import sys
from pathlib import Path

import click


@click.group()
def permission() -> None:
    """Maintain Dev10x plugin permission settings."""


@permission.command(name="update-paths")
@click.option("--dry-run", is_flag=True, help="Show changes without modifying files")
@click.option(
    "--version",
    "target_version",
    default=None,
    help="Target version (default: auto-detect)",
)
@click.option("--quiet", is_flag=True, help="Suppress per-file details")
@click.option(
    "--summary",
    is_flag=True,
    help="Print one line per changed file (count) instead of full per-file details",
)
@click.option("--restore", is_flag=True, help="Restore settings from most recent backups")
def update_paths(
    *,
    dry_run: bool,
    target_version: str | None,
    quiet: bool,
    summary: bool,
    restore: bool,
) -> None:
    """Update versioned plugin cache paths to the latest version."""
    from dev10x.skills.permission import update_paths as mod

    if restore:
        sys.exit(mod._restore(config_path=mod.find_config()))

    config_path = mod.find_config()
    if not quiet:
        click.echo(f"Config: {config_path}")
    config = mod.load_config(config_path)

    settings_files = mod.find_settings_files(
        roots=config.get("roots", []),
        include_user=config.get("include_user_settings", True),
    )
    if not settings_files:
        click.echo("No settings files found.")
        return

    cache_dir = Path(config["plugin_cache"]).expanduser()
    target = target_version or mod.detect_latest_version(cache_dir)
    if not target:
        click.echo(f"ERROR: No versions found in {cache_dir}", err=True)
        sys.exit(1)

    publisher = mod.extract_cache_publisher(config["plugin_cache"])
    if not quiet:
        click.echo(f"Target version: {target}")
        if publisher:
            click.echo(f"Target publisher: {publisher}")
    if dry_run and not quiet:
        click.echo("(dry run — no files will be modified)\n")

    total_changes = 0
    files_changed = 0

    for path in sorted(settings_files):
        count, messages = mod.update_file(
            path,
            target,
            target_publisher=publisher,
            dry_run=dry_run,
        )
        if count > 0:
            if summary:
                click.echo(f"{path}: {count} replacements")
            elif not quiet:
                click.echo(f"\n{path}")
                for msg in messages:
                    click.echo(msg)
            total_changes += count
            files_changed += 1

    if total_changes == 0:
        click.echo("All files already up to date.")
    else:
        verb = "Would update" if dry_run else "Updated"
        click.echo(f"{verb} {total_changes} paths in {files_changed} files.")


@permission.command(name="ensure-base")
@click.option("--dry-run", is_flag=True, help="Show changes without modifying files")
@click.option("--quiet", is_flag=True, help="Suppress per-file details")
def ensure_base(*, dry_run: bool, quiet: bool) -> None:
    """Add missing base permissions from projects.yaml."""
    from dev10x.skills.permission import update_paths as mod

    config_path = mod.find_config()
    if not quiet:
        click.echo(f"Config: {config_path}")
    config = mod.load_config(config_path)

    settings_files = mod.find_settings_files(
        roots=config.get("roots", []),
        include_user=config.get("include_user_settings", True),
    )
    if not settings_files:
        click.echo("No settings files found.")
        return

    sys.exit(
        mod._ensure_base(
            config=config,
            settings_files=settings_files,
            dry_run=dry_run,
            quiet=quiet,
        )
    )


@permission.command()
@click.option("--dry-run", is_flag=True, help="Show changes without modifying files")
@click.option("--quiet", is_flag=True, help="Suppress per-file details")
def generalize(*, dry_run: bool, quiet: bool) -> None:
    """Replace session-specific permission args with wildcard patterns."""
    from dev10x.skills.permission import update_paths as mod

    config_path = mod.find_config()
    config = mod.load_config(config_path)

    settings_files = mod.find_settings_files(
        roots=config.get("roots", []),
        include_user=config.get("include_user_settings", True),
    )
    if not settings_files:
        click.echo("No settings files found.")
        return

    sys.exit(
        mod._generalize(
            settings_files=settings_files,
            dry_run=dry_run,
            quiet=quiet,
        )
    )


@permission.command(name="ensure-workspace")
@click.option("--dry-run", is_flag=True, help="Show changes without modifying files")
@click.option("--quiet", is_flag=True, help="Suppress per-file details")
def ensure_workspace(*, dry_run: bool, quiet: bool) -> None:
    """Register workspace directories (e.g. /tmp/Dev10x) in settings files.

    Paths outside the project root require registration under
    permissions.additionalDirectories — allow-rules alone are not
    sufficient (GH-40).
    """
    from dev10x.skills.permission import update_paths as mod

    config_path = mod.find_config()
    config = mod.load_config(config_path)

    settings_files = mod.find_settings_files(
        roots=config.get("roots", []),
        include_user=config.get("include_user_settings", True),
    )
    if not settings_files:
        click.echo("No settings files found.")
        return

    sys.exit(
        mod._ensure_workspace(
            config=config,
            settings_files=settings_files,
            dry_run=dry_run,
            quiet=quiet,
        )
    )


@permission.command(name="ensure-scripts")
@click.option("--dry-run", is_flag=True, help="Show changes without modifying files")
@click.option("--quiet", is_flag=True, help="Suppress per-file details")
def ensure_scripts(*, dry_run: bool, quiet: bool) -> None:
    """Verify all plugin scripts have allow rules; add missing ones."""
    from dev10x.skills.permission import update_paths as mod

    config_path = mod.find_config()
    config = mod.load_config(config_path)

    settings_files = mod.find_settings_files(
        roots=config.get("roots", []),
        include_user=config.get("include_user_settings", True),
    )
    if not settings_files:
        click.echo("No settings files found.")
        return

    sys.exit(
        mod._ensure_scripts(
            config=config,
            settings_files=settings_files,
            dry_run=dry_run,
            quiet=quiet,
        )
    )


@permission.command(name="ensure-reads")
@click.option("--dry-run", is_flag=True, help="Show changes without modifying files")
@click.option("--quiet", is_flag=True, help="Suppress per-file details")
def ensure_reads(*, dry_run: bool, quiet: bool) -> None:
    """Emit per-skill folder Read rules with ~/ + /home/<user>/ twins."""
    from dev10x.skills.permission import update_paths as mod

    config_path = mod.find_config()
    config = mod.load_config(config_path)

    settings_files = mod.find_settings_files(
        roots=config.get("roots", []),
        include_user=config.get("include_user_settings", True),
    )
    if not settings_files:
        click.echo("No settings files found.")
        return

    sys.exit(
        mod._ensure_reads(
            config=config,
            settings_files=settings_files,
            dry_run=dry_run,
            quiet=quiet,
        )
    )


@permission.command()
def init() -> None:
    """Create userspace config from plugin default."""
    from dev10x.skills.permission.update_paths import _init_userspace_config

    sys.exit(_init_userspace_config())


@permission.command()
@click.option("--dry-run", is_flag=True, help="Show changes without modifying files")
@click.option("--verbose", "-v", is_flag=True, help="Print each affected rule")
@click.option(
    "--summary",
    is_flag=True,
    help="Print one line per changed file (count) instead of full per-file details",
)
@click.option("--restore", is_flag=True, help="Restore settings from most recent backups")
def clean(*, dry_run: bool, verbose: bool, summary: bool, restore: bool) -> None:
    """Clean redundant permissions from project settings files."""
    from dev10x.skills.permission import clean_project_files as mod

    if restore:
        sys.exit(mod._restore(config_path=mod.find_config()))

    config_path = mod.find_config()
    click.echo(f"Config: {config_path}")
    config = mod.load_config(config_path)

    global_data = mod.load_global_settings(mod.GLOBAL_SETTINGS)
    global_rules = mod.extract_allow_rules(global_data)
    click.echo(f"Global rules: {len(global_rules)}")

    cache_dir = Path(config.get("plugin_cache", "")).expanduser()
    cache_root = cache_dir.parent.parent if cache_dir.parts else None
    current_version = mod.detect_current_version(cache_dir)
    if current_version:
        click.echo(f"Current plugin version: {current_version}")

    base_permissions = set(config.get("base_permissions", []))
    settings_files = mod.find_settings_files(roots=config.get("roots", []))

    if not settings_files:
        click.echo("No project settings files found.")
        return

    click.echo(f"Scanning {len(settings_files)} files")
    if dry_run:
        click.echo("(dry run — no files will be modified)\n")
    else:
        click.echo()

    total_removed = 0
    total_kept = 0
    files_changed = 0
    total_secrets = 0

    for path in sorted(settings_files):
        result, messages = mod.clean_file(
            path,
            global_rules=global_rules,
            current_version=current_version,
            base_permissions=base_permissions,
            cache_root=cache_root,
            dry_run=dry_run,
            verbose=verbose,
        )
        if result is None:
            click.echo(f"\n{path}")
            for msg in messages:
                click.echo(msg)
            continue

        has_findings = (
            result.total_removed > 0
            or result.leaked_secrets
            or result.wildcard_bypasses
            or result.allow_deny_contradictions
            or result.ask_shadowed_by_allow
        )
        if has_findings:
            if summary and result.total_removed > 0 and not result.leaked_secrets:
                click.echo(f"{path}: {result.total_removed} removed")
            else:
                click.echo(f"\n{path}")
                for msg in messages:
                    click.echo(msg)
            total_removed += result.total_removed
            total_kept += len(result.kept)
            total_secrets += len(result.leaked_secrets)
            if result.total_removed > 0:
                files_changed += 1
        else:
            total_kept += len(result.kept)

    click.echo()
    if total_removed == 0:
        click.echo("All project files are clean.")
    else:
        verb = "Would remove" if dry_run else "Removed"
        click.echo(f"{verb} {total_removed} rules across {files_changed} files.")
        click.echo(f"Kept {total_kept} rules total.")

    if total_secrets > 0:
        click.echo(
            f"\n⚠ Found {total_secrets} rules containing leaked secrets."
            " Review and rotate affected credentials."
        )


@permission.command(name="enumerate-mcp")
@click.option("--dry-run", is_flag=True, help="Show changes without modifying files")
@click.option("--quiet", is_flag=True, help="Suppress per-file details")
def enumerate_mcp(*, dry_run: bool, quiet: bool) -> None:
    """Expand `mcp__plugin_Dev10x_*` wildcards into enumerated tool names."""
    from dev10x.skills.permission import enumerate_mcp as mod
    from dev10x.skills.permission import update_paths as paths_mod

    config_path = paths_mod.find_config()
    if not quiet:
        click.echo(f"Config: {config_path}")
    config = paths_mod.load_config(config_path)

    settings_files = paths_mod.find_settings_files(
        roots=config.get("roots", []),
        include_user=config.get("include_user_settings", True),
    )
    if not settings_files:
        click.echo("No settings files found.")
        return

    if dry_run and not quiet:
        click.echo("(dry run — no files will be modified)\n")

    mod.enumerate_settings(settings_files, dry_run=dry_run, quiet=quiet)


@permission.command(name="merge-worktree")
@click.option("--dry-run", is_flag=True, help="Show changes without modifying files")
@click.option("--restore", is_flag=True, help="Restore settings from most recent backups")
def merge_worktree(*, dry_run: bool, restore: bool) -> None:
    """Merge worktree permissions back into main project settings."""
    from dev10x.skills.permission import merge_worktree_permissions as mod

    config_path = mod.find_config()

    if restore:
        sys.exit(mod._restore(config_path=config_path))

    click.echo(f"Config: {config_path}")
    config = mod.load_config(config_path)

    roots = config.get("roots", [])
    if not roots:
        click.echo("No roots configured. Run `dev10x permission init` first.")
        return

    groups = mod.find_worktree_groups(roots)
    if not groups:
        click.echo("No worktree groups found.")
        return

    if dry_run:
        click.echo("(dry run — no files will be modified)\n")

    total_merged = 0
    projects_changed = 0

    for main_project, worktree_dirs in sorted(groups.items()):
        count, messages = mod.merge_permissions(
            main_project=main_project,
            worktree_dirs=worktree_dirs,
            dry_run=dry_run,
        )
        if count > 0:
            click.echo(f"\n{main_project}")
            for msg in messages:
                click.echo(msg)
            total_merged += count
            projects_changed += 1
        else:
            click.echo(f"\n{main_project} — up to date ({len(worktree_dirs)} worktrees)")

    if total_merged == 0:
        click.echo("\nAll projects up to date.")
    else:
        verb = "Would merge" if dry_run else "Merged"
        click.echo(f"\n{verb} {total_merged} permissions into {projects_changed} projects.")


@permission.group()
def investigate() -> None:
    """Permission Pattern Investigator (GH-47).

    Materialize fixtures, mutate settings with candidate rule shapes,
    and aggregate per-shape outcomes into a markdown report. The
    subagent dispatch loop that exercises each cell is orchestrated
    from the ``Dev10x:permission-investigator`` skill.
    """


_INVESTIGATOR_NS = "permission-investigator"


def _investigator_workdir() -> Path:
    return Path("/tmp/Dev10x") / _INVESTIGATOR_NS


def _matrix_state_path(*, workdir: Path | None = None) -> Path:
    """Return the matrix.json path for the given workdir.

    When ``workdir`` is None, falls back to the default workdir.
    Apply/record/report/restore commands resolve workdir from the
    persisted state so a `prepare --workdir X` run can be driven
    end-to-end without losing track of the matrix.
    """
    return (workdir or _investigator_workdir()) / "matrix.json"


def _resolve_state_path() -> Path:
    """Find matrix.json by checking the default workdir first.

    The default location is the bootstrap point — `prepare` always
    writes the initial copy there. If a non-default workdir was
    supplied to `prepare`, the state file at the default location
    contains a `redirect` pointer to the real matrix path.
    """
    default = _matrix_state_path()
    if not default.is_file():
        return default
    try:
        import json as _json

        data = _json.loads(default.read_text())
        redirect = data.get("redirect")
        if redirect:
            return Path(redirect)
    except (OSError, ValueError):
        pass
    return default


@investigate.command(name="prepare")
@click.option(
    "--workdir",
    type=click.Path(),
    default=None,
    help="Override workdir (default: /tmp/Dev10x/permission-investigator)",
)
def investigate_prepare(*, workdir: str | None) -> None:
    """Materialize fixtures and snapshot the user's settings files."""
    import json as _json
    from dataclasses import asdict

    from dev10x.skills.permission_investigator import fixtures
    from dev10x.skills.permission_investigator.matrix import generate_matrix

    work = Path(workdir) if workdir else _investigator_workdir()
    paths = fixtures.materialize_fixtures(workdir=work, user_home=Path.home())

    snapshot_dir = work / "snapshots"
    fixtures.snapshot_settings(
        settings_path=paths.global_settings,
        snapshot_dir=snapshot_dir,
    )
    fixtures.snapshot_settings(
        settings_path=paths.project_settings,
        snapshot_dir=snapshot_dir,
    )

    matrix = generate_matrix()
    state = {
        "fixture": {
            "fixture_root": str(paths.fixture_root),
            "fixture_relpath": str(paths.fixture_relpath),
            "plugin_skill_file": str(paths.plugin_skill_file),
            "project_settings": str(paths.project_settings),
            "global_settings": str(paths.global_settings),
            "workdir": str(paths.workdir),
            "publisher_root": str(paths.publisher_root),
        },
        "cells": [
            {
                "cell_id": cell.cell_id,
                "shape": asdict(cell.shape),
                "location": cell.location,
            }
            for cell in matrix.cells
        ],
        "results": {},
    }
    real_state_path = _matrix_state_path(workdir=work)
    real_state_path.parent.mkdir(parents=True, exist_ok=True)
    real_state_path.write_text(_json.dumps(state, indent=2))

    if work != _investigator_workdir():
        default_state_path = _matrix_state_path()
        default_state_path.parent.mkdir(parents=True, exist_ok=True)
        default_state_path.write_text(_json.dumps({"redirect": str(real_state_path)}, indent=2))

    click.echo(f"Workdir: {work}")
    click.echo(f"Fixture: {paths.plugin_skill_file}")
    click.echo(f"Cells: {len(matrix.cells)}")


@investigate.command(name="apply")
@click.argument("cell_id")
def investigate_apply(*, cell_id: str) -> None:
    """Apply the rule shape for ``cell_id`` to the appropriate target file(s)."""
    import json as _json

    from dev10x.skills.permission_investigator import fixtures
    from dev10x.skills.permission_investigator.matrix import RuleShape

    state_path = _resolve_state_path()
    if not state_path.is_file():
        click.echo("ERROR: state missing — run `prepare` first.", err=True)
        sys.exit(1)
    state = _json.loads(state_path.read_text())

    cell = next((c for c in state["cells"] if c["cell_id"] == cell_id), None)
    if cell is None:
        click.echo(f"ERROR: unknown cell_id {cell_id}", err=True)
        sys.exit(1)

    shape = RuleShape(**cell["shape"])
    rule = shape.render(
        fixture_relpath=state["fixture"]["fixture_relpath"],
        user_home=str(Path.home()),
    )

    targets: list[Path] = []
    if cell["location"] in ("project", "both"):
        targets.append(Path(state["fixture"]["project_settings"]))
    if cell["location"] in ("global", "both"):
        targets.append(Path(state["fixture"]["global_settings"]))

    for target in targets:
        fixtures.apply_rule(rule=rule, target=target)

    click.echo(f"Applied rule: {rule}")
    click.echo(f"Targets: {len(targets)}")


@investigate.command(name="record")
@click.argument("cell_id")
@click.option(
    "--auto-approved/--prompted",
    default=False,
    help="Whether the dispatcher tool call was auto-approved",
)
@click.option("--error", default=None, help="Error message, if any")
@click.option("--notes", default="", help="Free-form notes from the dispatcher")
def investigate_record(
    *,
    cell_id: str,
    auto_approved: bool,
    error: str | None,
    notes: str,
) -> None:
    """Record the outcome for one cell into the persisted matrix."""
    import json as _json

    state_path = _resolve_state_path()
    if not state_path.is_file():
        click.echo("ERROR: state missing — run `prepare` first.", err=True)
        sys.exit(1)
    state = _json.loads(state_path.read_text())

    state.setdefault("results", {})[cell_id] = {
        "cell_id": cell_id,
        "auto_approved": bool(auto_approved),
        "prompted": not bool(auto_approved),
        "error": error,
        "notes": notes,
    }
    state_path.write_text(_json.dumps(state, indent=2))
    click.echo(f"Recorded {cell_id}")


@investigate.command(name="restore")
def investigate_restore() -> None:
    """Restore settings files from the pre-run snapshots."""
    import json as _json

    from dev10x.skills.permission_investigator import fixtures

    state_path = _resolve_state_path()
    if not state_path.is_file():
        click.echo("Nothing to restore — state missing.")
        return
    state = _json.loads(state_path.read_text())
    snapshot_dir = Path(state["fixture"]["workdir"]) / "snapshots"

    for key in ("global_settings", "project_settings"):
        target = Path(state["fixture"][key])
        snap = snapshot_dir / f"{target.name}.snapshot"
        if snap.is_file():
            fixtures.restore_settings(snapshot_path=snap, target_path=target)
            click.echo(f"Restored {target}")

    publisher_root_str = state["fixture"].get("publisher_root")
    if publisher_root_str:
        publisher_root = Path(publisher_root_str)
        if publisher_root.is_dir():
            import shutil as _shutil

            _shutil.rmtree(publisher_root)
            click.echo(f"Removed fixture publisher tree {publisher_root}")


@investigate.command(name="report")
@click.option(
    "--output",
    type=click.Path(),
    default=None,
    help="Write the report to this path (default: stdout)",
)
def investigate_report(*, output: str | None) -> None:
    """Render the populated matrix as a markdown report."""
    import json as _json

    from dev10x.skills.permission_investigator.matrix import (
        Matrix,
        MatrixCell,
        MatrixResult,
        RuleShape,
    )
    from dev10x.skills.permission_investigator.report import render_markdown_report

    state_path = _resolve_state_path()
    if not state_path.is_file():
        click.echo("ERROR: state missing — run `prepare` first.", err=True)
        sys.exit(1)
    state = _json.loads(state_path.read_text())

    matrix = Matrix()
    for cell_data in state.get("cells", []):
        shape = RuleShape(**cell_data["shape"])
        matrix.cells.append(
            MatrixCell(
                shape=shape,
                location=cell_data["location"],
                cell_id=cell_data["cell_id"],
            )
        )
    for cell_id, result_data in state.get("results", {}).items():
        matrix.add_result(MatrixResult(**result_data))

    rendered = render_markdown_report(matrix)
    if output:
        Path(output).write_text(rendered)
        click.echo(f"Wrote report to {output}")
    else:
        click.echo(rendered)


@investigate.command(name="delta")
def investigate_delta() -> None:
    """Compare matrix outcomes against current plugin-maintenance rules."""
    import json as _json

    from dev10x.skills.permission import update_paths as paths_mod
    from dev10x.skills.permission_investigator.matrix import (
        Matrix,
        MatrixCell,
        MatrixResult,
        RuleShape,
    )
    from dev10x.skills.permission_investigator.report import compute_delta

    state_path = _resolve_state_path()
    if not state_path.is_file():
        click.echo("ERROR: state missing — run `prepare` first.", err=True)
        sys.exit(1)
    state = _json.loads(state_path.read_text())

    matrix = Matrix()
    for cell_data in state.get("cells", []):
        matrix.cells.append(
            MatrixCell(
                shape=RuleShape(**cell_data["shape"]),
                location=cell_data["location"],
                cell_id=cell_data["cell_id"],
            )
        )
    for cell_id, result_data in state.get("results", {}).items():
        matrix.add_result(MatrixResult(**result_data))

    config_path = paths_mod.find_config()
    config = paths_mod.load_config(config_path)
    base_permissions = config.get("base_permissions", [])

    delta = compute_delta(matrix=matrix, base_permissions=base_permissions)

    click.echo("Ineffective rules currently shipped:")
    for rule in delta.ineffective_rules or ["  (none)"]:
        click.echo(f"  - {rule}")
    click.echo()
    click.echo("Suggested replacements:")
    for line in delta.suggested_rules or ["  (none — matrix incomplete or all prompt)"]:
        click.echo(f"  * {line}")
