from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

import click

from dev10x.domain.common.result import ErrorResult
from dev10x.permission.service import PermissionContext, load_permission_context


@click.group()
def permission() -> None:
    """Maintain Dev10x plugin permission settings."""


def _emit_result(result: dict) -> int:
    """Print messages/errors from a public-API result dict and return its exit_code."""
    for msg in result.get("messages", []):
        click.echo(msg)
    for err in result.get("errors", []):
        click.echo(err, err=True)
    return int(result.get("exit_code", 0))


def _require_config(mod: ModuleType) -> Path:
    """Unwrap ``mod.find_config()`` or exit — the CLI layer owns exit codes."""
    resolved = mod.find_config()
    if isinstance(resolved, ErrorResult):
        click.echo(f"ERROR: {resolved.error}", err=True)
        sys.exit(1)
    return resolved.value


def _require_context(*, include_user: bool | None = None) -> PermissionContext:
    """Resolve the permission context via the service or exit (audit N18).

    The CLI counterpart to the MCP adapter's ``load_permission_context``
    call: both reach the same service instead of inlining the
    ``find_config`` → ``load_config`` → ``find_settings_files`` triple.
    The CLI layer owns exit codes, so a config-resolution failure exits 1.
    """
    result = load_permission_context(include_user=include_user)
    if isinstance(result, ErrorResult):
        click.echo(f"ERROR: {result.error}", err=True)
        sys.exit(1)
    return result.value


def _require_settings(
    *,
    include_user: bool | None = None,
    show_config: bool = False,
    quiet: bool = False,
) -> PermissionContext | None:
    """Resolve a context that has settings files, or signal an early return.

    Folds the per-command preamble every ``ensure_*`` / ``doctor_*`` handler
    repeated (audit GH-541 Template Method): resolve the context, optionally
    echo the config path, and guard on an empty ``settings_files`` set.
    Returns ``None`` after emitting "No settings files found." so callers
    early-return with a single ``if ctx is None: return``.
    """
    ctx = _require_context(include_user=include_user)
    if show_config and not quiet:
        click.echo(f"Config: {ctx.config_path}")
    if not ctx.settings_files:
        click.echo("No settings files found.")
        return None
    return ctx


def _run_fix(
    fn: object,
    *,
    needs_config: bool,
    dry_run: bool,
    quiet: bool,
    show_config: bool = False,
) -> None:
    """Run one ``ensure_*``/``generalize`` fix behind the shared preamble.

    Collapses the ``_require_settings`` → early-return → ``sys.exit(
    _emit_result(mod.FN(...)))`` skeleton that every single-call ``ensure_*``
    handler repeated (audit GH-842). ``needs_config`` forwards ``config`` only
    for the handlers that accept it (``generalize`` does not); ``show_config``
    echoes the config path (``ensure-base`` only). Exits the process with the
    fix's exit code, or returns early when no settings files are found.

    ``ensure-scripts`` folds two domain calls with ``max(...)`` and stays an
    explicit handler — the one documented exception to this runner.
    """
    ctx = _require_settings(show_config=show_config, quiet=quiet)
    if ctx is None:
        return
    kwargs: dict[str, object] = {
        "settings_files": ctx.settings_files,
        "dry_run": dry_run,
        "quiet": quiet,
    }
    if needs_config:
        kwargs["config"] = ctx.config
    sys.exit(_emit_result(fn(**kwargs)))  # type: ignore[operator]


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
        sys.exit(mod._restore(config_path=_require_config(mod)))

    ctx = _require_settings(show_config=True, quiet=quiet)
    if ctx is None:
        return
    config = ctx.config
    settings_files = ctx.settings_files

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
    total_collapsed = 0
    files_collapsed = 0

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

        # GH-269: collapse retired upgrade-cleanup script rules to the
        # uvx CLI form. Runs on every update-paths invocation so user
        # settings stop drifting with each plugin upgrade.
        collapsed_count, collapsed_messages = mod.collapse_legacy_upgrade_cleanup_rules(
            path,
            dry_run=dry_run,
        )
        if collapsed_count > 0:
            if summary:
                click.echo(f"{path}: collapsed {collapsed_count} legacy script rule(s)")
            elif not quiet:
                if count == 0:
                    click.echo(f"\n{path}")
                for msg in collapsed_messages:
                    click.echo(msg)
            total_collapsed += collapsed_count
            files_collapsed += 1

    if total_changes == 0 and total_collapsed == 0:
        click.echo("All files already up to date.")
    else:
        verb = "Would update" if dry_run else "Updated"
        if total_changes:
            click.echo(f"{verb} {total_changes} paths in {files_changed} files.")
        if total_collapsed:
            verb_c = "Would collapse" if dry_run else "Collapsed"
            click.echo(
                f"{verb_c} {total_collapsed} legacy script rule(s) "
                f"in {files_collapsed} files (GH-269)."
            )


