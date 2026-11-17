"""Plain HTTP GET for the source adapters (GH-1985).

The adapters only read public pages, feeds and audio files, so the
standard library is enough; a third-party client would be one more
dependency for every `uvx dev10x` install.

Feed and enclosure URLs come from third-party JSON and RSS, so every
request is limited to http(s) — before opening and on every redirect,
because urllib would otherwise follow a feed into ``file://`` — and
every read stops at a byte cap instead of trusting the server to end.
"""

from __future__ import annotations

import logging
import urllib.error
import urllib.request
from contextlib import suppress
from http.client import HTTPException
from pathlib import Path
from typing import IO, Any
from urllib.parse import urlparse

from dev10x.core.domain.common.result import Result, err, ok

log = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (compatible; dev10x-kb)"
PAGE_TIMEOUT_SECONDS = 30
DOWNLOAD_TIMEOUT_SECONDS = 600
MAX_PAGE_BYTES = 30 * 1024 * 1024
MAX_DOWNLOAD_BYTES = 2 * 1024 * 1024 * 1024
_CHUNK_BYTES = 1024 * 1024
_ALLOWED_SCHEMES = frozenset({"http", "https"})
# HTTPException (IncompleteRead, RemoteDisconnected) is not an OSError.
_FETCH_ERRORS = (OSError, HTTPException, ValueError)


class UnsafeUrlError(urllib.error.URLError):
    """A URL, or a redirect target, outside http(s)."""


class _HttpOnlyRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        if not is_web_url(url=newurl):
            raise UnsafeUrlError(f"refusing redirect to {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_HttpOnlyRedirects)


def is_web_url(*, url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme.lower() in _ALLOWED_SCHEMES and bool(parsed.netloc)


def _open(*, url: str, timeout: float) -> Any:
    if not is_web_url(url=url):
        raise UnsafeUrlError(f"refusing non-http(s) URL {url}")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    return _OPENER.open(request, timeout=timeout)


def fetch_bytes(
    *,
    url: str,
    timeout: float = PAGE_TIMEOUT_SECONDS,
    max_bytes: int = MAX_PAGE_BYTES,
) -> Result[bytes]:
    try:
        with _open(url=url, timeout=timeout) as response:
            body = response.read(max_bytes + 1)
    except _FETCH_ERRORS as exc:
        log.warning("http get failed", extra={"url": url, "error": str(exc)})
        return err(f"cannot fetch {url}: {exc}. Please try again.")
    if len(body) > max_bytes:
        return err(f"{url} is larger than {max_bytes} bytes; refusing to read it")
    return ok(body)


def _discard(*, path: Path) -> None:
    with suppress(OSError):
        path.unlink(missing_ok=True)


def download(
    *,
    url: str,
    destination: Path,
    timeout: float = DOWNLOAD_TIMEOUT_SECONDS,
    max_bytes: int = MAX_DOWNLOAD_BYTES,
) -> Result[Path]:
    """Stream ``url`` to ``destination``, stopping at ``max_bytes``."""
    written = 0
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with _open(url=url, timeout=timeout) as response, destination.open("wb") as handle:
            while chunk := response.read(_CHUNK_BYTES):
                written += len(chunk)
                if written > max_bytes:
                    break
                handle.write(chunk)
    except _FETCH_ERRORS as exc:
        log.warning("download failed", extra={"url": url, "error": str(exc)})
        _discard(path=destination)
        return err(f"cannot download {url}: {exc}. Please try again.")
    if written > max_bytes:
        _discard(path=destination)
        return err(f"{url} is larger than {max_bytes} bytes; refusing to download it")
    return ok(destination)
