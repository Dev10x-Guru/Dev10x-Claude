"""Durable record of notifications that never arrived (GH-1421).

``notify_slack`` and ``pr_notify`` return ``err(...)`` when a message
fails, and that error existed only in the one call's return value —
nothing persisted the message, queued it, or wrote it anywhere a person
could find it later.

In an attended session an agent surfaces the error to the user. Under
``foreman``'s unattended overnight crews there is no one to surface it
to, so a failed "crew stalled" or "PR ready for review" notification was
silently gone. That is the execution mode where a human is least likely
to notice quickly, and it is the mode this exists for.

**Discoverability is the whole goal — this is not a retry queue.** It
does not re-send, schedule, or track delivery state. Nothing reads the
file; a person greps it in the morning. Adding a retry subsystem here
would be a different feature with a different failure mode, and
``dev10x.domain.retry`` already covers the transient case *before* a
message reaches this sink.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dev10x.domain.dev10x_paths import Dev10xConfigDir
from dev10x.domain.file_locks import atomic_append_line

log = logging.getLogger(__name__)

_DEAD_LETTER_FILENAME = "undelivered-notifications.jsonl"

# atomic_append_line's single-write atomicity holds up to PIPE_BUF, so a
# long message body must not be allowed to push a record past it and start
# interleaving with a concurrent worktree's. The body is a hint for
# recognising the lost message, not an archive of it.
_MAX_RECORDED_BODY = 500


def dead_letter_path() -> Path:
    """Where undelivered notifications accumulate."""
    return Dev10xConfigDir.home() / _DEAD_LETTER_FILENAME


def record_undelivered(
    *,
    channel: str,
    transport: str,
    error: str,
    body: str | None = None,
    context: dict[str, Any] | None = None,
) -> None:
    """Append one failed notification to the dead-letter log.

    Never raises. A sink that can take down the caller it was added to
    protect would be worse than the gap it closes: the notification has
    already failed at this point, and losing the *call* as well converts
    a missed message into a broken crew.
    """
    record = {
        "at": datetime.now(UTC).isoformat(),
        "transport": transport,
        "channel": channel,
        "error": error,
        "body": (body or "")[:_MAX_RECORDED_BODY],
        **(context or {}),
    }
    try:
        atomic_append_line(dead_letter_path(), json.dumps(record))
    except (OSError, TypeError, ValueError) as ex:
        # TypeError/ValueError cover a context value json cannot encode.
        log.warning("Could not record an undelivered notification: %s", ex)
