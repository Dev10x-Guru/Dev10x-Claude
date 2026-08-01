"""PR-body hygiene rules (GH-945).

Pure functions mirroring the two hygiene-bot checks that `create_pr`
bodies recurrently tripped: the JTBD Job Story must carry all three
bold markers, and `Fixes:` must be the literal last line.
"""

import re

WHEN_MARKER = "**When**"
WANTS_MARKER = "**<actor> wants to**"
SO_CAN_MARKER = "**so <beneficiary> can**"

JOB_STORY_FORMAT = (
    "**When** <situation>, **<actor> wants to** <motivation>, **so <beneficiary> can** <outcome>"
)

_WHEN_PATTERN = re.compile(r"\*\*When\*\*")
_WANTS_PATTERN = re.compile(r"\*\*[^*]*\bwants? to\*\*")
_SO_CAN_PATTERN = re.compile(r"\*\*so\b[^*]*\bcan\b[^*]*\*\*")

_SEPARATOR_PATTERN = re.compile(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$")
_FIXES_PATTERN = re.compile(r"^Fixes:", re.IGNORECASE)


def missing_job_story_markers(*, job_story: str) -> list[str]:
    """Return the JTBD markers absent from ``job_story``, in order."""
    checks = (
        (WHEN_MARKER, _WHEN_PATTERN),
        (WANTS_MARKER, _WANTS_PATTERN),
        (SO_CAN_MARKER, _SO_CAN_PATTERN),
    )
    return [marker for marker, pattern in checks if not pattern.search(job_story)]


def job_story_error(*, job_story: str) -> str | None:
    """Return an actionable error when ``job_story`` is non-compliant."""
    missing = missing_job_story_markers(job_story=job_story)
    if not missing:
        return None
    return (
        "Job Story is missing required JTBD marker(s): "
        + ", ".join(missing)
        + f". Expected format: {JOB_STORY_FORMAT}. Third-person concrete "
        "domain actor — see references/git-jtbd.md."
    )


def has_fixes_trailer(*, body: str) -> bool:
    return _last_fixes_index(lines=body.rstrip().split("\n")) is not None


def normalize_pr_body(*, body: str) -> str:
    """Move any content trailing the ``Fixes:`` line above it.

    A separator-only trailer (the bare ``---`` left behind when the
    checklist template is absent) is dropped; substantive trailing
    content is relocated so ``Fixes:`` ends the body. Returns the body
    without a trailing newline.
    """
    lines = body.rstrip().split("\n")
    fixes_index = _last_fixes_index(lines=lines)
    if fixes_index is None:
        return "\n".join(lines)

    head = lines[:fixes_index]
    fixes_line = lines[fixes_index].rstrip()
    relocated = _relocatable_trailer(lines=lines[fixes_index + 1 :])

    if relocated:
        head = _trim_blank_edges(lines=head)
        head = head + [""] + relocated if head else relocated

    head = _trim_blank_edges(lines=head)
    if not head:
        return fixes_line
    return "\n".join([*head, "", fixes_line])


def _last_fixes_index(*, lines: list[str]) -> int | None:
    for index in range(len(lines) - 1, -1, -1):
        if _FIXES_PATTERN.match(lines[index]):
            return index
    return None


def _relocatable_trailer(*, lines: list[str]) -> list[str]:
    substantive = [line for line in lines if line.strip() and not _SEPARATOR_PATTERN.match(line)]
    if not substantive:
        return []
    return _trim_blank_edges(lines=lines)


def _trim_blank_edges(*, lines: list[str]) -> list[str]:
    start = 0
    end = len(lines)
    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1
    return lines[start:end]
