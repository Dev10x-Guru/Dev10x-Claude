"""Importable Google Chat notification helpers (mirrors slack_notify.py).

Powers the `dev10x skill notify gchat-send` CLI command and any in-process
callers. Posts through a private Chat bot authenticated with a service
account (app auth) against the Chat REST API. The SA-key JSON is read from
the OS keyring; an access token is minted with pyjwt + stdlib urllib.
"""

from __future__ import annotations

import json
import logging
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

log = logging.getLogger(__name__)

GCHAT_SCOPE = "https://www.googleapis.com/auth/chat.bot"
TOKEN_URI = "https://oauth2.googleapis.com/token"
CHAT_API_BASE = "https://chat.googleapis.com/v1"
_JWT_GRANT = "urn:ietf:params:oauth:grant-type:jwt-bearer"

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


def _post_json(url: str, payload: dict[str, str], token: str) -> Result[dict]:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json; charset=UTF-8",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            return ok(json.loads(resp.read().decode()))
    except urllib.error.HTTPError as ex:
        detail = ex.read().decode(errors="replace")
        return err(f"Google Chat POST failed (HTTP {ex.code}): {detail}")
    except urllib.error.URLError as ex:
        return err(f"Google Chat unreachable: {ex.reason}")


def post_message(*, space_id: str, text: str, token: str) -> Result[str]:
    url = f"{CHAT_API_BASE}/spaces/{space_id}/messages"
    result = _post_json(url, {"text": text}, token)
    if isinstance(result, ErrorResult):
        return result
    name = result.value.get("name")
    if not name:
        return err(f"Google Chat accepted the POST but returned no message name: {result.value}")
    return ok(name)


def send_gchat_message(*, space: str, message: str) -> Result[str]:
    space_result = resolve_space_id(space)
    if isinstance(space_result, ErrorResult):
        return space_result
    sa_result = get_sa_info()
    if isinstance(sa_result, ErrorResult):
        return sa_result
    token_result = mint_access_token(sa_result.value)
    if isinstance(token_result, ErrorResult):
        return token_result
    resolved = resolve_mentions(message)
    return post_message(space_id=space_result.value, text=resolved, token=token_result.value)


def notify_gchat(*, space: str, message: str) -> Result[str]:
    """Single service entry for sending a Google Chat message.

    Returns ``ok(message_name)`` or ``err(reason)``; callers own their own
    user-facing output formatting (mirrors ``slack_notify.notify_slack``).
    """
    return send_gchat_message(space=space, message=message)
