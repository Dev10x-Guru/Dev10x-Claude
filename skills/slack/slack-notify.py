#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["slack_sdk", "pyyaml"]
# ///
"""
Slack notification tool for posting messages and uploading files to channels.

Usage:
    slack-notify.py --channel CHANNEL_ID --message "Your message here"
    slack-notify.py --channel CHANNEL_ID --files screenshot.png video.webm --message "Evidence"
    slack-notify.py --channel CHANNEL_ID --thread-ts 123.456 --files report.png
    slack-notify.py --remind "Follow up on PR #1234"
    slack-notify.py --delete-file F0ALXGBAAUC

Token resolution order:
    1. --workspace <name> flag → keyring at service=slack-<name>
    2. SLACK_TOKEN environment variable
    3. Default keyring at service=slack

Configuration:
    ~/.claude/memory/Dev10x/slack-config.yaml — user groups, self_user_id,
    bot_username, and optional `workspaces:` map for multi-workspace setups.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import subprocess
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from slack_sdk import WebClient

CONFIG_PATH = pathlib.Path.home() / ".claude" / "memory" / "slack-config.yaml"

_active_workspace: str | None = None


def _load_config() -> dict:
    if CONFIG_PATH.exists():
        import yaml

        return yaml.safe_load(CONFIG_PATH.read_text()) or {}
    return {}


_config = _load_config()


def _workspace_config() -> dict:
    if _active_workspace is None:
        return {}
    workspaces = _config.get("workspaces", {}) or {}
    return workspaces.get(_active_workspace, {}) or {}


def set_workspace(name: str | None) -> None:
    """Select an active workspace. Affects keyring service and per-workspace config."""
    global _active_workspace
    _active_workspace = name


def _resolve(key: str, default: str = "") -> str:
    """Read a config key, preferring the active workspace's override."""
    ws = _workspace_config()
    if key in ws:
        return ws[key] or default
    return _config.get(key, default) or default


def _self_user_id() -> str:
    return os.environ.get("SLACK_SELF_USER_ID") or _resolve("self_user_id", "")


def _bot_username() -> str:
    return _resolve("bot_username", "Claude AI")


def _user_groups() -> dict[str, str]:
    ws = _workspace_config()
    if "user_groups" in ws:
        return ws.get("user_groups") or {}
    return _config.get("user_groups", {}) or {}


def resolve_mentions(message: str) -> str:
    for mention, group_id in _user_groups().items():
        message = message.replace(mention, group_id)
    return message


def _keyring_lookup(*, service: str, key: str) -> str | None:
    if sys.platform == "darwin":
        cmd = ["security", "find-generic-password", "-s", service, "-a", key, "-w"]
    else:
        cmd = ["secret-tool", "lookup", "service", service, "key", key]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout.strip() or None
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def _keyring_service() -> str:
    """Resolve keyring service name for the active workspace.

    Honors `keyring_service:` override in the workspace config; otherwise
    falls back to `slack-<workspace>`.
    """
    if _active_workspace is None:
        return "slack"
    ws = _workspace_config()
    override = ws.get("keyring_service")
    if override:
        return override
    return f"slack-{_active_workspace}"


def get_token() -> str:
    """Resolve the Slack bot token.

    Resolution order:
      1. If --workspace was set: keyring at the workspace's service name.
         Raise if missing — workspace was explicitly requested.
      2. SLACK_TOKEN environment variable.
      3. Default keyring at service=slack.
    """
    if _active_workspace is not None:
        service = _keyring_service()
        token = _keyring_lookup(service=service, key="bot_token")
        if token:
            return token
        raise RuntimeError(
            f"No Slack token found in keyring for workspace "
            f"'{_active_workspace}' (service={service})"
        )
    env_token = os.environ.get("SLACK_TOKEN")
    if env_token:
        return env_token
    token = _keyring_lookup(service="slack", key="bot_token")
    if token:
        return token
    raise RuntimeError(
        "No Slack token found. Set SLACK_TOKEN env, configure the default "
        "keyring (service=slack, key=bot_token), or pass --workspace NAME."
    )


