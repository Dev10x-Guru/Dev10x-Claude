from __future__ import annotations

import sys
from pathlib import Path

import click

from dev10x.domain.common.result import ErrorResult


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
    try:
        slack_review_request.cmd_prepare(args)
    except slack_review_request.GhCommandError as ex:
        click.echo(f"[ERROR] {ex}", err=True)
        sys.exit(1)


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
    """Send a Slack message via the importable slack_notify module (GH-442).

    Delegates to `dev10x.skills.notifications.slack_notify` so the command
    works when dev10x is installed via ``uvx`` — where ``skills/`` data files
    are not shipped as part of the wheel and cannot be reached by filesystem
    traversal from the installed package location.
    """
    if not message and not message_file:
        raise click.UsageError("Provide --message or --message-file.")

    from dev10x.skills.notifications import slack_notify

    msg: str
    if message_file is not None:
        msg = message_file.read_text()
    else:
        msg = message  # type: ignore[assignment]  # validated above

    result = slack_notify.notify_slack(
        channel=channel,
        message=msg,
        workspace=workspace,
        thread_ts=thread_ts,
    )
    if isinstance(result, ErrorResult):
        click.echo(f"❌ {result.error}", err=True)
        sys.exit(1)
    click.echo(f"✅ Slack message sent successfully! ts={result.value}")


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
