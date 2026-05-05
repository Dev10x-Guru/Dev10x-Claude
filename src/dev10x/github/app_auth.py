"""GitHub App authentication for posting agent-generated content.

Loads an opt-in App configuration from
``~/.claude/Dev10x/github-app.yaml`` and mints short-lived
installation tokens for the configured repository. The tokens are
cached per-repo until shortly before their expiry.

When configuration is absent, malformed, or the token exchange
fails, ``get_bot_token`` returns ``None`` so callers can fall back
to the engineer's ``gh auth`` token without raising.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml

from dev10x.subprocess_utils import async_run

DEFAULT_CONFIG_PATH = Path.home() / ".claude" / "Dev10x" / "github-bot" / "github-app.yaml"


@dataclass(frozen=True)
class AppConfig:
    app_id: str
    private_key_path: Path
    installation_id: str | None = None

    @classmethod
    def load(cls, *, path: Path | None = None) -> AppConfig | None:
        config_path = path or DEFAULT_CONFIG_PATH
        if not config_path.is_file():
            return None
        try:
            data = yaml.safe_load(config_path.read_text()) or {}
        except (OSError, yaml.YAMLError):
            return None
        block = data.get("github_app") or {}
        if not block.get("enabled", True):
            return None
        app_id = block.get("app_id")
        key_path = block.get("private_key_path")
        if not app_id or not key_path:
            return None
        installation_raw = block.get("installation_id")
        return cls(
            app_id=str(app_id),
            private_key_path=Path(str(key_path)).expanduser(),
            installation_id=str(installation_raw) if installation_raw else None,
        )


@dataclass
class _CachedToken:
    token: str
    expires_at: float


_TOKEN_CACHE: dict[str, _CachedToken] = {}


def _clear_cache() -> None:
    _TOKEN_CACHE.clear()


def _create_app_jwt(*, app_id: str, private_key: str) -> str:
    import jwt

    now = int(time.time())
    payload = {"iat": now - 30, "exp": now + 540, "iss": app_id}
    return jwt.encode(payload, private_key, algorithm="RS256")


def _parse_expires_at(raw: str | None) -> float:
    if not raw:
        return time.time() + 3600
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return time.time() + 3600


async def _resolve_installation_id(
    *,
    repo: str,
    app_jwt: str,
) -> str | None:
    result = await async_run(
        args=[
            "gh",
            "api",
            "-H",
            "Accept: application/vnd.github+json",
            f"/repos/{repo}/installation",
        ],
        env={**os.environ, "GH_TOKEN": app_jwt, "GITHUB_TOKEN": app_jwt},
    )
    if result.returncode != 0:
        return None
    try:
        return str(json.loads(result.stdout)["id"])
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


async def _exchange_for_installation_token(
    *,
    installation_id: str,
    app_jwt: str,
) -> tuple[str, float] | None:
    result = await async_run(
        args=[
            "gh",
            "api",
            "-X",
            "POST",
            f"/app/installations/{installation_id}/access_tokens",
        ],
        env={**os.environ, "GH_TOKEN": app_jwt, "GITHUB_TOKEN": app_jwt},
    )
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    token = data.get("token")
    if not token:
        return None
    return token, _parse_expires_at(data.get("expires_at"))


async def get_bot_token(
    *,
    repo: str,
    config: AppConfig | None = None,
) -> str | None:
    """Return an installation token for ``repo``, or ``None`` on failure.

    Callers should treat ``None`` as a signal to fall back to the
    engineer's existing ``gh auth`` credentials.
    """
    cached = _TOKEN_CACHE.get(repo)
    if cached is not None:
        if cached.expires_at - 60 > time.time():
            return cached.token
        _TOKEN_CACHE.pop(repo, None)

    cfg = config if config is not None else AppConfig.load()
    if cfg is None:
        return None

    try:
        private_key = cfg.private_key_path.read_text()
    except OSError:
        return None

    try:
        app_jwt = _create_app_jwt(app_id=cfg.app_id, private_key=private_key)
    except Exception:
        return None

    installation_id = cfg.installation_id or await _resolve_installation_id(
        repo=repo,
        app_jwt=app_jwt,
    )
    if installation_id is None:
        return None

    exchanged = await _exchange_for_installation_token(
        installation_id=installation_id,
        app_jwt=app_jwt,
    )
    if exchanged is None:
        return None

    token, expires_at = exchanged
    _TOKEN_CACHE[repo] = _CachedToken(token=token, expires_at=expires_at)
    return token
