from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import click

from dev10x.core.domain.common.result import ErrorResult

if TYPE_CHECKING:  # pragma: no cover
    from dev10x.comm.skills.notifications.gchat_notify import PostedMessage
    from dev10x.comm.skills.notifications.gchat_watch import Watch


@click.group()
def skill() -> None:
    """Skill script commands (audit, notify, permission, release-notes, rename)."""


@skill.group()
def notify() -> None:
    """Post notifications (Slack review requests, generic Slack sends).

    Exposes the slack-review-request prepare/send flow and the generic
    slack-notify send call as version-stable `dev10x` subcommands so the
    `dev10x:slack-review-request` and `dev10x:slack` skills do not need
    to embed plugin-cache paths in their documented invocations.
    """


@notify.command(name="slack-review-prepare")
@click.option("--pr", type=int, required=True, help="PR number")
@click.option("--repo", required=True, help="GitHub repo (owner/name)")
def slack_review_prepare(*, pr: int, repo: str) -> None:
    """Resolve slack-review-request project config and emit the JSON envelope.

    Wraps `dev10x.comm.skills.notifications.slack_review_request` so callers
    can invoke `uvx dev10x skill notify slack-review-prepare ...` instead
    of the version-pinned `skills/slack-review-request/scripts/...`
    script path. Output is identical to the underlying `prepare` call.
    """
    import argparse

    from dev10x.comm.skills.notifications import slack_review_request

    args = argparse.Namespace(pr=pr, repo=repo)
    try:
        slack_review_request.cmd_prepare(args)
    except slack_review_request.GhCommandError as ex:
        click.echo(f"[ERROR] {ex}", err=True)
        sys.exit(1)


