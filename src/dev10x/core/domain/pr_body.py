"""PR-body hygiene rules (GH-945).

Pure functions mirroring the two hygiene-bot checks that `create_pr`
bodies recurrently tripped: the JTBD Job Story must carry all three
bold markers, and `Fixes:` must be the literal last line.
"""

import re
from dataclasses import dataclass

WHEN_MARKER = "**When**"
WANTS_MARKER = "**<actor> wants**"
SO_CAN_MARKER = "**so <beneficiary> can**"

JOB_STORY_FORMAT = (
    "**When** <situation>, **<actor> wants to** <motivation>, **so <beneficiary> can** <outcome>"
)


@dataclass(frozen=True)
class JobStoryDialect:
    """One language's spelling of the three structural JTBD markers.

    The skill instructions tell writers to use the project's language
    (`gh-pr-create` Step 3d) and to search for translated markers when
    reading (Step 3b), but the validator matched English literals — so a
    Polish story written exactly as its own project prescribed was
    refused at the only point that could still accept it (GH-1291). The
    workaround it forced, English markers around Polish prose, reads
    worse than either language alone.
    """

    language: str
    markers: tuple[str, str, str]
    patterns: tuple[re.Pattern[str], re.Pattern[str], re.Pattern[str]]

    @property
    def format_hint(self) -> str:
        situation, motivation, outcome = self.markers
        return f"{situation} …, {motivation} …, {outcome} …"


# GH-1258: an outcome frame ("**the dealer wants** the reason to be
# obvious") carries the actor but not the `to` verb, so demanding a
# literal `wants to**` forced writers off the guidance jtbd recommends.
# The leading `[^*\s]` keeps the actor clause mandatory — `**wants**`
# still fails. The Polish patterns keep the same shape: the actor clause
# is mandatory, the verb may inflect.
_ENGLISH = JobStoryDialect(
    language="en",
    markers=(WHEN_MARKER, WANTS_MARKER, SO_CAN_MARKER),
    patterns=(
        re.compile(r"\*\*When\*\*"),
        re.compile(r"\*\*[^*\s][^*]*\bwants?\b[^*]*\*\*"),
        re.compile(r"\*\*so\b[^*]*\bcan\b[^*]*\*\*"),
    ),
)

_POLISH = JobStoryDialect(
    language="pl",
    markers=("**Gdy**", "**<rola> chce**", "**żeby <beneficjent> mógł**"),
    patterns=(
        re.compile(r"\*\*Gdy\*\*"),
        re.compile(r"\*\*[^*\s][^*]*\bchc[ei]\b[^*]*\*\*"),
        re.compile(r"\*\*żeby\b[^*]*\bm(?:óg[łl]|ogł[aoy]|ogli)\b[^*]*\*\*"),
    ),
)

DIALECTS: tuple[JobStoryDialect, ...] = (_ENGLISH, _POLISH)

