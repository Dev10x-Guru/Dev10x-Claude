"""PR-body hygiene rules (GH-945).

Pure functions mirroring the two hygiene-bot checks that `create_pr`
bodies recurrently tripped: the JTBD Job Story must carry all three
bold markers, and `Fixes:` must be the literal last line.
"""

import re
import unicodedata
from dataclasses import dataclass

from dev10x.core.fixes_trailer import (
    EXIT_MISSING,
    NONE_TRAILER_HINT,
    declares_none,
    references_in_line,
    verdict,
    visible_lines,
    visible_lines_by_index,
)

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
_GITHUB_SHAPED = re.compile(
    r"(?:fixes|closes|resolves):?\s*(?:#|GH-|https?://github\.com/)",
    re.IGNORECASE,
)
_FORMAT_CATEGORY = "Cf"
_GITHUB_REFERENCE = re.compile(
    r"https?://github\.com/[^\s/]+/[^\s/]+/issues/\d"
    r"|(?<![\w&/])(?:#|GH-)\d",
    re.IGNORECASE,
)
# GH-1896: the case patterns create-pr.sh uses to split a trailer.
_SPLITTABLE_REFERENCE = re.compile(r"https?://.*|#[0-9].*|[A-Z].*-[0-9].*", re.ASCII)
_IFS = re.compile(r"[ \t\n]+")
MISSING_REFERENCE_HINT = (
    "the trailer built from fixes_url, issue_id and closes names no reference; "
    "a fixes_url that is set replaces issue_id rather than adding to it, so "
    "pass an issue reference in fixes_url, or fixes_url='none — <reason>'"
)
MULTILINE_REFERENCE_HINT = (
    "the fixes_url or issue_id value spans several lines; pass it on one line"
)
SEVERAL_REFERENCES_HINT = (
    "a closing line names more GitHub issues than close-issues closes — it "
    "reads one reference per keyword, so the rest stay open. Pass one "
    "reference per comma- or space-separated token in fixes_url (e.g. "
    "'#12 #13', with no other words), or write one 'Fixes:' line per issue "
    "in the body"
)
UNREADABLE_REFERENCE_HINT = (
    "a GitHub reference must name an ASCII issue number on its own, e.g. "
    "'Fixes: #123', 'Fixes: GH-123' or 'Fixes: https://github.com/<owner>/"
    "<repo>/issues/123'; close-issues cannot read this one and fails the merge"
)
HIDDEN_TRAILER_HINT = (
    "job_story leaves a code fence or HTML comment open, which hides the "
    "Fixes: trailer appended after it; close the fence or comment"
)


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


def none_trailer_error(*, body: str) -> str | None:
    """Refuse a `Fixes: none` trailer that close-issues would fail on (GH-1873).

    Only a body whose trailer declares `none` is judged, and then by the
    same verdict() close-issues runs. A reference-only trailer is left
    alone: whether it closes anything depends on the repo's tracker,
    which create_pr does not know. The trailer is found on the lines
    close-issues reads (GH-1896), so indentation does not hide it and a
    fenced or commented example does not stand in for it.
    """
    if not any(declares_none(line=line) for line in visible_lines(body=body)):
        return None
    code, _ = verdict(body=body, repo="")
    if code != EXIT_MISSING:
        return None
    return f"Fixes: trailer is malformed — {NONE_TRAILER_HINT}"


def malformed_trailer_error(*, body: str) -> str | None:
    """Refuse a trailer close-issues cannot act on, before the PR opens.

    A `none` trailer is judged by none_trailer_error(). A closing line
    (`Fixes`, `Closes`, `Resolves`) shaped as a GitHub reference (`#`,
    `GH-`, a github.com URL) must
    yield an issue close-issues reads; one that does not, such as a
    non-ASCII number, is refused whatever the tracker (GH-1896). One that
    names more GitHub issues than close-issues reads from it, such as
    `Fixes: #12, #13`, is refused too: only the first would close
    (GH-1936).
    """
    none_error = none_trailer_error(body=body)
    if none_error is not None:
        return none_error
    closing = [line for line in visible_lines(body=body) if _is_github_shaped(line=line)]
    read = [len(references_in_line(line=line, repo="")) for line in closing]
    if 0 in read:
        return f"Fixes: trailer is malformed — {UNREADABLE_REFERENCE_HINT}"
    named = [len(_GITHUB_REFERENCE.findall(line)) for line in closing]
    if any(n > r for n, r in zip(named, read, strict=True)):
        return f"Fixes: trailer is malformed — {SEVERAL_REFERENCES_HINT}"
    return None


