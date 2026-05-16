from __future__ import annotations

import json
import os
import sys
import traceback
from datetime import UTC, datetime, timedelta
from pathlib import Path

import click

_DEBUG = os.environ.get("HOOK_DEBUG", "") != ""


@click.group()
def hook() -> None:
    """Hook entry points (validate-bash, validate-edit, plan-sync, session)."""


@hook.command(name="validate-bash")
def validate_bash() -> None:
    """Validate Bash commands via the unified validator registry.

    Reads JSON from stdin, dispatches to registered validators.
    Exit codes: 0=allow, 2=block.
    """
    from dev10x.hooks.audit_emit import audit_hook

    _run = audit_hook(name="validate-bash", event="PreToolUse")(_validate_bash_body)
    _run()


def _validate_bash_body() -> None:
    from dev10x.domain import HookInput
    from dev10x.validators import get_chain

    inp = HookInput.from_stdin()
    if inp.tool_name != "Bash":
        sys.exit(0)
    if not inp.command:
        sys.exit(0)

    for result in get_chain().run(inp=inp):
        result.emit()

    sys.exit(0)


@hook.group(name="plan")
def plan() -> None:
    """Plan synchronization commands."""


@plan.command(name="sync")
def plan_sync() -> None:
    """Sync task state from stdin (PostToolUse hook mode)."""
    from dev10x.hooks.task_plan_sync import cmd_hook

    cmd_hook()


@plan.command(name="summary")
def plan_summary() -> None:
    """Read plan YAML, output JSON summary."""
    from dev10x.hooks.task_plan_sync import cmd_json_summary

    cmd_json_summary()


@plan.command(name="set-context")
@click.argument("pairs", nargs=-1, required=True)
def plan_set_context(pairs: tuple[str, ...]) -> None:
    """Store plan-level context metadata (K=V pairs, dot-paths supported)."""
    from dev10x.hooks.task_plan_sync import cmd_set_context

    cmd_set_context(args=list(pairs))


@plan.command(name="archive")
def plan_archive() -> None:
    """Archive completed plan to .claude/session/archive/."""
    from dev10x.hooks.task_plan_sync import cmd_archive

    cmd_archive()


@hook.command(name="permission-denied")
def permission_denied() -> None:
    """Handle PermissionDenied events via the validator registry.

    Reads JSON from stdin, dispatches to validators that implement
    correct(). Returns retry=true with corrective guidance when a
    validator recognizes the denied command.

    Also runs permission diagnostics to explain *why* a pre-approved
    tool was prompted (settings override semantics, missing rules).
    Exit codes: 0 always (retry decision is in JSON output).
    """
    from dev10x.domain import HookInput
    from dev10x.validators import get_chain

    inp = HookInput.from_stdin()

    if inp.command:
        result = get_chain().correct(inp=inp)
        if result is not None:
            result.emit()

    _run_permission_diagnostics(raw=inp.raw, cwd=inp.cwd)
    sys.exit(0)


def _run_permission_diagnostics(*, raw: dict, cwd: str) -> None:
    try:
        from dev10x.hooks.permission_diagnostics import diagnose, format_diagnostic

        result = diagnose(raw=raw, cwd=cwd)
        if result is None:
            return
        message = format_diagnostic(result=result)
        if message:
            print(
                json.dumps({"systemMessage": message}),
                file=sys.stderr,
            )
    except Exception:
        if _DEBUG:
            print("[HOOK_DEBUG] permission_diagnostics raised:", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)


@hook.command(name="validate-edit")
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, path_type=Path),
    default=None,
)
@click.option("--debug", is_flag=True)
def validate_edit(config_path: Path | None, debug: bool) -> None:
    """Validate Edit/Write tool calls against sensitive file rules.

    Reads JSON from stdin, checks file paths against rules.
    Exit codes: 0=allow, 2=block.
    """
    import json

    from dev10x.hooks.edit_validator import validate_edit_write

    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    validate_edit_write(
        data=data,
        yaml_path=config_path,
        debug=debug,
    )


@hook.group(name="session")
def session() -> None:
    """Session lifecycle commands."""


@session.command(name="reload")
def session_reload_cmd() -> None:
    """Reload prior session state (SessionStart hook)."""
    from dev10x.hooks.session import session_reload

    session_reload()


@session.command(name="compact")
def session_compact_cmd() -> None:
    """Inject context summary before compaction (PreCompact hook)."""
    from dev10x.hooks.session import context_compact

    context_compact()


