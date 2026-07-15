"""Shared `gh` CLI JSON helper for the notification review-request modules.

Both slack_review_request and gchat_review_request fetch PR metadata with
`gh ... --json`; this module holds the one implementation they share.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any


class GhCommandError(RuntimeError):
    """A `gh` invocation failed — raised so entry points own exit codes."""


def gh_json(args: list[str]) -> Any:
    result = subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise GhCommandError(f"gh {' '.join(args)}: {result.stderr.strip()}")
    return json.loads(result.stdout)