@notify.command(name="slack-send")
@click.option("--channel", default=None, help="Slack channel ID (e.g., C042DJ8AJKB)")
@click.option(
    "--remind",
    is_flag=True,
    default=False,
    help="DM the message to yourself instead of a channel (needs self_user_id)",
)
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
    channel: str | None,
    remind: bool,
    message: str | None,
    message_file: Path | None,
    thread_ts: str | None,
    workspace: str | None,
) -> None:
    """Send a Slack message via the importable slack_notify module (GH-442).

    Delegates to `dev10x.comm.skills.notifications.slack_notify` so the command
    works when dev10x is installed via ``uvx`` — where ``skills/`` data files
    are not shipped as part of the wheel and cannot be reached by filesystem
    traversal from the installed package location.
    """
    if not message and not message_file:
        raise click.UsageError("Provide --message or --message-file.")
    if remind == (channel is not None):
        raise click.UsageError("Provide exactly one of --channel or --remind.")

    from dev10x.comm.skills.notifications import slack_notify

    msg: str
    if message_file is not None:
        msg = message_file.read_text()
    else:
        msg = message  # type: ignore[assignment]  # validated above

    if remind:
        slack_notify.set_workspace(workspace)
        result = slack_notify.send_reminder(message=msg)
    else:
        result = slack_notify.notify_slack(
            channel=channel,  # type: ignore[arg-type]  # validated above
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
@click.option(
    "--thread",
    default=None,
    help=(
        "Reply into this thread instead of starting a new one. Accepts the full "
        "spaces/<space>/threads/<id> name or the bare thread id from a Chat URL"
    ),
)
@click.option(
    "--watch",
    "watch_replies",
    is_flag=True,
    default=False,
    help="After posting, watch the message's thread and notify --notify/--notify-role",
)
@click.option(
    "--notify",
    "notify_mailboxes",
    multiple=True,
    help="claude-bus mailbox told about replies (with --watch; repeatable)",
)
@click.option(
    "--notify-role",
    "notify_roles",
    multiple=True,
    help="Bus registry Role told about replies, resolved at delivery (with --watch; repeatable)",
)
@click.option(
    "--watch-mode",
    type=click.Choice(["reply", "ttl"]),
    default="reply",
    show_default=True,
    help="reply: disarm after the first delivered reply; ttl: stay armed until the TTL",
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
    thread: str | None,
    watch_replies: bool,
    notify_mailboxes: tuple[str, ...],
    notify_roles: tuple[str, ...],
    watch_mode: str,
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

    `--watch` arms a reply watch on the thread the message landed in
    (GH-1682); `gchat-watch poll` then delivers each reply over the bus.
    """
    has_targets = bool(notify_mailboxes or notify_roles)
    if watch_replies and not has_targets:
        raise click.UsageError("--watch needs at least one --notify or --notify-role.")
    if has_targets and not watch_replies:
        raise click.UsageError("--notify and --notify-role only apply with --watch.")
    msg, cards = _resolve_gchat_body(
        message=message,
        message_file=message_file,
        card_title=card_title,
        card_subtitle=card_subtitle,
        card_file=card_file,
    )

    from dev10x.comm.skills.notifications import gchat_notify

    if not watch_replies:
        result = gchat_notify.notify_gchat(
            space=space, message=msg, cards=cards, fallback_text=fallback_text, thread=thread
        )
        if isinstance(result, ErrorResult):
            click.echo(f"❌ {result.error}", err=True)
            sys.exit(1)
        click.echo(f"✅ Google Chat message sent! name={result.value}")
        return

    posted = gchat_notify.notify_gchat_detailed(
        space=space, message=msg, cards=cards, fallback_text=fallback_text, thread=thread
    )
    if isinstance(posted, ErrorResult):
        click.echo(f"❌ {posted.error}", err=True)
        sys.exit(1)
    click.echo(f"✅ Google Chat message sent! name={posted.value.name}")
    _arm_after_post(
        posted=posted.value,
        notify_mailboxes=notify_mailboxes,
        notify_roles=notify_roles,
        watch_mode=watch_mode,
    )


def _arm_after_post(
    *,
    posted: PostedMessage,
    notify_mailboxes: tuple[str, ...],
    notify_roles: tuple[str, ...],
    watch_mode: str,
) -> None:
    from dev10x.comm.skills.notifications import gchat_watch

    if not posted.thread:
        click.echo(
            "❌ Posted, but Google Chat reported no thread for the message, so no "
            "watch was armed.",
            err=True,
        )
        sys.exit(1)
    armed = gchat_watch.arm_watch(
        thread=posted.thread,
        notify=notify_mailboxes,
        notify_roles=notify_roles,
        mode=watch_mode,
        own_message_names=(posted.name,),
    )
    if isinstance(armed, ErrorResult):
        click.echo(f"❌ Posted, but the watch was not armed: {armed.error}", err=True)
        sys.exit(1)
    click.echo(_watch_line(watch=armed.value, kind="ARMED"))


def _watch_line(*, watch: Watch, kind: str) -> str:
    targets = ",".join((*watch.notify, *(f"role:{role}" for role in watch.notify_roles)))
    return " ".join(
        (
            kind,
            watch.id,
            watch.thread or watch.space,
            f"mode={watch.mode}",
            f"notify={targets or '-'}",
            f"route={'yes' if watch.route else 'no'}",
            f"expires={watch.expires_at.isoformat(timespec='seconds')}",
        )
    )


def _resolve_gchat_body(
    *,
    message: str | None,
    message_file: Path | None,
    card_title: str | None,
    card_subtitle: str | None,
    card_file: Path | None,
) -> tuple[str | None, list[dict] | None]:
    """Turn the shared body/card flags into a (text, cards) pair."""
    if not message and not message_file and not card_file:
        raise click.UsageError("Provide --message, --message-file, or --card-file.")
    if card_title and card_file:
        raise click.UsageError("Use --card-title or --card-file, not both.")
    if card_subtitle and not card_title:
        raise click.UsageError("--card-subtitle requires --card-title.")

    from dev10x.comm.skills.notifications import gchat_cards

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
    return msg, cards


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


@notify.group(name="gchat-watch")
def gchat_watch_group() -> None:
    """Watch Google Chat threads and spaces for new messages (GH-1612, GH-1682).

    Reads through your own `gog` grant, keeps a durable cursor per watch,
    and delivers each new message over the claude-bus as untrusted data.
    """


@gchat_watch_group.command(name="arm")
@click.option("--space", default=None, help="Space alias, id, or spaces/<id>")
@click.option(
    "--thread",
    default=None,
    help="spaces/<space>/threads/<id>, or a bare thread id with --space; omit to watch the space",
)
@click.option(
    "--notify", "notify_mailboxes", multiple=True, help="claude-bus mailbox (repeatable)"
)
@click.option(
    "--notify-role",
    "notify_roles",
    multiple=True,
    help="Bus registry Role, resolved to its newest Reply-To at delivery (repeatable)",
)
@click.option(
    "--route",
    is_flag=True,
    default=False,
    help="Route each message by domain through the bus registry (dispatcher mode)",
)
@click.option(
    "--mode",
    type=click.Choice(["reply", "ttl"]),
    default="reply",
    show_default=True,
    help="reply: disarm after the first delivered message; ttl: stay armed until the TTL",
)
@click.option(
    "--ttl-hours",
    type=click.FloatRange(min=0, min_open=True),
    default=24.0,
    show_default=True,
)
def gchat_watch_arm(
    *,
    space: str | None,
    thread: str | None,
    notify_mailboxes: tuple[str, ...],
    notify_roles: tuple[str, ...],
    route: bool,
    mode: str,
    ttl_hours: float,
) -> None:
    """Arm (or extend) a watch; re-arming merges targets and keeps the cursor."""
    from datetime import timedelta

    from dev10x.comm.skills.notifications import gchat_watch

    result = gchat_watch.arm_watch(
        space=space,
        thread=thread,
        notify=notify_mailboxes,
        notify_roles=notify_roles,
        route=route,
        mode=mode,
        ttl=timedelta(hours=ttl_hours),
    )
    if isinstance(result, ErrorResult):
        click.echo(f"ERROR {result.error}", err=True)
        sys.exit(1)
    click.echo(_watch_line(watch=result.value, kind="ARMED"))


@gchat_watch_group.command(name="disarm")
@click.option("--id", "watch_id", default=None, help="Watch id, as printed by arm or list")
@click.option("--space", default=None, help="Space alias, id, or spaces/<id>")
@click.option("--thread", default=None, help="Thread name of the watch to disarm")
def gchat_watch_disarm(*, watch_id: str | None, space: str | None, thread: str | None) -> None:
    """Disarm a watch by id, or by the space/thread it watches."""
    from dev10x.comm.skills.notifications import gchat_watch

    result = gchat_watch.disarm_watch(watch_id=watch_id, space=space, thread=thread)
    if isinstance(result, ErrorResult):
        click.echo(f"ERROR {result.error}", err=True)
        sys.exit(1)
    click.echo(f"DISARMED {result.value.id}")


@gchat_watch_group.command(name="list")
def gchat_watch_list() -> None:
    """Print one line per armed watch."""
    from dev10x.comm.skills.notifications import gchat_watch

    result = gchat_watch.list_watches()
    if isinstance(result, ErrorResult):
        click.echo(f"ERROR {result.error}", err=True)
        sys.exit(1)
    if not result.value:
        click.echo("No armed Google Chat watches.")
    for watch in result.value:
        click.echo(_watch_line(watch=watch, kind="WATCH"))


@gchat_watch_group.command(name="poll")
@click.option(
    "--once",
    is_flag=True,
    default=False,
    help="Exit after the first poll that reports anything (run under background Bash)",
)
@click.option(
    "--interval",
    type=click.FloatRange(min=0),
    default=60.0,
    show_default=True,
    help="Seconds between polls",
)
@click.option(
    "--polls",
    type=click.IntRange(min=1),
    default=None,
    help="Give up after N polls",
)
def gchat_watch_poll(*, once: bool, interval: float, polls: int | None) -> None:
    """Poll armed watches and print NEW/UNROUTED/DEAD/EXPIRED/DISARMED/GAP/FAILED lines.

    Exits 0 when nothing is armed any more, after the first batch with
    events under `--once`, or after `--polls` polls.
    """
    import time
    from datetime import UTC, datetime

    from dev10x.comm.skills.notifications import gchat_watch

    result = gchat_watch.watch_loop(
        poll=lambda: gchat_watch.poll_once(reader=gchat_watch.gog_reader, now=datetime.now(UTC)),
        emit=lambda line: click.echo(line),
        sleep=time.sleep,
        interval=interval,
        once=once,
        polls=polls,
    )
    if isinstance(result, ErrorResult):
        click.echo(f"ERROR {result.error}", err=True)
        sys.exit(1)


@notify.command(name="gchat-update")
@click.option(
    "--message-name",
    required=True,
    help="Full spaces/<space>/messages/<id> name, as printed by gchat-send",
)
@click.option("--message", default=None, help="Replacement message text (or use --message-file)")
@click.option(
    "--message-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Read the replacement message body from this file",
)
@click.option(
    "--card-title",
    default=None,
    help="Render the replacement body as a cardsV2 panel with this header title",
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
def gchat_update(
    *,
    message_name: str,
    message: str | None,
    message_file: Path | None,
    card_title: str | None,
    card_subtitle: str | None,
    card_file: Path | None,
    fallback_text: str | None,
) -> None:
    """Edit a Google Chat message the bot posted earlier.

    Takes the same body flags as `gchat-send`. No `--space` is needed: the
    space is already part of the message name.

    Only fields you supply are masked, so replacing the text of a card
    message leaves its card intact. Under app auth the bot can edit only
    its own messages — a message posted by a person returns a 403.
    """
    msg, cards = _resolve_gchat_body(
        message=message,
        message_file=message_file,
        card_title=card_title,
        card_subtitle=card_subtitle,
        card_file=card_file,
    )

    from dev10x.comm.skills.notifications import gchat_notify

    result = gchat_notify.update_gchat_message(
        message_name=message_name, message=msg, cards=cards, fallback_text=fallback_text
    )
    if isinstance(result, ErrorResult):
        click.echo(f"❌ {result.error}", err=True)
        sys.exit(1)
    click.echo(f"✅ Google Chat message updated! name={result.value}")


@notify.command(name="gchat-delete")
@click.option(
    "--message-name",
    required=True,
    help="Full spaces/<space>/messages/<id> name, as printed by gchat-send",
)
def gchat_delete(*, message_name: str) -> None:
    """Delete a Google Chat message the bot posted earlier.

    Under app auth the bot can delete only its own messages — a message
    posted by a person returns a 403.
    """
    from dev10x.comm.skills.notifications import gchat_notify

    result = gchat_notify.delete_gchat_message(message_name=message_name)
    if isinstance(result, ErrorResult):
        click.echo(f"❌ {result.error}", err=True)
        sys.exit(1)
    click.echo(f"✅ Google Chat message deleted! name={result.value}")


@notify.command(name="gchat-review-prepare")
@click.option("--pr", type=int, required=True, help="PR number")
@click.option("--repo", required=True, help="GitHub repo (owner/name)")
def gchat_review_prepare(*, pr: int, repo: str) -> None:
    """Resolve gchat-review-request project config and emit the JSON envelope.

    Mirrors `slack-review-prepare`. Output keys: skip, ask, space, mentions,
    resolved_mentions, message, pr_url, pr_title.
    """
    import argparse

    from dev10x.comm.skills.notifications import gchat_review_request

    args = argparse.Namespace(pr=pr, repo=repo)
    try:
        gchat_review_request.cmd_prepare(args)
    except gchat_review_request.GhCommandError as ex:
        click.echo(f"[ERROR] {ex}", err=True)
        sys.exit(1)


@skill.command(name="rename")
@click.argument("old")
@click.argument("new")
@click.option(
    "--apply",
    "apply_changes",
    is_flag=True,
    default=False,
    help="Write the rewrite to disk. Without it, only the diff is printed.",
)
@click.option(
    "--root",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=".",
    show_default=True,
    help="Repository checkout to rewrite.",
)
def rename(*, old: str, new: str, apply_changes: bool, root: Path) -> None:
    """Rewrite one skill's invocation name across the repo (GH-1558).

    OLD and NEW are `<plugin>:<skill>` names, e.g. `dev10x:tts` and
    `dev10x-qa:tts`; a bare skill name means the `dev10x` core plugin.
    Plugin names come from `src/dev10x/core/plugins.yaml`. Prints a
    unified diff and changes nothing unless `--apply` is passed.
    """
    from dev10x.core.plugin_map import load_plugin_map
    from dev10x.core.skill_rename import plan_rename_from_text

    result = plan_rename_from_text(
        root=root.resolve(),
        old=old,
        new=new,
        plugin_map=load_plugin_map(),
    )
    if isinstance(result, ErrorResult):
        click.echo(f"❌ {result.error}", err=True)
        sys.exit(1)
    plan = result.value
    click.echo(plan.diff(), nl=False)
    summary = (
        f"{plan.replacements} reference(s) in {len(plan.rewrites)} file(s): "
        f"{plan.old.text} -> {plan.new.text}"
    )
    if apply_changes:
        plan.apply()
        click.echo(f"Rewrote {summary}")
        return
    click.echo(f"Dry run, nothing written. Would rewrite {summary}. Pass --apply to write.")


@skill.command(name="prune-overrides")
@click.option(
    "--settings",
    "settings_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=Path(".claude/settings.local.json"),
    show_default=True,
    help="Settings file to plan against (project-local scope by default).",
)
@click.option(
    "--set",
    "assignments",
    multiple=True,
    metavar="NAME=VISIBILITY",
    help="Proposed visibility: off, name-only, user-invocable-only, or on. Repeatable.",
)
@click.option(
    "--disable-plugin",
    "plugin_disables",
    multiple=True,
    metavar="PLUGIN@MARKETPLACE",
    help="Plugin to switch off for this project via enabledPlugins. Repeatable.",
)
@click.option("--keep", "keeps", multiple=True, help="Never change this name. Repeatable.")
@click.option(
    "--allowlist",
    "allowlist_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="YAML with a `keep:` list (default ~/.config/Dev10x/skill-prune.yaml).",
)
@click.option(
    "--apply",
    "apply_changes",
    is_flag=True,
    default=False,
    help="Write the plan to the settings file. Without it, only the plan is printed.",
)
def prune_overrides(
    *,
    settings_path: Path,
    assignments: tuple[str, ...],
    plugin_disables: tuple[str, ...],
    keeps: tuple[str, ...],
    allowlist_path: Path | None,
    apply_changes: bool,
) -> None:
    """Plan (and with --apply, write) per-project skill pruning (GH-1627).

    Prints one JSON object: the planned `skillOverrides` changes, plugins
    to switch off, and what was left alone and why. Re-running on an
    already-pruned file reports `has_changes: false`.
    """
    import json

    from dev10x.commands.json_output import fail_json
    from dev10x.core.domain.common.skill_overrides import (
        PrunePlan,
        Visibility,
        apply_prune,
        load_allowlist,
        parse_settings,
        plan_prune,
    )
    from dev10x.core.domain.dev10x_paths import Dev10xConfigDir
    from dev10x.core.domain.file_locks import locked_json_update

    proposed: dict[str, Visibility] = {}
    for assignment in assignments:
        name, _, value = assignment.partition("=")
        try:
            proposed[name.strip()] = Visibility(value.strip())
        except ValueError:
            fail_json(error=f"invalid --set '{assignment}'")
    loaded = load_allowlist(
        path=allowlist_path or Dev10xConfigDir.skill_prune_yaml(),
        required=allowlist_path is not None,
    )
    if isinstance(loaded, ErrorResult):
        fail_json(error=loaded)
    allowlist = loaded.value | frozenset(keeps)
    settings: dict = {}
    if settings_path.exists():
        try:
            text = settings_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            fail_json(error=f"cannot read {settings_path}: {exc}")
        parsed = parse_settings(text=text, source=str(settings_path))
        if isinstance(parsed, ErrorResult):
            fail_json(error=parsed)
        settings = parsed.value

    def plan_against(*, current: dict) -> PrunePlan:
        return plan_prune(
            settings=current,
            proposed=proposed,
            plugin_disables=plugin_disables,
            allowlist=allowlist,
        )

    plan = plan_against(current=settings)
    written = apply_changes and plan.has_changes
    if written:
        with locked_json_update(settings_path) as data:
            plan = plan_against(current=data)
            merged = apply_prune(settings=data, plan=plan)
            data.clear()
            data.update(merged)
    report = plan.to_dict()
    if written:
        report["written"] = str(settings_path)
    click.echo(json.dumps(report, indent=2))


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
    from dev10x.teach.skills.audit import instruction_budget as mod

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
