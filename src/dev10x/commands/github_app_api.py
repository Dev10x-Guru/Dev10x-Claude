"""GitHub API helpers for the App setup wizard.

Wraps the endpoints needed to verify an App identity end-to-end:

- ``GET /app`` — the key ↔ App ID match check
- ``GET /app/installations`` — proves the App is installed somewhere
- ``POST /app/installations/{id}/access_tokens`` — token exchange
- ``GET /installation/repositories`` — installation can list repos
- ``GET /repos/{owner}/{repo}`` — installation token can read a repo

Uses stdlib ``urllib.request`` plus the existing ``PyJWT`` dependency.
No extra runtime dependencies.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

API_ROOT = "https://api.github.com"
_USER_AGENT = "dev10x-github-app-setup"
_REQUEST_TIMEOUT_SECONDS = 15


class GitHubAPIError(Exception):
    """Raised when a GitHub API call fails."""


def mint_app_jwt(*, app_id: str, private_key: str) -> str:
    """Mint a short-lived App-level JWT for the GitHub API."""
    import jwt

    now = int(time.time())
    token = jwt.encode(
        {"iat": now - 60, "exp": now + 300, "iss": app_id},
        private_key,
        algorithm="RS256",
    )
    return token if isinstance(token, str) else token.decode()


def _bearer_headers(value: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {value}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": _USER_AGENT,
    }


def _request(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    body: dict[str, Any] | None = None,
) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url=url, method=method, headers=headers, data=data)
    try:
        with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT_SECONDS) as resp:
            payload = resp.read().decode()
            return json.loads(payload) if payload else None
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode(errors="replace")
        except Exception:  # noqa: BLE001 — best-effort detail extraction
            detail = ""
        raise GitHubAPIError(
            f"{method} {url} → {exc.code} {exc.reason}: {detail}".strip()
        ) from exc
    except urllib.error.URLError as exc:
        raise GitHubAPIError(f"{method} {url} failed: {exc.reason}") from exc


def get_app(*, jwt_token: str) -> dict[str, Any]:
    """Return the authenticated App's metadata (id, slug, owner, ...)."""
    return _request("GET", f"{API_ROOT}/app", headers=_bearer_headers(jwt_token))


def list_installations(*, jwt_token: str) -> list[dict[str, Any]]:
    """Return all installations of the authenticated App."""
    return _request(
        "GET",
        f"{API_ROOT}/app/installations",
        headers=_bearer_headers(jwt_token),
    )


def create_installation_token(*, jwt_token: str, installation_id: int) -> str:
    """Exchange the App JWT for a short-lived installation access token."""
    result = _request(
        "POST",
        f"{API_ROOT}/app/installations/{installation_id}/access_tokens",
        headers=_bearer_headers(jwt_token),
        body={},
    )
    return result["token"]


def list_installation_repositories(*, token: str) -> list[dict[str, Any]]:
    """List repos the current installation can access."""
    result = _request(
        "GET",
        f"{API_ROOT}/installation/repositories",
        headers=_bearer_headers(token),
    )
    return result.get("repositories", []) if isinstance(result, dict) else []


def get_repo(*, token: str, owner: str, repo: str) -> dict[str, Any]:
    """Read a single repo via installation token."""
    return _request(
        "GET",
        f"{API_ROOT}/repos/{owner}/{repo}",
        headers=_bearer_headers(token),
    )
