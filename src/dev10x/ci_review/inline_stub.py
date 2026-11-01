from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from dev10x.ci_review.outbox import OUTBOX_ENV, append_entry

SERVER_NAME: str = "github_inline_comment"
FAKE_COMMENT_ID_BASE: int = 900_000_000
FAKE_COMMENT_ID_BITS: int = 40

server = FastMCP(name=SERVER_NAME)


@server.tool()
def create_inline_comment(
    path: str,
    body: str,
    line: int | None = None,
    startLine: int | None = None,  # the action's wire name, so the model's call matches
    side: str = "RIGHT",
    commit_id: str | None = None,
    confirmed: bool | None = None,
) -> str:
    """Record an inline review comment instead of posting it (dev10x ci-review dry run)."""
    if line is None and startLine is None:
        raise ValueError("Either line or startLine must be provided")
    outbox = Path(os.environ[OUTBOX_ENV])
    comment_id = fake_comment_id()
    append_entry(
        path=outbox,
        entry={
            "kind": "inline_comment",
            "comment_id": comment_id,
            "path": path,
            "body": body,
            "line": line,
            "startLine": startLine,
            "side": side,
            "commit_id": commit_id,
            "confirmed": confirmed,
        },
    )
    return json.dumps(
        {
            "success": True,
            "comment_id": comment_id,
            "html_url": None,
            "path": path,
            "line": line or startLine,
            "message": "Inline comment recorded to the dev10x ci-review outbox (dry run)",
        }
    )


def fake_comment_id() -> int:
    # Random, not counted from the outbox: concurrent calls read the same length.
    return FAKE_COMMENT_ID_BASE + (uuid.uuid4().int >> (128 - FAKE_COMMENT_ID_BITS))


def main() -> int:
    server.run()
    return 0


if __name__ == "__main__":  # pragma: no cover - process entry, run via `python -m`
    sys.exit(main())