_SEPARATOR_PATTERN = re.compile(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$")
_FIXES_PATTERN = re.compile(r"^Fixes:", re.IGNORECASE)


def _missing_for(dialect: JobStoryDialect, *, job_story: str) -> list[str]:
    return [
        marker
        for marker, pattern in zip(dialect.markers, dialect.patterns, strict=True)
        if not pattern.search(job_story)
    ]


def missing_job_story_markers(*, job_story: str) -> list[str]:
    """Return the JTBD markers absent from ``job_story``, in order.

    A story satisfies the contract when ANY one dialect is complete —
    mixing halves of two languages is what the old validator pushed
    writers into, and it is not a pass. The reported gap comes from the
    dialect the story came closest to, so the error names the language
    the author was actually writing.
    """
    per_dialect = [_missing_for(dialect, job_story=job_story) for dialect in DIALECTS]
    if any(not missing for missing in per_dialect):
        return []
    return min(per_dialect, key=len)


def job_story_error(*, job_story: str) -> str | None:
    """Return an actionable error when ``job_story`` is non-compliant."""
    missing = missing_job_story_markers(job_story=job_story)
    if not missing:
        return None
    accepted = "; ".join(f"{d.language}: {d.format_hint}" for d in DIALECTS)
    return (
        "Job Story is missing required JTBD marker(s): "
        + ", ".join(missing)
        + f". Accepted marker sets — {accepted}. Use one language "
        "throughout. Third-person concrete domain actor — see "
        "references/git-jtbd.md."
    )


def _issue_reference(issue_id: str) -> str:
    bare = issue_id.strip().lstrip("#")
    return f"#{bare}" if bare.isdigit() else bare


def fixes_references(
    *,
    issue_id: str,
    fixes_url: str | None,
    closes: list[int] | None,
) -> str:
    """Assemble the ``Fixes:`` references for a new PR (GH-1256).

    ``create-pr.sh`` derived its trailer from ``fixes_url`` alone, so
    linking an issue the documented way — ``issue_id`` — produced a body
    with no trailer, which the hygiene bot rejects. ``closes`` members
    are folded in for a second reason: ``Closes #N`` never fires on a
    merge to ``develop`` (GH-958), so only a ``Fixes:`` line closes them.

    An explicit ``fixes_url`` leads, and prose such as
    ``none — self-motivated`` passes through untouched so the script's
    non-splittable branch keeps handling it.
    """
    if fixes_url and not fixes_url.lstrip().startswith(("http", "#")):
        return fixes_url

    references = [fixes_url] if fixes_url else [_issue_reference(issue_id)]
    references.extend(f"#{number}" for number in closes or [])
    return " ".join(dict.fromkeys(reference for reference in references if reference))


def has_fixes_trailer(*, body: str) -> bool:
    return _last_fixes_index(lines=body.rstrip().split("\n")) is not None


def normalize_pr_body(*, body: str) -> str:
    """Move any content trailing the ``Fixes:`` trailer above it.

    A separator-only trailer (the bare ``---`` left behind when the
    checklist template is absent) is dropped; substantive trailing
    content is relocated so the ``Fixes:`` block ends the body. Returns
    the body without a trailing newline.

    A bundle PR closes several issues and needs one ``Fixes:`` line per
    issue (GH-1107 finding 2), so a contiguous run of them is treated as
    a single trailer — splitting the run with a blank line would leave
    the earlier entries stranded in the body.
    """
    lines = body.rstrip().split("\n")
    fixes_start = _fixes_block_start(lines=lines)
    if fixes_start is None:
        return "\n".join(lines)

    fixes_end = _fixes_block_end(lines=lines, start=fixes_start)
    head = lines[:fixes_start]
    fixes_block = [line.rstrip() for line in lines[fixes_start : fixes_end + 1]]
    relocated = _relocatable_trailer(lines=lines[fixes_end + 1 :])

    if relocated:
        head = _trim_blank_edges(lines=head)
        head = head + [""] + relocated if head else relocated

    head = _trim_blank_edges(lines=head)
    if not head:
        return "\n".join(fixes_block)
    return "\n".join([*head, "", *fixes_block])


def _last_fixes_index(*, lines: list[str]) -> int | None:
    for index in range(len(lines) - 1, -1, -1):
        if _FIXES_PATTERN.match(lines[index]):
            return index
    return None


def _fixes_block_start(*, lines: list[str]) -> int | None:
    """Index of the first line in the trailing run of ``Fixes:`` lines."""
    last = _last_fixes_index(lines=lines)
    if last is None:
        return None
    start = last
    while start > 0 and _FIXES_PATTERN.match(lines[start - 1]):
        start -= 1
    return start


def _fixes_block_end(*, lines: list[str], start: int) -> int:
    end = start
    while end + 1 < len(lines) and _FIXES_PATTERN.match(lines[end + 1]):
        end += 1
    return end


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
