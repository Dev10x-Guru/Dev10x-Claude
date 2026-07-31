"""Importable Slack notification helpers (GH-442).

Extracted from ``skills/slack/slack-notify.py`` so the logic is available
when dev10x is installed via ``uvx`` — where the ``skills/`` data files are
not part of the wheel and cannot be located via filesystem traversal.

The standalone ``skills/slack/slack-notify.py`` uv-script remains the entry
point for direct plugin-checkout invocations; this module powers the
``dev10x skill notify slack-send`` CLI command and any in-process callers.

``slack_sdk`` is an optional fast path (GH-917). The in-process callers —
notably the MCP server behind ``pr_notify`` — do not always run in an
environment where the declared dependency was actually installed, so every
message path falls back to :func:`call_slack_api`, a stdlib ``urllib`` POST to
the Slack Web API. File uploads are the sole SDK-only path.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dev10x import subprocess_utils
from dev10x.domain.common.result import ErrorResult, Result, err, ok
from dev10x.domain.dev10x_paths import Dev10xConfigDir

if TYPE_CHECKING:
    from slack_sdk import WebClient
    from slack_sdk.web import SlackResponse

log = logging.getLogger(__name__)

SLACK_API_BASE = "https://slack.com/api"
_HTTP_TIMEOUT_SECONDS = 30

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
        result = subprocess_utils.run(cmd, capture_output=True, text=True, check=True)
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


def get_token() -> Result[str]:
    """Resolve the Slack bot token (GH-587).

    Returns a :class:`Result` instead of raising so callers share one
    Result-based error style rather than mixing ``raise RuntimeError``
    with ``Result`` returns.

    Resolution order:
      1. If --workspace was set: keyring at the workspace's service name.
         Error if missing — workspace was explicitly requested.
      2. SLACK_TOKEN environment variable.
      3. Default keyring at service=slack.
    """
    if _active_workspace is not None:
        service = _keyring_service()
        token = _keyring_lookup(service=service, key="bot_token")
        if token:
            return ok(token)
        return err(
            f"No Slack token found in keyring for workspace "
            f"'{_active_workspace}' (service={service})"
        )
    env_token = os.environ.get("SLACK_TOKEN")
    if env_token:
        return ok(env_token)
    token = _keyring_lookup(service="slack", key="bot_token")
    if token:
        return ok(token)
    return err(
        "No Slack token found. Set SLACK_TOKEN env, configure the default "
        "keyring (service=slack, key=bot_token), or pass --workspace NAME."
    )


def sdk_client(*, token: str) -> WebClient | None:
    """Build a ``slack_sdk`` client, or ``None`` when the SDK is absent (GH-917).

    The MCP server and other in-process callers do not always run in an
    environment where the declared ``slack-sdk`` dependency was installed, so
    every send path treats the SDK as an optional fast path and falls back to
    :func:`call_slack_api`. This function is the injection seam tests use to
    exercise the dependency-free transport.
    """
    try:
        from slack_sdk import WebClient
    except ImportError:
        log.info("slack_sdk unavailable — using the stdlib HTTP Slack transport")
        return None
    return WebClient(token=token)


def call_slack_api(
    *,
    method: str,
    payload: dict[str, Any],
    token: str,
) -> Result[dict[str, Any]]:
    """POST a JSON payload to a Slack Web API method using only the stdlib.

    Keys whose value is ``None`` are dropped so the payload matches what the
    ``slack_sdk`` client would have sent. A Slack-level rejection
    (``{"ok": false}``) is returned as an :class:`ErrorResult` carrying
    Slack's own error code.
    """
    body = {key: value for key, value in payload.items() if value is not None}
    request = urllib.request.Request(
        f"{SLACK_API_BASE}/{method}",
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(  # noqa: S310 - fixed https Slack API host
            request,
            timeout=_HTTP_TIMEOUT_SECONDS,
        ) as response:
            parsed = json.loads(response.read().decode())
    except urllib.error.HTTPError as ex:
        detail = ex.read().decode(errors="replace")
        return err(f"Slack {method} failed (HTTP {ex.code}): {detail}")
    except urllib.error.URLError as ex:
        return err(f"Slack API unreachable: {ex.reason}")
    except json.JSONDecodeError as ex:
        return err(f"Slack {method} returned a non-JSON response: {ex}")
    if not parsed.get("ok"):
        return err(f"Slack {method} rejected the request: {parsed.get('error', 'unknown_error')}")
    return ok(parsed)


def _http_call(
    *,
    method: str,
    payload: dict[str, Any],
    token: str,
    failure_label: str,
) -> Result[dict[str, Any]]:
    """Call the Slack API over HTTP, logging and labelling any failure."""
    result = call_slack_api(method=method, payload=payload, token=token)
    if isinstance(result, ErrorResult):
        log.error("%s: %s", failure_label, result.error)
        return err(f"{failure_label}: {result.error}")
    return result


def _send_over_http(
    *,
    channel: str,
    resolved_message: str,
    token: str,
    thread_ts: str | None,
    broadcast: bool,
    reactions: list[str] | None,
    unfurl: bool,
) -> Result[str]:
    """Post a message (and its reactions) without the ``slack_sdk`` dependency."""
    is_user_token = token.startswith("xoxp-")
    posted = _http_call(
        method="chat.postMessage",
        payload={
            "channel": channel,
            "text": resolved_message,
            "username": None if is_user_token else _bot_username(),
            "thread_ts": thread_ts,
            "reply_broadcast": broadcast if thread_ts else None,
            "unfurl_links": unfurl,
            "unfurl_media": unfurl,
        },
        token=token,
        failure_label="Failed to send Slack message",
    )
    if isinstance(posted, ErrorResult):
        return posted
    ts = posted.value["ts"]
    for emoji in reactions or []:
        reacted = _http_call(
            method="reactions.add",
            payload={"channel": channel, "timestamp": ts, "name": emoji},
            token=token,
            failure_label="Failed to add Slack reaction",
        )
        if isinstance(reacted, ErrorResult):
            return reacted
    return ok(ts)


def send_slack_message(
    channel: str,
    message: str,
    thread_ts: str | None = None,
    broadcast: bool = False,
    reactions: list[str] | None = None,
    unfurl: bool = False,
) -> Result[str]:
    resolved_message = resolve_mentions(message)
    token_result = get_token()
    if isinstance(token_result, ErrorResult):
        log.error("Failed to send Slack message: %s", token_result.error)
        return token_result
    token = token_result.value
    client = sdk_client(token=token)
    if client is None:
        return _send_over_http(
            channel=channel,
            resolved_message=resolved_message,
            token=token,
            thread_ts=thread_ts,
            broadcast=broadcast,
            reactions=reactions,
            unfurl=unfurl,
        )
    from slack_sdk.errors import SlackApiError

    try:
        is_user_token = token.startswith("xoxp-")
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


def notify_slack(
    *,
    channel: str,
    message: str,
    workspace: str | None = None,
    thread_ts: str | None = None,
    broadcast: bool = False,
    reactions: list[str] | None = None,
    unfurl: bool = False,
) -> Result[str]:
    """Single service entry for sending a Slack message (GH-587).

    Consolidates the previously-scattered ``set_workspace`` +
    ``send_slack_message`` call sites behind one ``Result``-returning
    service so every caller shares the same error contract instead of
    three divergent styles. Returns ``ok(ts)`` or ``err(reason)``;
    callers own their own user-facing output formatting.
    """
    if workspace is not None:
        set_workspace(workspace)
    return send_slack_message(
        channel=channel,
        message=message,
        thread_ts=thread_ts,
        broadcast=broadcast,
        reactions=reactions,
        unfurl=unfurl,
    )


def upload_slack_files(
    channel: str,
    file_paths: list[str],
    message: str | None = None,
    thread_ts: str | None = None,
) -> Result[str | None]:
    """Upload files to a channel, returning the first file id (GH-533).

    Returns a :class:`Result` instead of printing and returning ``None`` so
    the importable module shares one error contract with the rest of the
    package; the caller owns any user-facing output (script-domain-boundaries
    H3). On success the value is the first uploaded file id, or ``None`` when
    Slack returns no file metadata.

    This is the one path that still requires ``slack_sdk``: the upload flow is
    a three-call multipart handshake, not a single JSON POST, so the GH-917
    stdlib fallback does not cover it. Without the SDK the caller gets an
    actionable error instead of an ``ImportError`` traceback.
    """
    token_result = get_token()
    if isinstance(token_result, ErrorResult):
        return token_result
    token = token_result.value
    client = sdk_client(token=token)
    if client is None:
        return err(
            "Slack file uploads need the optional slack_sdk package "
            "(the stdlib HTTP fallback covers messages only). "
            "Install it with: uv pip install slack-sdk"
        )
    from slack_sdk.errors import SlackApiError

    resolved_message = resolve_mentions(message) if message else None

    file_uploads = []
    for path in file_paths:
        if not os.path.exists(path):
            return err(f"File not found: {path}")
        file_uploads.append({"file": path, "title": os.path.basename(path)})

    try:
        result = _files_upload_v2(
            client=client,
            file_uploads=file_uploads,
            channel=channel,
            initial_comment=resolved_message,
            thread_ts=thread_ts,
        )
    except SlackApiError as ex:
        error = ex.response.get("error")
        if error == "missing_scope":
            needed = ex.response.get("needed", "files:write")
            return err(
                f"Bot token missing '{needed}' scope. "
                f"Add it at https://api.slack.com/apps → OAuth & Permissions."
            )
        if error == "not_in_channel":
            return err(
                f"Bot is not a member of channel {channel} and cannot auto-join. "
                f"Invite the bot via channel settings → Integrations."
            )
        log.error("Failed to upload Slack file(s)", exc_info=ex)
        return err(f"Failed to upload Slack file(s): {ex}")

    files: list[dict] = result.get("files", [])
    file_id = files[0].get("id") if files else None
    log.info("Uploaded %d file(s): %s", len(file_uploads), [f.get("id") for f in files])
    return ok(file_id)


def _files_upload_v2(
    client: WebClient,
    file_uploads: list[dict],
    channel: str,
    initial_comment: str | None,
    thread_ts: str | None,
) -> SlackResponse:
    """Upload files, auto-joining the channel once on ``not_in_channel``.

    Raises :class:`SlackApiError` on failure — including a failed auto-join —
    so the caller maps it to a descriptive :class:`Result` error rather than
    exiting the process (GH-533).
    """
    from slack_sdk.errors import SlackApiError

    try:
        return client.files_upload_v2(
            file_uploads=file_uploads,
            channel=channel,
            initial_comment=initial_comment,
            thread_ts=thread_ts,
        )
    except SlackApiError as ex:
        if ex.response.get("error") != "not_in_channel":
            raise
        log.info("Bot not in channel %s, joining…", channel)
        client.conversations_join(channel=channel)
        return client.files_upload_v2(
            file_uploads=file_uploads,
            channel=channel,
            initial_comment=initial_comment,
            thread_ts=thread_ts,
        )


def send_reminder(message: str) -> Result[str]:
    """Send a reminder DM to the configured self user (GH-533).

    Returns ``ok(ts)`` with the posted message timestamp, or ``err(...)``
    when the self user is unconfigured, the token is missing, or the Slack
    API rejects the DM. Programmer errors (e.g. a malformed API response)
    propagate, mirroring :func:`send_slack_message` (GH-537).
    """
    self_user_id = _self_user_id()
    if not self_user_id:
        return err(
            f"self_user_id not configured. Set it in {_config_path()} "
            f"or the SLACK_SELF_USER_ID env var."
        )
    token_result = get_token()
    if isinstance(token_result, ErrorResult):
        return token_result
    token = token_result.value
    client = sdk_client(token=token)
    if client is None:
        opened = _http_call(
            method="conversations.open",
            payload={"users": self_user_id},
            token=token,
            failure_label="Failed to send reminder",
        )
        if isinstance(opened, ErrorResult):
            return opened
        return send_slack_message(channel=opened.value["channel"]["id"], message=message)
    from slack_sdk.errors import SlackApiError

    try:
        dm = client.conversations_open(users=self_user_id)
        channel = dm["channel"]["id"]
    except (SlackApiError, OSError) as ex:
        log.error("Failed to open reminder DM", exc_info=ex)
        return err(f"Failed to send reminder: {ex}")
    return send_slack_message(channel=channel, message=message)


def update_slack_message(channel: str, ts: str, message: str) -> Result[None]:
    """Edit an existing message (GH-533). Returns ``ok(None)`` on success."""
    resolved_message = resolve_mentions(message)
    token_result = get_token()
    if isinstance(token_result, ErrorResult):
        return token_result
    token = token_result.value
    client = sdk_client(token=token)
    if client is None:
        updated = _http_call(
            method="chat.update",
            payload={"channel": channel, "ts": ts, "text": resolved_message},
            token=token,
            failure_label="Failed to update Slack message",
        )
        return updated if isinstance(updated, ErrorResult) else ok(None)
    from slack_sdk.errors import SlackApiError

    try:
        client.chat_update(channel=channel, ts=ts, text=resolved_message)
    except (SlackApiError, OSError) as ex:
        log.error("Failed to update Slack message", exc_info=ex)
        return err(f"Failed to update Slack message: {ex}")
    return ok(None)


def delete_slack_message(channel: str, ts: str) -> Result[None]:
    """Delete a message (GH-533). Returns ``ok(None)`` on success."""
    token_result = get_token()
    if isinstance(token_result, ErrorResult):
        return token_result
    token = token_result.value
    client = sdk_client(token=token)
    if client is None:
        deleted = _http_call(
            method="chat.delete",
            payload={"channel": channel, "ts": ts},
            token=token,
            failure_label="Failed to delete Slack message",
        )
        return deleted if isinstance(deleted, ErrorResult) else ok(None)
    from slack_sdk.errors import SlackApiError

    try:
        client.chat_delete(channel=channel, ts=ts)
    except (SlackApiError, OSError) as ex:
        log.error("Failed to delete Slack message", exc_info=ex)
        return err(f"Failed to delete Slack message: {ex}")
    return ok(None)


def delete_slack_file(file_id: str) -> Result[None]:
    """Delete a file (GH-533). Returns ``ok(None)`` on success."""
    token_result = get_token()
    if isinstance(token_result, ErrorResult):
        return token_result
    token = token_result.value
    client = sdk_client(token=token)
    if client is None:
        deleted = _http_call(
            method="files.delete",
            payload={"file": file_id},
            token=token,
            failure_label="Failed to delete Slack file",
        )
        return deleted if isinstance(deleted, ErrorResult) else ok(None)
    from slack_sdk.errors import SlackApiError

    try:
        client.files_delete(file=file_id)
    except (SlackApiError, OSError) as ex:
        log.error("Failed to delete Slack file", exc_info=ex)
        return err(f"Failed to delete Slack file: {ex}")
    return ok(None)
