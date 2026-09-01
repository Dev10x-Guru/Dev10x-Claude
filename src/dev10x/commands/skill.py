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


@notify.command(name="gchat-send")
@click.option("--space", required=True, help="Google Chat space alias (see gchat-config.yaml)")
@click.option("--message", default=None, help="Message text (or use --message-file)")
@click.option(
    "--message-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Read message body from this file",
)
@click.option(
    "--card-title",
    default=None,
    help="Render the message as a cardsV2 panel with this header title",
)
@click.option("--card-subtitle", default=None, help="Subtitle for the --card-title header")
@click.option(
    "--card-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Read a raw cardsV2 array (or a single card) from this JSON file",
)
@click.option(
    "--fallback-text",
    default=None,
    help="Plain-text shown in mobile notifications when the card cannot render",
)
def gchat_send(
    *,
    space: str,
    message: str | None,
    message_file: Path | None,
    card_title: str | None,
    card_subtitle: str | None,
    card_file: Path | None,
    fallback_text: str | None,
) -> None:
    """Send a Google Chat message via the importable gchat_notify module.

    Posts through the private Chat bot (service-account app auth). Mirrors
    `slack-send`; works under `uvx` because the logic lives in the package.

    Plain text by default. `--card-title` moves the message body into a
    cardsV2 panel so its markup renders as formatted text; `--card-file`
    supplies hand-authored card JSON alongside the message instead.

    A card cannot resolve mentions, and `--card-title` leaves no text
    behind, so pair `--message` with `--card-file` when the notification
    has to reach a person.
    """
    if not message and not message_file and not card_file:
        raise click.UsageError("Provide --message, --message-file, or --card-file.")
    if card_title and card_file:
        raise click.UsageError("Use --card-title or --card-file, not both.")
    if card_subtitle and not card_title:
        raise click.UsageError("--card-subtitle requires --card-title.")

    from dev10x.skills.notifications import gchat_cards, gchat_notify

    msg: str | None = None
    if message_file is not None:
        msg = message_file.read_text()
    elif message is not None:
        msg = message

    cards: list[dict] | None = None
    if card_file is not None:
        cards = _load_cards(card_file)
    elif card_title is not None:
        # --card-title excludes --card-file, and the first guard already
        # rejected a call with no body, so a body is guaranteed here.
        assert msg is not None
        cards = [
            gchat_cards.simple_card(
                card_id="dev10x-message", body=msg, title=card_title, subtitle=card_subtitle
            )
        ]
        # The body now lives in the panel; leaving it in `text` duplicates it.
        msg = None

    result = gchat_notify.notify_gchat(
        space=space, message=msg, cards=cards, fallback_text=fallback_text
    )
    if isinstance(result, ErrorResult):
        click.echo(f"❌ {result.error}", err=True)
        sys.exit(1)
    click.echo(f"✅ Google Chat message sent! name={result.value}")


def _load_cards(card_file: Path) -> list[dict]:
    """Accept a cardsV2 array, one CardWithId, or a bare Card object."""
    import json

    try:
        parsed = json.loads(card_file.read_text())
    except json.JSONDecodeError as ex:
        raise click.UsageError(f"{card_file} is not valid JSON: {ex}") from ex
    if isinstance(parsed, list):
        return parsed
    if not isinstance(parsed, dict):
        raise click.UsageError(f"{card_file} must hold a cardsV2 array or a single card object.")
    if "card" in parsed:
        return [parsed]
    return [{"cardId": "dev10x-message", "card": parsed}]


@notify.command(name="gchat-review-prepare")
@click.option("--pr", type=int, required=True, help="PR number")
@click.option("--repo", required=True, help="GitHub repo (owner/name)")
def gchat_review_prepare(*, pr: int, repo: str) -> None:
    """Resolve gchat-review-request project config and emit the JSON envelope.

    Mirrors `slack-review-prepare`. Output keys: skip, ask, space, mentions,
    resolved_mentions, message, pr_url, pr_title.
    """
    import argparse

    from dev10x.skills.notifications import gchat_review_request

    args = argparse.Namespace(pr=pr, repo=repo)
    try:
        gchat_review_request.cmd_prepare(args)
    except gchat_review_request.GhCommandError as ex:
        click.echo(f"[ERROR] {ex}", err=True)
        sys.exit(1)


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