def send_slack_message(
    channel: str,
    message: str,
    thread_ts: str | None = None,
    broadcast: bool = False,
    reactions: list[str] | None = None,
    unfurl: bool = False,
) -> str | None:
    try:
        from slack_sdk import WebClient

        resolved_message = resolve_mentions(message)
        token = get_token()
        is_user_token = token.startswith("xoxp-")
        client = WebClient(token=token)
        result = client.chat_postMessage(
            channel=channel,
            text=resolved_message,
            username=None if is_user_token else _bot_username(),
            thread_ts=thread_ts,
            reply_broadcast=broadcast if thread_ts else None,
            unfurl_links=unfurl,
            unfurl_media=unfurl,
        )
        ts = result["ts"]
        if reactions:
            for emoji in reactions:
                client.reactions_add(channel=channel, timestamp=ts, name=emoji)
        return ts
    except Exception as ex:
        print(f"❌ Failed to send Slack message: {ex}", file=sys.stderr)
        return None


def upload_slack_files(
    channel: str,
    file_paths: list[str],
    message: str | None = None,
    thread_ts: str | None = None,
) -> str | None:
    from slack_sdk import WebClient
    from slack_sdk.errors import SlackApiError

    token = get_token()
    client = WebClient(token=token)
    resolved_message = resolve_mentions(message) if message else None

    file_uploads = []
    for path in file_paths:
        if not os.path.exists(path):
            print(f"❌ File not found: {path}", file=sys.stderr)
            return None
        file_uploads.append({"file": path, "title": os.path.basename(path)})

    try:
        result = _files_upload_v2(
            client=client,
            file_uploads=file_uploads,
            channel=channel,
            initial_comment=resolved_message,
            thread_ts=thread_ts,
        )
        files = result.get("files", [])
        print(f"✅ Uploaded {len(file_uploads)} file(s): {[f.get('id') for f in files]}")
        return files[0].get("id") if files else None
    except SlackApiError as ex:
        if ex.response.get("error") == "missing_scope":
            needed = ex.response.get("needed", "files:write")
            print(
                f"❌ Bot token missing '{needed}' scope. "
                f"Add it at https://api.slack.com/apps → OAuth & Permissions.",
                file=sys.stderr,
            )
            raise SystemExit(1) from ex
        raise


def _files_upload_v2(
    client: WebClient,
    file_uploads: list[dict],
    channel: str,
    initial_comment: str | None,
    thread_ts: str | None,
) -> dict:
    from slack_sdk.errors import SlackApiError

    kwargs = dict(
        file_uploads=file_uploads,
        channel=channel,
        initial_comment=initial_comment,
        thread_ts=thread_ts,
    )
    try:
        return client.files_upload_v2(**kwargs)
    except SlackApiError as ex:
        if ex.response.get("error") == "not_in_channel":
            try:
                print("Bot not in channel, joining…", file=sys.stderr)
                client.conversations_join(channel=channel)
                return client.files_upload_v2(**kwargs)
            except SlackApiError:
                print(
                    f"❌ Bot is not a member of channel {channel} and cannot auto-join. "
                    f"Invite the bot via channel settings → Integrations.",
                    file=sys.stderr,
                )
                raise SystemExit(1) from ex
        raise


def send_reminder(message: str) -> str | None:
    self_user_id = _self_user_id()
    if not self_user_id:
        print(
            "❌ self_user_id not configured. Set it in "
            f"{CONFIG_PATH} or SLACK_SELF_USER_ID env var.",
            file=sys.stderr,
        )
        return None
    try:
        from slack_sdk import WebClient

        token = get_token()
        client = WebClient(token=token)
        dm = client.conversations_open(users=self_user_id)
        channel = dm["channel"]["id"]
        return send_slack_message(channel=channel, message=message)
    except Exception as ex:
        print(f"❌ Failed to send reminder: {ex}", file=sys.stderr)
        return None


def update_slack_message(channel: str, ts: str, message: str) -> bool:
    try:
        from slack_sdk import WebClient

        resolved_message = resolve_mentions(message)
        token = get_token()
        client = WebClient(token=token)
        client.chat_update(channel=channel, ts=ts, text=resolved_message)
        return True
    except Exception as ex:
        print(f"❌ Failed to update Slack message: {ex}", file=sys.stderr)
        return False


def delete_slack_message(channel: str, ts: str) -> bool:
    try:
        from slack_sdk import WebClient

        token = get_token()
        client = WebClient(token=token)
        client.chat_delete(channel=channel, ts=ts)
        return True
    except Exception as ex:
        print(f"❌ Failed to delete Slack message: {ex}", file=sys.stderr)
        return False


