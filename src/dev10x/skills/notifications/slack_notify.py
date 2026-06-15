"""Importable Slack notification helpers (GH-442).

Extracted from ``skills/slack/slack-notify.py`` so the logic is available
when dev10x is installed via ``uvx`` — where the ``skills/`` data files are
not part of the wheel and cannot be located via filesystem traversal.

The standalone ``skills/slack/slack-notify.py`` uv-script remains the entry
point for direct plugin-checkout invocations; this module powers the
``dev10x skill notify slack-send`` CLI command and any in-process callers.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from dev10x.domain.common.result import ErrorResult, Result, err, ok
from dev10x.domain.dev10x_paths import Dev10xConfigDir

if TYPE_CHECKING:
    from slack_sdk import WebClient
    from slack_sdk.web import SlackResponse

log = logging.getLogger(__name__)

_active_workspace: str | None = None
_config: dict | None = None


def _config_path() -> Path:
    return Dev10xConfigDir.slack_config_yaml()


def _load_config() -> dict:
    config_path = _config_path()
    if config_path.exists():
        import yaml

        return yaml.safe_load(config_path.read_text()) or {}
    return {}


def _get_config() -> dict:
    global _config
    if _config is None:
        _config = _load_config()
    return _config


def _workspace_config() -> dict:
    if _active_workspace is None:
        return {}
    workspaces = _get_config().get("workspaces", {}) or {}
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
    return _get_config().get(key, default) or default


def _self_user_id() -> str:
    return os.environ.get("SLACK_SELF_USER_ID") or _resolve("self_user_id", "")


def _bot_username() -> str:
    return _resolve("bot_username", "Claude AI")


def _user_groups() -> dict[str, str]:
    ws = _workspace_config()
    if "user_groups" in ws:
        return ws.get("user_groups") or {}
    return _get_config().get("user_groups", {}) or {}


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

    Honors ``keyring_service:`` override in the workspace config; otherwise
    falls back to ``slack-<workspace>``.
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
) -> Result[str]:
    try:
        from slack_sdk import WebClient
        from slack_sdk.errors import SlackApiError
    except ImportError as ex:
        log.error("slack_sdk is not installed", exc_info=ex)
        return err(f"Failed to send Slack message: {ex}")
    try:
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
        return ok(ts)
    except (SlackApiError, OSError, RuntimeError) as ex:
        log.error("Failed to send Slack message", exc_info=ex)
        return err(f"Failed to send Slack message: {ex}")


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
        files: list[dict] = result.get("files", [])
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
) -> SlackResponse:
    from slack_sdk.errors import SlackApiError

    try:
        return client.files_upload_v2(
            file_uploads=file_uploads,
            channel=channel,
            initial_comment=initial_comment,
            thread_ts=thread_ts,
        )
    except SlackApiError as ex:
        if ex.response.get("error") == "not_in_channel":
            try:
                print("Bot not in channel, joining…", file=sys.stderr)
                client.conversations_join(channel=channel)
                return client.files_upload_v2(
                    file_uploads=file_uploads,
                    channel=channel,
                    initial_comment=initial_comment,
                    thread_ts=thread_ts,
                )
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
            f"{_config_path()} or SLACK_SELF_USER_ID env var.",
            file=sys.stderr,
        )
        return None
    try:
        from slack_sdk import WebClient

        token = get_token()
        client = WebClient(token=token)
        dm = client.conversations_open(users=self_user_id)
        channel = dm["channel"]["id"]
        result = send_slack_message(channel=channel, message=message)
        if isinstance(result, ErrorResult):
            print(f"❌ Failed to send reminder: {result.error}", file=sys.stderr)
            return None
        return result.value
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
