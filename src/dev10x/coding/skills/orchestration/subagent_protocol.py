"""Subagent status-line protocol parsing (GH-248 G3).

Extracted from the prose contract in
``references/orchestration/subagent-status-protocol.md`` so the
last-line status parsing used by every orchestration hub
(work-on, fanout, gh-pr-monitor, skill-audit, adr-evaluate) has a
single importable, unit-tested implementation instead of being
re-derived in each skill body.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

STATUS_PROMPT_TEMPLATE = """\
Report your final status as the LAST line of your output, with
exactly one of these prefixes:

- DONE                           — task complete
- DONE_WITH_CONCERNS: <text>     — complete but flagged
- NEEDS_CONTEXT: <what>          — re-dispatch needed
- BLOCKED: <reason>              — cannot proceed (permission,
                                    missing tool, unrecoverable)
- BLOCKED: hook denied <command> — a hook refused a command; stop,
                                    do not try another shape

Do not write anything after the status line."""

# The template asks for `hook denied <command>`, but any blocked or
# unreadable report that mentions a hook is surfaced rather than re-run:
# listing phrasings left a new gap with every wording (GH-1874).
HOOK_MENTION = re.compile(r"\bhooks?\b", re.IGNORECASE)

# A named background agent's plain-text output is NOT delivered to the
# orchestrator — only an idle notification with no content arrives
# (GH-776). Background dispatches MUST append this so the status line
# actually reaches the controller.
BACKGROUND_DELIVERY_TEMPLATE = """\
Your plain-text output is NOT delivered to the orchestrator when you
run as a named background agent — the orchestrator only receives an
idle notification with no content. Deliver your report explicitly:

- Call SendMessage(to="main", summary="<5 words>", message=<full
  report ending with your status line>).
- If SendMessage(to="main", ...) is rejected with "Send to a named
  agent instead", the "main" alias is not registered in this harness
  config — retry addressing the orchestrator by the actual name/ID it
  told you to report to at dispatch.
- If the report exceeds one message, split it into labeled parts and
  send them in order.
- Fallback: Write the report to the scratchpad path you were given,
  then send a one-line SendMessage confirming the path.

The status line (DONE / DONE_WITH_CONCERNS / NEEDS_CONTEXT / BLOCKED)
must be the LAST line of the SendMessage payload — bare stdout is
never read."""


class SubagentStatus(StrEnum):
    DONE = "DONE"
    DONE_WITH_CONCERNS = "DONE_WITH_CONCERNS"
    NEEDS_CONTEXT = "NEEDS_CONTEXT"
    BLOCKED = "BLOCKED"
    # Missing or unrecognized status line — the controller treats a
    # protocol violation as BLOCKED (subagent-status-protocol.md).
    MALFORMED = "MALFORMED"


# Prefixes that carry a free-text payload after the colon.
_PAYLOAD_PREFIXES: tuple[tuple[str, SubagentStatus], ...] = (
    ("DONE_WITH_CONCERNS:", SubagentStatus.DONE_WITH_CONCERNS),
    ("NEEDS_CONTEXT:", SubagentStatus.NEEDS_CONTEXT),
    ("BLOCKED:", SubagentStatus.BLOCKED),
)


@dataclass(frozen=True)
class ParsedStatus:
    status: SubagentStatus
    payload: str
    raw_line: str


def _last_non_empty_line(result: str) -> str:
    for line in reversed(result.splitlines()):
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def parse_subagent_status(result: str) -> ParsedStatus:
    raw_line = _last_non_empty_line(result=result)

    if raw_line == SubagentStatus.DONE.value:
        return ParsedStatus(status=SubagentStatus.DONE, payload="", raw_line=raw_line)

    for prefix, status in _PAYLOAD_PREFIXES:
        if raw_line.startswith(prefix):
            payload = raw_line[len(prefix) :].strip()
            return ParsedStatus(status=status, payload=payload, raw_line=raw_line)

    return ParsedStatus(status=SubagentStatus.MALFORMED, payload="", raw_line=raw_line)


_FALLBACK_STATUSES = (SubagentStatus.BLOCKED, SubagentStatus.MALFORMED)


def is_hook_denial(*, parsed: ParsedStatus) -> bool:
    """A blocked or unreadable report that names a hook (GH-1874).

    Deliberately broad: a false match only means the controller surfaces
    the report instead of re-running it, while a miss re-runs a command a
    hook refused.
    """
    return parsed.status in _FALLBACK_STATUSES and HOOK_MENTION.search(parsed.raw_line) is not None


def requires_main_session_fallback(*, parsed: ParsedStatus) -> bool:
    """Whether the controller re-runs the work in the main session (GH-901).

    A hook denial is surfaced instead: re-running the denied command from
    the main session either hits the same hook or slips past it.
    """
    return parsed.status in _FALLBACK_STATUSES and not is_hook_denial(parsed=parsed)