@permission.command(name="ensure-base")
@click.option("--dry-run", is_flag=True, help="Show changes without modifying files")
@click.option("--quiet", is_flag=True, help="Suppress per-file details")
def ensure_base(*, dry_run: bool, quiet: bool) -> None:
    """Add missing base permissions from projects.yaml."""
    from dev10x.skills.permission import update_paths as mod

    _run_fix(mod.ensure_base, needs_config=True, dry_run=dry_run, quiet=quiet, show_config=True)


@permission.command()
@click.option("--dry-run", is_flag=True, help="Show changes without modifying files")
@click.option("--quiet", is_flag=True, help="Suppress per-file details")
def generalize(*, dry_run: bool, quiet: bool) -> None:
    """Replace session-specific permission args with wildcard patterns."""
    from dev10x.skills.permission import update_paths as mod

    _run_fix(mod.generalize, needs_config=False, dry_run=dry_run, quiet=quiet)


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

    _run_fix(mod.ensure_workspace, needs_config=True, dry_run=dry_run, quiet=quiet)


@permission.command(name="ensure-scripts")
@click.option("--dry-run", is_flag=True, help="Show changes without modifying files")
@click.option("--quiet", is_flag=True, help="Suppress per-file details")
def ensure_scripts(*, dry_run: bool, quiet: bool) -> None:
    """Verify plugin and user-skill scripts have allow rules; add missing ones."""
    from dev10x.skills.permission import update_paths as mod

    ctx = _require_settings()
    if ctx is None:
        return

    plugin_exit = _emit_result(
        mod.ensure_scripts(
            config=ctx.config,
            settings_files=ctx.settings_files,
            dry_run=dry_run,
            quiet=quiet,
        )
    )
    # GH-606 AC2: also enumerate ~/.claude/skills/<dir>/scripts/ so personal
    # and plugin-installed user skills get canonical allow rules.
    user_exit = _emit_result(
        mod.ensure_user_skill_scripts(
            settings_files=ctx.settings_files,
            dry_run=dry_run,
            quiet=quiet,
        )
    )
    sys.exit(max(plugin_exit, user_exit))


@permission.command(name="ensure-reads")
@click.option("--dry-run", is_flag=True, help="Show changes without modifying files")
@click.option("--quiet", is_flag=True, help="Suppress per-file details")
def ensure_reads(*, dry_run: bool, quiet: bool) -> None:
    """Emit per-skill folder Read rules with ~/ + /home/<user>/ twins."""
    from dev10x.skills.permission import update_paths as mod

    _run_fix(mod.ensure_reads, needs_config=True, dry_run=dry_run, quiet=quiet)


@permission.command()
def init() -> None:
    """Create userspace config from plugin default."""
    from dev10x.skills.permission.update_paths import init_userspace_config

    sys.exit(_emit_result(init_userspace_config()))


