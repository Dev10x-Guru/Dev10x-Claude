"""Shared `gh` CLI JSON helper for the notification review-request modules.

Both slack_review_request and gchat_review_request fetch PR metadata with
`gh ... --json`; this module holds the one implementation they share.
"""

from __future__ import annotations

import json
from typing import Any

from dev10x import subprocess_utils

# `gh` fetches PR metadata over the network; bound so a hung API call cannot
# stall a long-lived MCP server (ADR-0011).
_GH_TIMEOUT_SECONDS = 30


class GhCommandError(RuntimeError):
    """A `gh` invocation failed — raised so entry points own exit codes."""


def gh_json(args: list[str], *, cwd: str | None = None) -> Any:
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
