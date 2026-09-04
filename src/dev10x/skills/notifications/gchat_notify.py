"""Importable Google Chat notification helpers (mirrors slack_notify.py).

Powers the `dev10x skill notify gchat-send` CLI command and any in-process
callers. Posts through a private Chat bot authenticated with a service
account (app auth) against the Chat REST API. Two auth methods:

- ``sa_key`` (default): the SA-key JSON is read from the OS keyring and a
  token is minted by signing a JWT with pyjwt.
- ``impersonate``: keyless — gcloud Application Default Credentials
  (user identity) impersonate the service account via the IAM Credentials
  API, for orgs that enforce iam.disableServiceAccountKeyCreation.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from dev10x import subprocess_utils
from dev10x.domain.common.result import ErrorResult, Result, err, ok
from dev10x.domain.dev10x_paths import Dev10xConfigDir
from dev10x.skills.notifications import gchat_cards

log = logging.getLogger(__name__)

GCHAT_SCOPE = "https://www.googleapis.com/auth/chat.bot"
TOKEN_URI = "https://oauth2.googleapis.com/token"
CHAT_API_BASE = "https://chat.googleapis.com/v1"
IAM_CREDENTIALS_BASE = "https://iamcredentials.googleapis.com/v1"
_JWT_GRANT = "urn:ietf:params:oauth:grant-type:jwt-bearer"
REPLY_FALLBACK_OPTION = "REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD"

_config: dict | None = None


def _config_path() -> Path:
    return Dev10xConfigDir.gchat_config_yaml()


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


def resolve_space_id(alias: str) -> Result[str]:
    spaces = _get_config().get("spaces", {}) or {}
    entry = spaces.get(alias)
    if not entry or not entry.get("space_id"):
        return err(
            f"No Google Chat space configured for alias '{alias}'. "
            f"Add it under spaces: in {_config_path()}."
        )
    return ok(entry["space_id"])


def _user_groups() -> dict[str, str]:
    return _get_config().get("user_groups", {}) or {}


def resolve_mentions(message: str) -> str:
    for mention, token in _user_groups().items():
        message = message.replace(mention, token)
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


def get_sa_info() -> Result[dict]:
    """Read and parse the service-account key JSON from the keyring."""
    raw = _keyring_lookup(service="gchat", key="sa_key")
    if not raw:
        return err(
            "No Google Chat service-account key found. Store it with: "
            'secret-tool store --label="GChat SA key" service gchat key sa_key'
        )
    try:
        return ok(json.loads(raw))
    except json.JSONDecodeError as ex:
        return err(f"Google Chat service-account key is not valid JSON: {ex}")


def _post_form(url: str, fields: dict[str, str]) -> Result[dict]:
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            return ok(json.loads(resp.read().decode()))
    except urllib.error.HTTPError as ex:
        detail = ex.read().decode(errors="replace")
        return err(f"HTTP {ex.code}: {detail}")
    except urllib.error.URLError as ex:
        return err(f"Token endpoint unreachable: {ex.reason}")


def mint_access_token(sa_info: dict, *, now: int | None = None) -> Result[str]:
    """Sign a JWT with the SA key and exchange it for an access token."""
    import jwt

    iat = now if now is not None else int(time.time())
    try:
        claims = {
            "iss": sa_info["client_email"],
            "scope": GCHAT_SCOPE,
            "aud": TOKEN_URI,
            "iat": iat,
            "exp": iat + 3600,
        }
        assertion = jwt.encode(claims, sa_info["private_key"], algorithm="RS256")
    except KeyError as ex:
        return err(
            "Google Chat service-account key is missing client_email/private_key "
            f"or is unusable for signing: {ex}"
        )
    except Exception as ex:  # noqa: BLE001 - jwt/cryptography can raise many types
        return err(
            "Google Chat service-account key is missing client_email/private_key "
            f"or is unusable for signing: {ex}"
        )
    form_result = _post_form(TOKEN_URI, {"grant_type": _JWT_GRANT, "assertion": assertion})
    if isinstance(form_result, ErrorResult):
        return form_result
    token = form_result.value.get("access_token")
    if not token:
        return err("Token endpoint returned no access_token")
    return ok(token)


def _auth_config() -> dict:
    return _get_config().get("auth", {}) or {}


def _adc_path() -> Path:
    env_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if env_path:
        return Path(env_path)
    return Path.home() / ".config" / "gcloud" / "application_default_credentials.json"


def get_adc_info() -> Result[dict]:
    """Read and parse gcloud Application Default Credentials."""
    path = _adc_path()
    if not path.exists():
        return err(
            f"No Application Default Credentials found at {path}. "
            "Run: gcloud auth application-default login"
        )
    try:
        return ok(json.loads(path.read_text()))
    except json.JSONDecodeError as ex:
        return err(f"Application Default Credentials file is not valid JSON: {ex}")


def mint_user_token(adc_info: dict) -> Result[str]:
    """Exchange the ADC refresh token for a user access token."""
    if adc_info.get("type") != "authorized_user":
        return err(
            "Application Default Credentials are not user credentials "
            f"(type={adc_info.get('type')!r}). Run: gcloud auth application-default login"
        )
    try:
        fields = {
            "grant_type": "refresh_token",
            "client_id": adc_info["client_id"],
            "client_secret": adc_info["client_secret"],
            "refresh_token": adc_info["refresh_token"],
        }
    except KeyError as ex:
        return err(f"Application Default Credentials are missing {ex}")
    form_result = _post_form(TOKEN_URI, fields)
    if isinstance(form_result, ErrorResult):
        return form_result
    token = form_result.value.get("access_token")
    if not token:
        return err("Token endpoint returned no access_token")
    return ok(token)


def mint_impersonated_token(*, service_account: str, user_token: str) -> Result[str]:
    """Mint a short-lived chat.bot token for the SA via IAM Credentials impersonation.

    Keyless alternative to a downloaded SA key for orgs that enforce
    iam.disableServiceAccountKeyCreation. The calling user needs
    roles/iam.serviceAccountTokenCreator on the service account.
    """
    url = (
        f"{IAM_CREDENTIALS_BASE}/projects/-/serviceAccounts/{service_account}:generateAccessToken"
    )
    payload = {"scope": [GCHAT_SCOPE], "lifetime": "3600s"}
    result = _post_json(
        url, payload, user_token, error_label="Service-account impersonation failed"
    )
    if isinstance(result, ErrorResult):
        return result
    token = result.value.get("accessToken")
    if not token:
        return err("IAM Credentials returned no accessToken")
    return ok(token)


def mint_chat_token() -> Result[str]:
    """Mint a chat.bot access token using the auth method configured in gchat-config.yaml."""
    auth = _auth_config()
    method = auth.get("method", "sa_key")
    if method == "impersonate":
        service_account = auth.get("service_account")
        if not service_account:
            return err(
                "auth.method is 'impersonate' but auth.service_account is not set "
                f"in {_config_path()}."
            )
        adc_result = get_adc_info()
        if isinstance(adc_result, ErrorResult):
            return adc_result
        user_result = mint_user_token(adc_result.value)
        if isinstance(user_result, ErrorResult):
            return user_result
        return mint_impersonated_token(
            service_account=service_account, user_token=user_result.value
        )
    if method != "sa_key":
        return err(
            f"Unknown gchat auth.method {method!r} in {_config_path()} "
            "(expected 'sa_key' or 'impersonate')."
        )
    sa_result = get_sa_info()
    if isinstance(sa_result, ErrorResult):
        return sa_result
    return mint_access_token(sa_result.value)


def _request_json(
    url: str,
    *,
    token: str,
    payload: dict | None = None,
    method: str = "POST",
    error_label: str = "Google Chat request failed",
    status_notes: dict[int, str] | None = None,
) -> Result[dict]:
    """Issue one Chat API call.

    ``status_notes`` appends an explanation for a specific HTTP status.
    The status is only reliably known here — re-deriving it downstream by
    matching on the formatted message would also match a code quoted
    inside the API's own response body.
    """
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Authorization": f"Bearer {token}"}
    if data is not None:
        headers["Content-Type"] = "application/json; charset=UTF-8"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            # A successful DELETE answers 200 with an empty body, which
            # json.loads would reject.
            body = resp.read().decode()
            return ok(json.loads(body) if body.strip() else {})
    except urllib.error.HTTPError as ex:
        detail = ex.read().decode(errors="replace")
        message = f"{error_label} (HTTP {ex.code}): {detail}"
        note = (status_notes or {}).get(ex.code)
        return err(f"{message}\n{note}" if note else message)
    except urllib.error.URLError as ex:
        return err(f"{urllib.parse.urlsplit(url).netloc} unreachable: {ex.reason}")


def _post_json(
    url: str,
    payload: dict,
    token: str,
    *,
    error_label: str = "Google Chat POST failed",
) -> Result[dict]:
    return _request_json(url, token=token, payload=payload, method="POST", error_label=error_label)


def build_message_payload(
    *,
    text: str | None = None,
    cards: list[dict] | None = None,
    fallback_text: str | None = None,
    thread: str | None = None,
) -> Result[dict]:
    """Assemble the Chat ``messages.create`` body (GH-1113, GH-1203).

    ``text`` and ``cards`` are independent: a message may carry either or
    both. Sending both is the norm for a notification, because a card
    renders rich formatting but does NOT resolve ``<users/ID>`` mentions —
    only ``text`` notifies the people named in it.

    ``thread`` is the full ``spaces/<space>/threads/<id>`` resource name of
    the thread to reply into; omitting it starts a new thread as before.
    """
    if not text and not cards:
        return err("A Google Chat message needs text, cards, or both.")
    payload: dict = {}
    if text:
        payload["text"] = text
    if cards:
        payload["cardsV2"] = cards
        # Without fallbackText a card reads as blank in mobile notifications,
        # so derive one from the text half. An empty string would be no
        # better than the omission it replaces — leave the key out instead.
        fallback = fallback_text or gchat_cards.plain_text_fallback(text or "")
        if fallback:
            payload["fallbackText"] = fallback
    if thread:
        payload["thread"] = {"name": thread}
    return ok(payload)


def qualify_thread_name(thread: str, *, space_id: str) -> str:
    """Accept either a full thread resource name or the bare id from a Chat URL.

    A `chat.google.com/room/<space>/<thread>/<message>` link is where a user
    copies a thread id from, and that segment carries no `spaces/` prefix.
    """
    return thread if thread.startswith("spaces/") else f"spaces/{space_id}/threads/{thread}"


def post_message(
    *,
    space_id: str,
    token: str,
    text: str | None = None,
    cards: list[dict] | None = None,
    fallback_text: str | None = None,
    thread: str | None = None,
) -> Result[str]:
    qualified_thread = qualify_thread_name(thread, space_id=space_id) if thread else None
    payload_result = build_message_payload(
        text=text, cards=cards, fallback_text=fallback_text, thread=qualified_thread
    )
    if isinstance(payload_result, ErrorResult):
        return payload_result
    url = f"{CHAT_API_BASE}/spaces/{space_id}/messages"
    if qualified_thread:
        # FALLBACK_TO_NEW_THREAD degrades safely: a stale or wrong thread
        # name posts a new thread rather than failing the send.
        url = f"{url}?messageReplyOption={REPLY_FALLBACK_OPTION}"
    result = _post_json(url, payload_result.value, token)
    if isinstance(result, ErrorResult):
        return result
    name = result.value.get("name")
    if not name:
        return err(f"Google Chat accepted the POST but returned no message name: {result.value}")
    return ok(name)


def _validate_message_name(message_name: str) -> Result[str]:
    parts = message_name.split("/")
    if len(parts) != 4 or parts[0] != "spaces" or parts[2] != "messages":
        return err(
            f"{message_name!r} is not a Google Chat message name. "
            "Expected the full 'spaces/<space>/messages/<id>' resource name, "
            "which `gchat-send` prints on a successful post."
        )
    return ok(message_name)


# Under app auth the bot can only modify or delete messages it posted
# itself, and the raw 403 body does not say so.
_OWN_MESSAGE_NOTE = {
    403: (
        "Under app auth the bot can only modify or delete its own messages. "
        "A message posted by a person cannot be edited or deleted here."
    )
}

# spaces.messages.patch accepts a CLOSED set of updateMask field paths, in
# snake_case: text, attachment, cards, cards_v2, accessory_widgets. Our
# payload keys are the resource's JSON names, which differ — `cardsV2` is
# not accepted, and `fallbackText` is not updatable at all, so it rides in
# the body (where it is ignored) but never in the mask.
#
# [Verify] Taken from the Chat API's documented field-path list, not
# exercised against a live space in the session that wrote it.
_UPDATE_MASK_PATHS = {"text": "text", "cardsV2": "cards_v2"}


def patch_message(
    *,
    message_name: str,
    token: str,
    text: str | None = None,
    cards: list[dict] | None = None,
    fallback_text: str | None = None,
) -> Result[str]:
    name_result = _validate_message_name(message_name)
    if isinstance(name_result, ErrorResult):
        return name_result
    payload_result = build_message_payload(text=text, cards=cards, fallback_text=fallback_text)
    if isinstance(payload_result, ErrorResult):
        return payload_result
    payload = payload_result.value
    # Only the fields actually supplied are masked, so updating the text of a
    # card message does not blank the card (and vice versa). The payload
    # always carries text or cardsV2 — build_message_payload rejects a body
    # with neither — so the mask is never empty.
    update_mask = ",".join(path for key, path in _UPDATE_MASK_PATHS.items() if key in payload)
    url = f"{CHAT_API_BASE}/{message_name}?updateMask={urllib.parse.quote(update_mask)}"
    result = _request_json(
        url,
        token=token,
        payload=payload,
        method="PATCH",
        error_label="Google Chat message update failed",
        status_notes=_OWN_MESSAGE_NOTE,
    )
    if isinstance(result, ErrorResult):
        return result
    return ok(result.value.get("name") or message_name)


def delete_message(*, message_name: str, token: str) -> Result[str]:
    name_result = _validate_message_name(message_name)
    if isinstance(name_result, ErrorResult):
        return name_result
    url = f"{CHAT_API_BASE}/{message_name}"
    result = _request_json(
        url,
        token=token,
        method="DELETE",
        error_label="Google Chat message delete failed",
        status_notes=_OWN_MESSAGE_NOTE,
    )
    if isinstance(result, ErrorResult):
        return result
    return ok(message_name)


def send_gchat_message(
    *,
    space: str,
    message: str | None = None,
    cards: list[dict] | None = None,
    fallback_text: str | None = None,
    thread: str | None = None,
) -> Result[str]:
    space_result = resolve_space_id(space)
    if isinstance(space_result, ErrorResult):
        return space_result
    token_result = mint_chat_token()
    if isinstance(token_result, ErrorResult):
        return token_result
    return post_message(
        space_id=space_result.value,
        token=token_result.value,
        text=resolve_mentions(message) if message else None,
        cards=cards,
        fallback_text=resolve_mentions(fallback_text) if fallback_text else None,
        thread=thread,
    )


def notify_gchat(
    *,
    space: str,
    message: str | None = None,
    cards: list[dict] | None = None,
    fallback_text: str | None = None,
    thread: str | None = None,
) -> Result[str]:
    """Single service entry for sending a Google Chat message.

    Returns ``ok(message_name)`` or ``err(reason)``; callers own their own
    user-facing output formatting (mirrors ``slack_notify.notify_slack``).
    Pass ``cards`` (built with ``gchat_cards``) for a formatted cardsV2
    panel, optionally alongside ``message`` so mentions still notify.
    Pass ``thread`` to reply into an existing thread (GH-1203).
    """
    return send_gchat_message(
        space=space,
        message=message,
        cards=cards,
        fallback_text=fallback_text,
        thread=thread,
    )


def update_gchat_message(
    *,
    message_name: str,
    message: str | None = None,
    cards: list[dict] | None = None,
    fallback_text: str | None = None,
) -> Result[str]:
    """Edit a message the bot posted earlier (GH-1207).

    ``message_name`` is the full ``spaces/<space>/messages/<id>`` resource
    name returned by a successful send, so no space alias is needed — the
    space is already part of the name.
    """
    token_result = mint_chat_token()
    if isinstance(token_result, ErrorResult):
        return token_result
    return patch_message(
        message_name=message_name,
        token=token_result.value,
        text=resolve_mentions(message) if message else None,
        cards=cards,
        fallback_text=resolve_mentions(fallback_text) if fallback_text else None,
    )


def delete_gchat_message(*, message_name: str) -> Result[str]:
    """Delete a message the bot posted earlier (GH-1207)."""
    token_result = mint_chat_token()
    if isinstance(token_result, ErrorResult):
        return token_result
    return delete_message(message_name=message_name, token=token_result.value)
