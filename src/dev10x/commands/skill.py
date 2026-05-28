from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import click


@click.group()
def skill() -> None:
    """Skill script commands (audit, notify, permission, release-notes)."""


@skill.group()
def notify() -> None:
    """Post notifications (Slack review requests, generic Slack sends).

    Exposes the slack-review-request prepare/send flow and the generic
    slack-notify send call as version-stable `dev10x` subcommands so the
    `Dev10x:slack-review-request` and `Dev10x:slack` skills do not need
    to embed plugin-cache paths in their documented invocations.
    """


def _plugin_root() -> Path:
    """Resolve the plugin root containing the skills/ directory.

    `src/dev10x/commands/skill.py` -> parents[3] = plugin root.
    """
    return Path(__file__).resolve().parents[3]


@notify.command(name="slack-review-prepare")
@click.option("--pr", type=int, required=True, help="PR number")
@click.option("--repo", required=True, help="GitHub repo (owner/name)")
def slack_review_prepare(*, pr: int, repo: str) -> None:
    """Resolve slack-review-request project config and emit the JSON envelope.

    Wraps `dev10x.skills.notifications.slack_review_request` so callers
    can invoke `uvx dev10x skill notify slack-review-prepare ...` instead
    of the version-pinned `skills/slack-review-request/scripts/...`
    script path. Output is identical to the underlying `prepare` call.
    """
    import argparse

    from dev10x.skills.notifications import slack_review_request

    args = argparse.Namespace(pr=pr, repo=repo)
    slack_review_request.cmd_prepare(args)


@notify.command(name="slack-send")
@click.option("--channel", required=True, help="Slack channel ID (e.g., C042DJ8AJKB)")
@click.option("--message", default=None, help="Message text (or use --message-file)")
@click.option(
    "--message-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Read message body from this file",
)
@click.option("--thread-ts", default=None, help="Reply in this thread")
@click.option("--workspace", default=None, help="Select non-default Slack workspace")
def slack_send(
    *,
    channel: str,
    message: str | None,
    message_file: Path | None,
    thread_ts: str | None,
    workspace: str | None,
) -> None:
    """Send a Slack message via the plugin's slack-notify.py script.

    Delegates to `skills/slack/slack-notify.py` while exposing a
    version-stable CLI surface. The underlying script handles token
    resolution, user-group mention expansion, and bot identity.
    """
    if not message and not message_file:
        raise click.UsageError("Provide --message or --message-file.")

    slack_notify = _plugin_root() / "skills" / "slack" / "slack-notify.py"
    if not slack_notify.exists():
        click.echo(f"slack-notify.py not found at {slack_notify}", err=True)
        sys.exit(1)

    cmd: list[str] = [str(slack_notify), "--channel", channel]
    if message_file is not None:
        cmd.extend(["--message-file", str(message_file)])
    if message is not None:
        cmd.extend(["--message", message])
    if thread_ts is not None:
        cmd.extend(["--thread-ts", thread_ts])
    if workspace is not None:
        cmd.extend(["--workspace", workspace])

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.stdout:
        click.echo(result.stdout.rstrip())
    if result.returncode != 0:
        if result.stderr:
            click.echo(result.stderr.rstrip(), err=True)
        sys.exit(result.returncode)


@skill.command(name="count-instructions")
@click.argument(
    "paths",
    nargs=-1,
    type=click.Path(exists=True, path_type=Path),
    required=True,
)
@click.option(
    "--warn",
    type=int,
    default=None,
    help="Threshold at which to flag the file (default: 100).",
)
@click.option(
    "--over",
    type=int,
    default=None,
    help="Threshold above which to exit non-zero (default: 150).",
)
@click.option(
    "--quiet",
    is_flag=True,
    help="Print only over-threshold files.",
)
def count_instructions(
    *,
    paths: tuple[Path, ...],
    warn: int | None,
    over: int | None,
    quiet: bool,
) -> None:
    """Count actionable instructions per skill file (GH-882 instruction budget).

    QRSPI finding: LLMs follow ~150–200 instructions reliably, then silently
    skip the rest. Large skills that cross this budget risk dropping alignment
    steps without any error signal.

    Accepts individual SKILL.md files or directories (scanned recursively).
    Exit code 1 if any file exceeds --over (default 150).
    """
    from dev10x.skills.audit import instruction_budget as mod

    w = warn if warn is not None else mod.DEFAULT_WARN
    o = over if over is not None else mod.DEFAULT_OVER

    files: list[Path] = []
    for p in paths:
        if p.is_dir():
            files.extend(mod.find_skill_files(p))
        elif p.is_file():
            files.append(p)

    if not files:
        click.echo("No SKILL.md files found.")
        sys.exit(0)

    reports = mod.scan(files, warn=w, over=o)

    max_width = max((len(str(r.path)) for r in reports), default=40)
    over_count = 0
    warn_count = 0

    for report in reports:
        marker = {"ok": " ", "warn": "!", "over": "✗"}[report.status]
        if report.status == "over":
            over_count += 1
        elif report.status == "warn":
            warn_count += 1
        if quiet and report.status == "ok":
            continue
        click.echo(f" {marker} {str(report.path):<{max_width}}  {report.count:>4}")

    click.echo()
    click.echo(f"Thresholds: warn ≥ {w}, over ≥ {o}")
    click.echo(f"Scanned {len(reports)} file(s): {warn_count} warn, {over_count} over.")

    sys.exit(1 if over_count > 0 else 0)
