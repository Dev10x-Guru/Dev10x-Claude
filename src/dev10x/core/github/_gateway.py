"""The GitHub Gateway core every capability module calls through (ADR-0027).

**Pattern: Gateway** (Fowler, *PoEAA*; ADR-0013). Every call to the
``gh`` CLI and the GitHub REST/GraphQL APIs is funnelled through
``_gh_api_raw`` / ``async_run`` / ``async_run_script``, giving one place
to inject auth (``as_bot`` bot-token routing), retries and the effective
working directory.

**D2 seam.** Capability modules import this module and call through its
attributes — ``_gateway.async_run(...)``, never a bare ``async_run`` bound
by ``from ... import``. That keeps exactly one patch target per
dependency (``dev10x.github._gateway.<name>``), so a test that patches it
intercepts every caller. ``async_run`` / ``async_run_script`` /
``AppConfig`` / ``get_bot_token`` are re-imported here for that reason.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dev10x.core.github.app_auth import AppConfig, get_bot_token
from dev10x.domain.common.repository_ref import RepositoryRef
from dev10x.domain.common.result import Result, SuccessResult, err, ok
from dev10x.domain.git_context import GitContext
from dev10x.domain.milestone_prefixes import REGISTRY_RELPATH, parse_registered_prefixes
from dev10x.domain.retry import RetryPolicy, is_retryable, retry_after_seconds
from dev10x.subprocess_utils import async_run, async_run_script

log = logging.getLogger(__name__)

# GH-1423: three attempts, so a throttled call gets two more chances
# without a caller's worst case growing past what the transport affords.
_GH_RETRY_POLICY = RetryPolicy()


async def _detect_repo() -> str | None:
    result = await async_run(
        args=["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
        timeout=10,
    )
    if result.returncode == 0:
        return result.stdout.strip()
    return None


async def _gh_api_raw(
    endpoint: str,
    *,
    method: str = "GET",
    fields: dict[str, str | int | list[str]] | None = None,
    jq: str | None = None,
    repo: str | None = None,
    as_bot: bool = False,
    bot_env: dict[str, str] | None = None,
    timeout: int = 30,
) -> subprocess.CompletedProcess[str]:
    args = ["gh", "api"]
    if method != "GET":
        args.extend(["-X", method])
    if jq:
        args.extend(["--jq", jq])

    # GH-1191: `-f 'key[]=value'` only builds a JSON array on gh versions
    # that support the bracket syntax for --raw-field. Older gh sends a
    # literal field named `key[]`, so GitHub rejects the request with
    # "<key> wasn't supplied" — a 422 that names the very field we passed.
    # A JSON body on stdin is version-independent, so any payload carrying
    # a list goes that way. Mixing is not an option: with `--input`, gh
    # moves every field flag into the query string.
    body: str | None = None
    if fields and any(isinstance(value, list) for value in fields.values()):
        body = json.dumps(fields)
        args.extend(["--input", "-"])
    elif fields:
        for key, value in fields.items():
            if isinstance(value, int):
                args.extend(["-F", f"{key}={value}"])
            else:
                args.extend(["-f", f"{key}={value}"])
    args.append(endpoint)

    # An already-resolved bot_env wins: re-minting the token here would
    # let a second exchange fail and silently fall through to engineer
    # credentials while the caller still reports a bot action (GH-1272).
    env = bot_env or (await _bot_env(repo=repo) if as_bot and repo else None)

    # GH-1423: every `gh` call used to be a single attempt, so routine
    # throttling surfaced to the caller as a hard failure. Retry only the
    # transient classes; a 404 or a 422 is retried zero times.
    policy = _GH_RETRY_POLICY
    for attempt in range(1, policy.attempts + 1):
        result = await async_run(args=args, timeout=timeout, env=env, input_text=body)
        if result.returncode == 0 or attempt == policy.attempts:
            return result
        # Our own timeout (GH-1304 returns -1 / "Process timed out") is
        # deliberately NOT retryable: the wait was already bounded on
        # purpose, and re-running multiplies it by `attempts` — the
        # long-wait failure GH-1288 removed from the CI poll.
        if result.returncode < 0 or not is_retryable(result.stderr):
            return result
        delay = policy.delay_for(
            attempt=attempt,
            retry_after=retry_after_seconds(result.stderr),
        )
        log.warning(
            "gh api %s failed transiently (attempt %d/%d), retrying in %.2fs: %s",
            endpoint,
            attempt,
            policy.attempts,
            delay,
            result.stderr.strip()[:200],
        )
        await asyncio.sleep(delay)
    return result


async def _gh_api(
    endpoint: str,
    *,
    method: str = "GET",
    fields: dict[str, str | int | list[str]] | None = None,
    jq: str | None = None,
    repo: str | None = None,
    as_bot: bool = False,
) -> Result[dict[str, Any]]:
    """Call ``gh api`` and enforce the Result[dict] contract centrally.

    Wraps :func:`_gh_api_raw` through :func:`_parse_gh_api_result` so
    JSON parsing and error handling live in one place rather than
    being repeated at every call site (ADR-0009, finding I8). Callers
    that need the raw ``CompletedProcess`` — custom GraphQL error
    handling or ``--jq`` scalar extraction — call :func:`_gh_api_raw`
    directly.
    """
    return _parse_gh_api_result(
        await _gh_api_raw(
            endpoint,
            method=method,
            fields=fields,
            jq=jq,
            repo=repo,
            as_bot=as_bot,
        )
    )


#: GitHub's REST page-size cap, and how many pages a listing follows
#: before it is reported as truncated rather than silently cut short.
PAGE_SIZE = 100
MAX_LISTING_PAGES = 10


@dataclass(frozen=True)
class Listing:
    """Every item a paged REST listing returned, and whether pages ran out."""

    items: tuple[dict[str, Any], ...]
    truncated: bool


def _page_items(*, raw: str, key: str | None, label: str) -> Result[list[dict[str, Any]]]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return err(f"could not parse {label} as JSON")
    if key is None:
        items = payload
    else:
        items = payload.get(key) if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return err(f"unexpected {label} shape from GitHub")
    return ok([item for item in items if isinstance(item, dict)])


async def _gh_api_paginated(
    endpoint: str,
    *,
    label: str,
    key: str | None = None,
    repo: str | None = None,
    max_pages: int = MAX_LISTING_PAGES,
) -> Result[Listing]:
    """Follow a REST listing page by page (GH-1852).

    ``ci_rerun`` and ``pr_wait`` each paged by hand, with their own
    ceiling and their own truncation policy. The ceiling is reported, not
    enforced as an error: a caller for whom a cut listing hides the very
    item it needs (the newest review) decides that for itself.

    ``key`` names the array inside an object payload (``check_suites``);
    without it the payload itself must be the array. ``label`` names the
    listing in error messages.
    """
    separator = "&" if "?" in endpoint else "?"
    first = f"{endpoint}{separator}per_page={PAGE_SIZE}"
    items: list[dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        paged = first if page == 1 else f"{first}&page={page}"
        result = await _gh_api_raw(paged, repo=repo)
        if result.returncode != 0:
            return err(result.stderr.strip() or f"could not list {label}")
        page_items = _page_items(raw=result.stdout, key=key, label=label)
        if not isinstance(page_items, SuccessResult):
            return page_items
        items.extend(page_items.value)
        if len(page_items.value) < PAGE_SIZE:
            return ok(Listing(items=tuple(items), truncated=False))
    return ok(Listing(items=tuple(items), truncated=True))


async def _bot_env(*, repo: str) -> dict[str, str] | None:
    try:
        ref = RepositoryRef.parse(repo)
    except ValueError:
        return None
    canonical_repo = str(ref)
    token = await get_bot_token(repo=canonical_repo)
    if token is None:
        if AppConfig.load() is not None:
            log.warning(
                "GitHub App auth configured but bot token exchange failed for %s — "
                "falling back to engineer credentials. Verify the App is installed "
                "on the repo and the private key matches the app_id.",
                canonical_repo,
            )
        return None
    return {**os.environ, "GH_TOKEN": token, "GITHUB_TOKEN": token}


def _milestone_prefix_registry() -> frozenset[str] | None:
    """Registered milestone prefixes for the current checkout, or None.

    None means the checkout keeps no registry, so the GH-1690 guard does
    not apply — `milestone_create` serves every repo, not only this one.
    """
    toplevel = GitContext().toplevel
    if toplevel is None:
        return None
    registry = Path(toplevel) / REGISTRY_RELPATH
    if not registry.is_file():
        return None
    try:
        text = registry.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        log.warning("milestone prefix registry %s is unreadable: %s", registry, exc)
        return None
    return parse_registered_prefixes(text=text)


async def _resolve_repo(
    repo: str | None,
) -> Result[RepositoryRef]:
    resolved = repo or await _detect_repo()
    if not resolved:
        return err("Could not detect repository. Provide repo parameter.")
    try:
        return ok(RepositoryRef.parse(resolved))
    except ValueError as exc:
        return err(str(exc))


def _parse_gh_api_result(
    result: subprocess.CompletedProcess[str],
) -> Result[dict[str, Any]]:
    if result.returncode != 0:
        return err(result.stderr.strip())
    try:
        return ok(json.loads(result.stdout))
    except json.JSONDecodeError:
        return ok({"raw_output": result.stdout})


async def _run_and_parse(
    script: str,
    *args: str,
    fallback: Callable[[str], dict[str, Any]] | None = None,
) -> Result[dict[str, Any]]:
    """Run a ``gh``-wrapper script and parse its stdout as JSON.

    Centralises the run → check-returncode → parse-JSON skeleton that was
    duplicated across the ``async_run_script`` wrappers (GH-837), where
    each copy had already drifted on its non-JSON fallback. On a non-zero
    exit the stderr becomes the error. On success stdout is parsed as
    JSON; if that fails, ``fallback`` (e.g. :func:`parse_key_value_output`)
    is applied to the raw stdout, otherwise the raw text is wrapped under
    ``raw_output``. Scripts that emit key=value rather than JSON pass
    ``fallback=parse_key_value_output`` — the JSON attempt is a harmless
    no-op for them and the fallback carries the parse.

    Valid JSON that is not an *object* is rejected here (GH-993). The
    ADR-0009 wire contract is a Mapping, and ``SuccessResult.to_dict()``
    casts blindly — so a script emitting a bare array reached the MCP
    boundary and died on ``dict(<list of dicts>)`` with the opaque
    "dictionary update sequence element #0 has length 11; 2 is required".
    Worse, an *empty* array degraded to a silent ``{}`` success, so
    callers read "no results" instead of an error. Failing loud here
    names the offending script instead.
    """
    result = await async_run_script(script, *args)
    if result.returncode != 0:
        return err(result.stderr.strip())
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        if fallback is not None:
            return ok(fallback(result.stdout))
        return ok({"raw_output": result.stdout})
    if not isinstance(payload, dict):
        return err(
            f"{script} emitted a JSON {type(payload).__name__}, expected an object; "
            "the wire contract (ADR-0009) requires a mapping — "
            "drop any jq '-q' unwrapping so the script emits {\"key\": ...}"
        )
    return ok(payload)