@session.command(name="tmpdir")
def session_tmpdir_cmd() -> None:
    """Create session scratch directory and install mktmp.sh (SessionStart hook)."""
    from dev10x.hooks.session import session_tmpdir

    session_tmpdir()


@session.command(name="guidance")
def session_guidance_cmd() -> None:
    """Output session-guidance.md as additionalContext (SessionStart hook)."""
    from dev10x.hooks.session import session_guidance

    session_guidance()


@session.command(name="git-aliases")
def session_git_aliases_cmd() -> None:
    """Check git branch-comparison aliases and report status (SessionStart hook)."""
    from dev10x.hooks.session import session_git_aliases

    session_git_aliases()


@session.command(name="migrate-permissions")
def session_migrate_permissions_cmd() -> None:
    """Migrate stale plugin permission rules to current version (SessionStart hook)."""
    from dev10x.hooks.session import session_migrate_permissions

    session_migrate_permissions()


@session.command(name="persist")
def session_persist_cmd() -> None:
    """Persist session state to disk for next-session reload (SessionStop hook)."""
    from dev10x.hooks.session import session_persist

    session_persist()


@session.command(name="goodbye")
def session_goodbye_cmd() -> None:
    """Output goodbye message with community link and resume hint (SessionStop hook)."""
    from dev10x.hooks.session import session_goodbye

    session_goodbye()


@hook.group(name="skill")
def skill() -> None:
    """Skill lifecycle commands."""


@skill.command(name="tmpdir")
def skill_tmpdir_cmd() -> None:
    """Create scratch directory for skill (PreToolUse hook)."""
    from dev10x.hooks.skill import skill_tmpdir

    skill_tmpdir()


@skill.command(name="metrics")
def skill_metrics_cmd() -> None:
    """Append skill invocation metric to JSONL file (PostToolUse hook)."""
    from dev10x.hooks.skill import skill_metrics

    skill_metrics()


@hook.command(name="ruff-format")
def ruff_format_cmd() -> None:
    """Auto-format Python files with ruff after Edit/Write (PostToolUse hook)."""
    from dev10x.hooks.skill import ruff_format

    ruff_format()


@hook.group(name="audit")
def audit_group() -> None:
    """Hook execution audit commands (GH-860)."""


@audit_group.command(name="summary")
@click.option(
    "--since",
    "since",
    default=None,
    help="Relative window (e.g., 24h, 7d). Default: all records in retention.",
)
@click.option(
    "--hook",
    "hook_filter",
    default=None,
    help="Filter by hook name prefix.",
)
def audit_summary(since: str | None, hook_filter: str | None) -> None:
    """Summarize hook execution timing by hook name."""

    from dev10x.audit import iter_records, summarize

    since_dt = None
    if since:
        since_dt = _parse_since(value=since)

    records = iter_records(since=since_dt)
    stats = summarize(records=records)
    if hook_filter:
        stats = {k: v for k, v in stats.items() if k.startswith(hook_filter)}

    if not stats:
        click.echo("No audit records found.")
        return

    header = (
        f"{'hook':<30} {'count':>6} {'body_ms':>9} {'total_ms':>9} "
        f"{'startup_ms':>11} {'err':>4} {'blk':>4}"
    )
    click.echo(header)
    click.echo("-" * len(header))
    for name in sorted(stats.keys()):
        s = stats[name]
        click.echo(
            f"{name:<30} {s['count']:>6} {s['body_ms_avg']:>9} "
            f"{s['total_ms_avg']:>9} {s['startup_ms_avg']:>11} "
            f"{s['error_count']:>4} {s['block_count']:>4}"
        )


@audit_group.command(name="prune")
@click.option("--days", type=int, default=None, help="Override retention days.")
def audit_prune(days: int | None) -> None:
    """Delete log files older than the retention window."""
    from dev10x.audit import prune

    deleted = prune(retain_days=days)
    click.echo(f"Deleted {deleted} log file(s).")


def _parse_since(*, value: str) -> datetime | None:
    """Parse a relative time window like '24h' or '7d'."""
    value = value.strip().lower()
    if not value:
        return None
    try:
        if value.endswith("h"):
            return datetime.now(UTC) - timedelta(hours=int(value[:-1]))
        if value.endswith("d"):
            return datetime.now(UTC) - timedelta(days=int(value[:-1]))
        if value.endswith("m"):
            return datetime.now(UTC) - timedelta(minutes=int(value[:-1]))
    except ValueError:
        return None
    return None