def _is_github_shaped(*, line: str) -> bool:
    """Whether ``line`` opens with a closing keyword and a GitHub reference.

    Format characters are dropped first: a zero-width space between the
    keyword and the number hides the reference from close-issues, and the
    line must still be judged rather than pass as non-GitHub (GH-1936).
    """
    shown = "".join(ch for ch in line if unicodedata.category(ch) != _FORMAT_CATEGORY)
    return _GITHUB_SHAPED.match(shown) is not None


def built_trailer_lines(*, references: str) -> list[str]:
    """The ``Fixes:`` lines create-pr.sh appends for ``references``.

    Mirrors the script: one line per reference when every comma- or
    whitespace-separated token is a reference, else the whole string on
    one line (so prose such as ``none — self-motivated`` stays intact).
    Tokens split on space, tab and newline only, as bash's IFS does.
    """
    tokens = [token for token in _IFS.split(references.replace(",", " ")) if token]
    if not tokens:
        return []
    if all(_SPLITTABLE_REFERENCE.fullmatch(token) for token in tokens):
        return [f"Fixes: {token}" for token in tokens]
    return [f"Fixes: {references.rstrip(chr(10))}"]


def built_trailer_error(*, job_story: str, references: str) -> str | None:
    """Judge the body create_pr assembles from ``job_story`` and a built trailer.

    The job story, the separator and the trailer lines are laid out as
    create-pr.sh lays them out. Every appended trailer line must be
    visible; a hidden one means the job story left a fence or comment
    open. The commit list and checklist between them are not known yet,
    so the read-back after create judges those.
    """
    trailer = built_trailer_lines(references=references)
    if not trailer:
        return f"Fixes: trailer is missing — {MISSING_REFERENCE_HINT}"
    if any("\n" in line for line in trailer):
        return f"Fixes: trailer is malformed — {MULTILINE_REFERENCE_HINT}"
    body = "\n".join([job_story, "", "---", "", *trailer])
    last = body.count("\n")
    appended = set(range(last - len(trailer) + 1, last + 1))
    if not appended <= _trailer_indices(body=body):
        return f"Fixes: trailer is malformed — {HIDDEN_TRAILER_HINT}"
    return malformed_trailer_error(body=body)


def fixes_trailer_error(*, body: str) -> str | None:
    if not _trailer_indices(body=body):
        return "body carries no Fixes: trailer"
    return malformed_trailer_error(body=body)


def has_fixes_trailer(*, body: str) -> bool:
    return fixes_trailer_error(body=body) is None


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
    trimmed = body.rstrip()
    lines = trimmed.split("\n")
    trailer = _trailer_indices(body=trimmed)
    fixes_start = _fixes_block_start(trailer=trailer)
    if fixes_start is None:
        return "\n".join(lines)

    fixes_end = _fixes_block_end(trailer=trailer, start=fixes_start)
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


def _trailer_indices(*, body: str) -> set[int]:
    """Indices of the visible ``Fixes:`` lines in ``body.split("\\n")``."""
    return {
        index
        for index, text in visible_lines_by_index(body=body).items()
        if _FIXES_PATTERN.match(text)
    }


def _fixes_block_start(*, trailer: set[int]) -> int | None:
    """Index of the first line in the trailing run of ``Fixes:`` lines."""
    if not trailer:
        return None
    start = max(trailer)
    while start - 1 in trailer:
        start -= 1
    return start


def _fixes_block_end(*, trailer: set[int], start: int) -> int:
    end = start
    while end + 1 in trailer:
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
