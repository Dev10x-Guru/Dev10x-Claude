"""Shared `gh` CLI JSON helpers for the notification review-request modules.

Both slack_review_request and gchat_review_request fetch PR metadata with
`gh ... --json`; this module holds the one implementation they share.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from dev10x import subprocess_utils

# `gh` fetches PR metadata over the network; bound so a hung API call cannot
# stall a long-lived MCP server (ADR-0011).
_GH_TIMEOUT_SECONDS = 30


class GhCommandError(RuntimeError):
    """A `gh` invocation failed — raised so entry points own exit codes."""


def gh_json(args: list[str], *, cwd: str | None = None) -> Any:
    """Run an arbitrary `gh <subcommand> --json ...` and parse the output.

    For a `gh api <endpoint>` call, prefer :func:`gh_api_json` instead —
    it routes through the shared ``dev10x.github`` Gateway (GH-1442)
    rather than reimplementing the run/parse/error-wrap cycle here. This
    function remains for subcommands with no Gateway equivalent (e.g.
    `gh pr view --json <fields>`, where the Gateway's `pr_get` fetches a
    fixed broader field set).
    """
    result = subprocess_utils.run(
        ["gh", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=_GH_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise GhCommandError(f"gh {' '.join(args)}: {result.stderr.strip()}")
    return json.loads(result.stdout)


def gh_api_json(endpoint: str) -> Any:
    """Call `gh api <endpoint>` through the shared Gateway (GH-1442).

    These review-request modules are synchronous CLI scripts, unlike
    ``dev10x.github`` (async throughout, for the MCP event loop), so this
    is the one place that bridges the two: it runs
    :func:`dev10x.github._gh_api_raw` — the same GET/retry/timeout logic
    every other `gh api` caller in the codebase uses — via
    ``asyncio.run`` rather than reimplementing that logic's own miniature
    copy here.

    Raises :class:`GhCommandError` on a non-zero exit, matching
    :func:`gh_json`'s contract so existing `except (GhCommandError,
    json.JSONDecodeError)` call sites need no change.
    """
    from dev10x.github import _gh_api_raw

    result = asyncio.run(_gh_api_raw(endpoint, timeout=_GH_TIMEOUT_SECONDS))
    if result.returncode != 0:
        raise GhCommandError(f"gh api {endpoint}: {result.stderr.strip()}")
    return json.loads(result.stdout)