@permission.command()
@click.option("--dry-run", is_flag=True, help="Show changes without modifying files")
@click.option("--verbose", "-v", is_flag=True, help="Print each affected rule")
@click.option(
    "--summary",
    is_flag=True,
    help="Print one line per changed file (count) instead of full per-file details",
)
@click.option("--restore", is_flag=True, help="Restore settings from most recent backups")
@click.option(
    "--skip-global-dedup",
    is_flag=True,
    default=False,
    help=(
        "Do not remove project rules that are exact duplicates of global rules. "
        "Retained for backward compatibility — global-dedup is now OFF by "
        "default, so this flag is only meaningful alongside --aggressive."
    ),
)
@click.option(
    "--aggressive",
    is_flag=True,
    default=False,
    help=(
        "Also remove project rules that are exact duplicates of global rules. "
        "OFF by default (finding #47): global→project rule inheritance is NOT "
        "guaranteed when a project has its own settings.local.json, so stripping "
        "the local copy can reintroduce permission prompts. Only enable after "
        "`dev10x permission investigate` confirms inheritance holds for this "
        "environment. Recover a bad run with `dev10x permission clean --restore`."
    ),
)
def clean(
    *,
    dry_run: bool,
    verbose: bool,
    summary: bool,
    restore: bool,
    skip_global_dedup: bool,
    aggressive: bool,
) -> None:
    """Clean redundant permissions from project settings files."""
    from dev10x.skills.permission import clean_project_files as mod

    if restore:
        sys.exit(mod._restore(config_path=_require_config(mod)))

    # Global-dedup is opt-in (finding #47). It runs only under --aggressive,
    # and --skip-global-dedup always wins so the safe behavior cannot be
    # accidentally re-enabled.
    skip_global_dedup = skip_global_dedup or not aggressive

    config_path = _require_config(mod)
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
    total_global_dedup = 0

    for path in sorted(settings_files):
        result, messages = mod.clean_file(
            path,
            global_rules=global_rules,
            current_version=current_version,
            base_permissions=base_permissions,
            cache_root=cache_root,
            dry_run=dry_run,
            verbose=verbose,
            skip_global_dedup=skip_global_dedup,
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
            total_global_dedup += len(result.exact_duplicates)
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

    if total_global_dedup > 0 and not skip_global_dedup:
        click.echo(
            f"\n⚠  WARNING: {total_global_dedup} rules removed as exact duplicates of global"
            " rules (--aggressive). Global→project rule inheritance is NOT guaranteed when a"
            " project has its own settings.local.json (finding #47). If new permission prompts"
            " appear, recover with `dev10x permission clean --restore`."
        )

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

    ctx = _require_settings(show_config=True, quiet=quiet)
    if ctx is None:
        return

    if dry_run and not quiet:
        click.echo("(dry run — no files will be modified)\n")

    mod.enumerate_settings(ctx.settings_files, dry_run=dry_run, quiet=quiet)


@permission.command(name="promote-plan")
@click.option("--quiet", is_flag=True, help="Suppress config line")
@click.option(
    "--apply",
    "apply_changes",
    is_flag=True,
    help="Write the plan into global settings (Increment 2, GH-480). Default is dry-run report.",
)
@click.option(
    "--include-sensitive",
    is_flag=True,
    help="With --apply: also promote sensitivity-flagged reads (private/DM/secret). Opt-in.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="With --apply: show what would be written without modifying files.",
)
@click.option(
    "--proactive",
    is_flag=True,
    help="Seed the curated default-safe surface (GH-601) without a prior approval (GH-603).",
)
def promote_plan(
    *,
    quiet: bool,
    apply_changes: bool,
    include_sensitive: bool,
    dry_run: bool,
    proactive: bool,
) -> None:
    """Promote read-only MCP tools + research domains to global settings (GH-470/GH-480/GH-603).

    Without ``--apply`` this reports a DRY-RUN plan and makes NO changes:
    read-only tools and project-local research WebFetch domains are classified
    and deduped against global; writes and sensitivity-flagged reads are
    excluded from the default promotable set.

    With ``--apply`` (Increment 2, GH-480) the read-only set + research domains
    are written into global ``~/.claude/settings.json`` — backup-guarded and
    idempotent. Sensitivity-flagged reads are promoted only with the explicit
    ``--include-sensitive`` opt-in; writes are never promoted. Combine
    ``--apply --dry-run`` to preview exactly which rules the write would add.

    ``--proactive`` (GH-603) ignores project-local approvals and instead seeds
    the curated default-safe catalog surface (tier-2 ``benign`` groups, GH-601)
    directly — so a fresh project never pays the first-prompt toll. PII/secret
    groups (tier 3) are never proactively seeded.
    """
    from dev10x.skills.permission import promote as mod

    global_settings = Path.home() / ".claude" / "settings.json"
    if proactive:
        catalog = Path(mod.__file__).parent / "baseline-permissions.yaml"
        plan = mod.build_proactive_seed_plan(
            catalog_path=catalog,
            global_settings_path=global_settings,
        )
    else:
        ctx = _require_context(include_user=False)
        if not quiet:
            click.echo(f"Config: {ctx.config_path}")
        plan = mod.build_promotion_plan(
            project_settings_paths=ctx.settings_files,
            global_settings_path=global_settings,
        )
    if not apply_changes:
        click.echo(mod.render_promotion_plan(plan))
        return

    result = mod.apply_promotion_plan(
        plan=plan,
        global_settings_path=global_settings,
        include_sensitive=include_sensitive,
        dry_run=dry_run,
    )
    click.echo(mod.render_promotion_result(result, dry_run=dry_run))


@permission.command(name="provenance")
@click.option(
    "--path",
    "settings_path",
    default=None,
    help="Settings file to inspect (default: ./.claude/settings.local.json).",
)
def provenance(*, settings_path: str | None) -> None:
    """Report where each permission rule came from (GH-602).

    Classifies every allow/deny rule in a settings file as ``default`` (Dev10x
    base catalog), ``user`` (user-global settings), or ``project`` (local only).
    """
    from dev10x.skills.permission import provenance as mod
    from dev10x.skills.permission import update_paths as paths_mod

    config = paths_mod.load_config(_require_config(paths_mod))
    target = (
        Path(settings_path) if settings_path else Path.cwd() / ".claude" / "settings.local.json"
    )
    result = mod.build_provenance(settings_path=target, config=config)
    if isinstance(result, ErrorResult):
        click.echo(f"ERROR: {result.error}", err=True)
        sys.exit(1)
    counts = result.value["counts"]
    click.echo(f"{result.value['path']}")
    click.echo(
        f"  default: {counts['default']}  user: {counts['user']}  project: {counts['project']}"
    )
    for entry in result.value["rules"]:
        click.echo(f"  [{entry['provenance']}] {entry['kind']}: {entry['rule']}")


@permission.command(name="seed-worktree")
@click.argument("worktree_path")
@click.option("--dry-run", is_flag=True, help="Show what would be seeded without writing.")
def seed_worktree(*, worktree_path: str, dry_run: bool) -> None:
    """Pre-seed a worktree's settings with curated safe defaults (GH-602).

    Used at worktree creation so a curated read-only surface is honored in the
    new worktree without a first prompt.
    """
    from dev10x.skills.permission import update_paths as paths_mod

    config = paths_mod.load_config(_require_config(paths_mod))
    result = paths_mod.seed_worktree(
        worktree_root=Path(worktree_path), config=config, dry_run=dry_run
    )
    if isinstance(result, ErrorResult):
        click.echo(f"ERROR: {result.error}", err=True)
        sys.exit(1)
    verb = "Would seed" if dry_run else "Seeded"
    click.echo(f"{verb} {result.value['added']} rule(s) → {result.value['path']}")


@permission.command(name="merge-worktree")
@click.option("--dry-run", is_flag=True, help="Show changes without modifying files")
@click.option("--restore", is_flag=True, help="Restore settings from most recent backups")
def merge_worktree(*, dry_run: bool, restore: bool) -> None:
    """Merge worktree permissions back into main project settings."""
    from dev10x.skills.permission import merge_worktree_permissions as mod

    config_path = _require_config(mod)

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

    # GH-813 Finding 2: surface coverage explicitly. Discovery now unions the
    # .worktrees/ glob with `git worktree list`, so worktrees registered
    # outside the conventional layout are included instead of silently
    # skipped — echo the totals so a missing worktree is visible, not implied.
    discovered = sum(len(dirs) for dirs in groups.values())
    click.echo(f"Discovered {discovered} worktree(s) across {len(groups)} project(s).")

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


@permission.command(name="audit")
def permission_audit() -> None:
    """Classify allow rules onto typed auditor assessments (PAP-6, GH-867)."""
    from dev10x.skills.permission import policy_audit
    from dev10x.skills.permission.doctor import CATALOG_PATH, load_catalog

    ctx = _require_settings()
    if ctx is None:
        return
    catalog_policies = {
        policy.signature: policy for policy in load_catalog(CATALOG_PATH).policies()
    }
    rules = policy_audit.rules_from_settings(ctx.settings_files)
    for line in policy_audit.audit_report(rules=rules, catalog_policies=catalog_policies):
        click.echo(line)


@permission.command(name="resolve")
@click.argument("signature")
@click.option("--context", default="", help="Active skill context for PAP-5 scoped resolution")
@click.option(
    "--project",
    "project_path",
    type=click.Path(),
    default=None,
    help="Project catalog layer (grouped or flat YAML); optional",
)
def permission_resolve(*, signature: str, context: str, project_path: str | None) -> None:
    """Resolve the layered policy effect for a tool-call SIGNATURE (PAP-6, GH-868)."""
    from dev10x.domain.dev10x_paths import Dev10xConfigDir
    from dev10x.skills.permission.doctor import CATALOG_PATH
    from dev10x.skills.permission.resolve import resolve_report

    for line in resolve_report(
        signature=signature,
        context=context,
        plugin_path=CATALOG_PATH,
        user_path=Dev10xConfigDir.projects_yaml(),
        project_path=Path(project_path) if project_path else None,
    ):
        click.echo(line)


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
    from dev10x.skills.permission_investigator import runner

    work = Path(workdir) if workdir else _investigator_workdir()
    sys.exit(
        _emit_result(
            runner.prepare(
                workdir=work,
                user_home=Path.home(),
                default_workdir=_investigator_workdir(),
            )
        )
    )


@investigate.command(name="apply")
@click.argument("cell_id")
def investigate_apply(*, cell_id: str) -> None:
    """Apply the rule shape for ``cell_id`` to the appropriate target file(s)."""
    from dev10x.skills.permission_investigator import runner

    sys.exit(
        _emit_result(
            runner.apply_cell(
                state_path=_resolve_state_path(),
                cell_id=cell_id,
                user_home=Path.home(),
            )
        )
    )


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
    from dev10x.skills.permission_investigator import runner

    sys.exit(
        _emit_result(
            runner.record_outcome(
                state_path=_resolve_state_path(),
                cell_id=cell_id,
                auto_approved=auto_approved,
                error=error,
                notes=notes,
            )
        )
    )


@investigate.command(name="restore")
def investigate_restore() -> None:
    """Restore settings files from the pre-run snapshots."""
    from dev10x.skills.permission_investigator import runner

    sys.exit(_emit_result(runner.restore(state_path=_resolve_state_path())))


@investigate.command(name="report")
@click.option(
    "--output",
    type=click.Path(),
    default=None,
    help="Write the report to this path (default: stdout)",
)
def investigate_report(*, output: str | None) -> None:
    """Render the populated matrix as a markdown report."""
    from dev10x.skills.permission_investigator import runner

    sys.exit(_emit_result(runner.build_report(state_path=_resolve_state_path(), output=output)))


@investigate.command(name="delta")
def investigate_delta() -> None:
    """Compare matrix outcomes against current plugin-maintenance rules."""
    from dev10x.skills.permission import update_paths as paths_mod
    from dev10x.skills.permission_investigator import PermissionDeltaQuery

    config_path = _require_config(paths_mod)
    config = paths_mod.load_config(config_path)
    query = PermissionDeltaQuery(
        state_path=_resolve_state_path(),
        base_permissions=config.get("base_permissions", []),
    )
    if not query.state_exists():
        click.echo("ERROR: state missing — run `prepare` first.", err=True)
        sys.exit(1)
    delta = query.execute()

    click.echo("Ineffective rules currently shipped:")
    for rule in delta.ineffective_rules or ["  (none)"]:
        click.echo(f"  - {rule}")
    click.echo()
    click.echo("Suggested replacements:")
    for line in delta.suggested_rules or ["  (none — matrix incomplete or all prompt)"]:
        click.echo(f"  * {line}")


@permission.group()
def doctor() -> None:
    """Diagnose and fix common allow-rule friction patterns (GH-99)."""


@doctor.command(name="canonicalize")
@click.option("--dry-run", is_flag=True, help="Show changes without modifying files")
@click.option("--quiet", is_flag=True, help="Suppress per-file details")
def doctor_canonicalize(*, dry_run: bool, quiet: bool) -> None:
    """Collapse duplicate-slash path typos (``//`` → ``/``) in allow rules.

    ``${CLAUDE_PLUGIN_ROOT}`` expands with a trailing slash, so an expanded
    rule can bake a literal ``//`` into settings that the verbatim matcher
    never matches (GH-704). This command collapses those.

    It does NOT rewrite version-pinned plugin paths to ``**`` wildcards
    (GH-715) — ``**`` matching is unreliable; use
    ``dev10x permission update-paths`` to keep pinned paths current on
    upgrade.
    """
    from dev10x.skills.permission import doctor as mod

    ctx = _require_settings()
    if ctx is None:
        return

    if dry_run and not quiet:
        click.echo("(dry run — no files will be modified)\n")

    total_rewrites = 0
    files_changed = 0
    for path in sorted(ctx.settings_files):
        result = mod.canonicalize_settings_file(path, dry_run=dry_run)
        if result.changed:
            files_changed += 1
            total_rewrites += result.changed
            if not quiet:
                click.echo(f"\n{path} — {result.changed} rewrites")
                for original, rewritten in result.rewrites:
                    click.echo(f"  - {original}")
                    click.echo(f"  + {rewritten}")
    verb = "Would collapse" if dry_run else "Collapsed"
    click.echo(f"\n{verb} {total_rewrites} duplicate-slash typos across {files_changed} files.")


@doctor.command(name="cross-contamination")
@click.option(
    "--cwd",
    type=click.Path(exists=True),
    default=None,
    help="Project root (default: $PWD)",
)
@click.option("--quiet", is_flag=True, help="Suppress per-rule details")
def doctor_cross_contamination(*, cwd: str | None, quiet: bool) -> None:
    """Flag allow rules whose paths point outside the current project.

    Detects two contamination patterns:
      1. Foreign-project paths (copy-pasted settings).
      2. Source-repo paths when CWD is a worktree (use relative paths
         inside the worktree instead).
    """
    from dev10x.skills.permission import doctor as mod

    root = Path(cwd) if cwd else Path.cwd()
    sys.exit(_emit_result(mod.cross_contamination_for_root(root=root, quiet=quiet)))


@doctor.command(name="apply-deprecations")
@click.option("--dry-run", is_flag=True, help="Show changes without modifying files")
def doctor_apply_deprecations(*, dry_run: bool) -> None:
    """Apply catalog deprecations (canonicalize / remove) to settings files."""
    from dev10x.skills.permission import doctor as mod

    catalog = mod.load_catalog()
    ctx = _require_settings()
    if ctx is None:
        return

    if dry_run:
        click.echo("(dry run — no files will be modified)\n")

    sys.exit(
        _emit_result(
            mod.apply_deprecations_to_files(ctx.settings_files, catalog=catalog, dry_run=dry_run)
        )
    )


@doctor.command(name="enable-group")
@click.argument("group_name")
@click.option("--dry-run", is_flag=True, help="Show changes without modifying files")
def doctor_enable_group(*, group_name: str, dry_run: bool) -> None:
    """Add a Tier 3 group's rules from the baseline-permissions catalog."""
    from dev10x.skills.permission import doctor as mod

    catalog = mod.load_catalog()
    rules = catalog.group_rules(group_name)
    if not rules:
        click.echo(f"ERROR: unknown group {group_name!r}")
        sys.exit(1)
    ctx = _require_settings()
    if ctx is None:
        return
    if dry_run:
        click.echo("(dry run — no files will be modified)\n")

    sys.exit(
        _emit_result(
            mod.enable_group_in_files(
                ctx.settings_files,
                rules=rules,
                group_name=group_name,
                dry_run=dry_run,
            )
        )
    )


@doctor.command(name="anchor-worktree-roots")
@click.option("--dry-run", is_flag=True, help="Show changes without modifying files")
@click.option("--quiet", is_flag=True, help="Suppress per-file details")
def doctor_anchor_worktree_roots(*, dry_run: bool, quiet: bool) -> None:
    """Anchor .worktrees parents in additionalDirectories and flag relative skill-script rules.

    Worktrees accumulate per-leaf ``additionalDirectories`` entries instead of
    anchoring the project-level ``.worktrees`` parent. This command:

    \b
    1. Discovers every ``<project>/.worktrees`` parent beneath configured roots.
    2. Ensures each parent is present in ``additionalDirectories`` across all
       settings files — anchoring at the parent covers all sibling and future
       worktrees without re-prompting per leaf (GH-376).
    3. Flags bare-relative ``.claude/skills/.../scripts/`` allow rules that
       silently target different skill dirs per worktree CWD.
    """
    from dev10x.skills.permission import doctor as mod

    ctx = _require_context()
    roots = ctx.config.get("roots", [])
    if not roots:
        click.echo("No roots configured. Run `dev10x permission init` first.")
        return

    if not ctx.settings_files:
        click.echo("No settings files found.")
        return

    if dry_run and not quiet:
        click.echo("(dry run — no files will be modified)\n")

    worktrees_parents = mod.discover_worktrees_parents(roots)
    if not quiet:
        if worktrees_parents:
            click.echo(f"Discovered {len(worktrees_parents)} .worktrees parent(s):")
            for parent in worktrees_parents:
                click.echo(f"  {parent}")
        else:
            click.echo("No .worktrees parents found beneath configured roots.")

    anchor_result = mod.anchor_worktree_roots(
        ctx.settings_files,
        roots=roots,
        dry_run=dry_run,
    )

    workspace_count = anchor_result.workspace_anchored
    skill_script_count = sum(1 for f in anchor_result.findings if f.scope == "skill-script")

    for finding in anchor_result.findings:
        if finding.scope == "workspace" and not quiet:
            click.echo(f"\n{finding.settings_path}")
            click.echo(f"  {finding.suggestion}")
        elif finding.scope == "skill-script":
            click.echo(f"\n{finding.settings_path}")
            click.echo(f"  ! RELATIVE_SKILL_SCRIPT: {finding.rule}")
            if not quiet:
                click.echo(f"    {finding.suggestion}")

    if workspace_count == 0 and skill_script_count == 0:
        click.echo("\nAll settings files already have worktrees parents anchored.")
    else:
        if workspace_count > 0:
            verb = "Would anchor" if dry_run else "Anchored"
            click.echo(
                f"\n{verb} {workspace_count} worktrees parent path(s) in additionalDirectories."
            )
        if skill_script_count > 0:
            click.echo(
                f"\nFound {skill_script_count} relative skill-script rule(s) "
                f"— rewrite to absolute plugin-cache paths or Skill() invocations."
            )


@permission.command(name="record-upgrade")
@click.option(
    "--version",
    "explicit_version",
    default=None,
    help="Version to record (default: read from plugin.json)",
)
def record_upgrade(*, explicit_version: str | None) -> None:
    """Record the currently-installed plugin version as applied.

    Invoked by Dev10x:upgrade-cleanup after a successful run so the
    SessionStart install-check stays silent until the next upgrade.
    """
    from dev10x.domain.install_version import read_plugin_version, write_applied_version

    version = explicit_version or read_plugin_version()
    if version is None:
        click.echo(
            "ERROR: could not resolve plugin version; pass --version explicitly.",
            err=True,
        )
        sys.exit(1)
    written = write_applied_version(plugin_version=version)
    click.echo(f"Recorded plugin version {version} at {written}")