def delete_slack_file(file_id: str) -> bool:
    try:
        from slack_sdk import WebClient

        token = get_token()
        client = WebClient(token=token)
        client.files_delete(file=file_id)
        return True
    except Exception as ex:
        print(f"❌ Failed to delete Slack file: {ex}", file=sys.stderr)
        return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Send Slack notifications",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--channel",
        required=False,
        help="Slack channel ID (e.g., C042DJ8AJKB)",
    )
    parser.add_argument(
        "--message",
        help="Message to send (or use --message-file)",
    )
    parser.add_argument(
        "--thread-ts",
        help="Thread timestamp to reply to (e.g., 1770113637.855309)",
    )
    parser.add_argument(
        "--broadcast",
        action="store_true",
        help="Also send thread reply to channel (reply_broadcast)",
    )
    parser.add_argument(
        "--reactions",
        nargs="+",
        help="Emoji names to add as reactions (e.g., one two three four five)",
    )
    parser.add_argument(
        "--unfurl",
        action="store_true",
        help="Enable link previews (unfurl_links and unfurl_media)",
    )
    parser.add_argument(
        "--delete",
        metavar="TS",
        help="Delete a message by timestamp instead of sending",
    )
    parser.add_argument(
        "--delete-file",
        metavar="FILE_ID",
        help="Delete a Slack file by ID (e.g., F0ALXGBAAUC)",
    )
    parser.add_argument(
        "--update",
        metavar="TS",
        help="Update an existing message by timestamp (requires --message or --message-file)",
    )
    parser.add_argument(
        "--message-file",
        help="Read message from file instead of --message",
    )
    parser.add_argument(
        "--files",
        nargs="+",
        help="File paths to upload (images, videos, etc.)",
    )
    parser.add_argument(
        "--remind",
        metavar="MESSAGE",
        help="Send a DM reminder to yourself (requires self_user_id in config)",
    )
    parser.add_argument(
        "--workspace",
        metavar="NAME",
        help=(
            "Select a Slack workspace by name. Reads the bot token from "
            "keyring service=slack-<name> (override via "
            "workspaces.<name>.keyring_service in config) and applies "
            "per-workspace overrides for bot_username / self_user_id / "
            "user_groups."
        ),
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show verbose output",
    )

    args = parser.parse_args()

    if args.workspace:
        set_workspace(args.workspace)

    if args.remind:
        ts = send_reminder(message=args.remind)
        if ts:
            print(f"✅ Reminder sent! ts={ts}")
            sys.exit(0)
        else:
            sys.exit(1)

    if args.delete_file:
        success = delete_slack_file(file_id=args.delete_file)
        if success:
            print(f"✅ Deleted file {args.delete_file}")
            sys.exit(0)
        else:
            sys.exit(1)

    if not args.channel:
        print("❌ --channel is required", file=sys.stderr)
        sys.exit(1)

    if args.delete:
        success = delete_slack_message(channel=args.channel, ts=args.delete)
        if success:
            print(f"✅ Deleted message {args.delete}")
            sys.exit(0)
        else:
            sys.exit(1)

    message = args.message
    if args.message_file:
        with open(args.message_file) as f:
            message = f.read()

    if args.update:
        if not message:
            print("❌ --message or --message-file required with --update", file=sys.stderr)
            sys.exit(1)
        success = update_slack_message(channel=args.channel, ts=args.update, message=message)
        if success:
            print(f"✅ Updated message {args.update}")
            sys.exit(0)
        else:
            sys.exit(1)

    if args.files:
        file_id = upload_slack_files(
            channel=args.channel,
            file_paths=args.files,
            message=message,
            thread_ts=args.thread_ts,
        )
        sys.exit(0 if file_id else 1)

    if not message:
        print("❌ --message or --message-file required", file=sys.stderr)
        sys.exit(1)

    if args.verbose:
        print(f"Sending to channel: {args.channel}")
        print(f"Message: {message[:100]}...")

    ts = send_slack_message(
        channel=args.channel,
        message=message,
        thread_ts=args.thread_ts,
        broadcast=args.broadcast,
        reactions=args.reactions,
        unfurl=args.unfurl,
    )

    if ts:
        print(f"✅ Slack message sent successfully! ts={ts}")
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
