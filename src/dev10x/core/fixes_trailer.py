"""Grammar of the closing-reference trailer in a PR body (GH-1196, GH-1873).

Stdlib-only: `bin/extract-linked-issues.py` runs as a dependency-free
uv-script in `close-issues.yml` and reaches this module through a
`sys.path` shim, while `dev10x.domain.pr_body` imports it in-process, so
PR creation and merge read one rule.

`extract` writes one `<owner>/<repo>#<number>` reference per issue,
deduplicated and in first-seen order. `explicit_none_reason` returns the
reason carried by a `Fixes: none — <reason>` trailer (GH-1819).
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata

# GH-1896
_NUMBER_END = r"(?u:(?!\w))"
_HIDDEN_CATEGORIES = frozenset({"Mn", "Mc", "Me", "Cf"})
_URL = re.compile(
    rf"https://github\.com/(?P<repo>[\w.-]+/[\w.-]+)/issues/(?P<number>\d+){_NUMBER_END}",
    re.IGNORECASE | re.ASCII,
)

_KEYWORDS = r"(?:fixes|closes|resolves)"
_BARE = re.compile(
    rf"\b{_KEYWORDS}:?(?u:\s+)(?:GH-|#)(?P<number>\d+){_NUMBER_END}",
    re.IGNORECASE | re.ASCII,
)

_DECLARES_NONE = re.compile(r"fixes:[ \t]*none(?![\w-])", re.IGNORECASE)
_EXPLICIT_NONE = re.compile(
    r"fixes:[ \t]*none(?![\w-])[ \t]*[-–—]+(?P<reason>.*)",
    re.IGNORECASE,
)
_WORD = re.compile(r"[^\W_]")
_PLACEHOLDER = re.compile(r"<[^<>]*>")
_FENCE_OPEN = re.compile(r"(?P<marker>`{3,}|~{3,})(?P<info>.*)")
_MAX_FENCE_INDENT = 3
_COMMENT_OPEN = "<!--"
_COMMENT_CLOSE = "-->"

EXIT_REFS = 0
EXIT_MISSING = 1
EXIT_DECLARED_NONE = 3

RECOGNIZED_SHAPES = (
    "Fixes: GH-123",
    "Fixes: #123",
    "Closes #123",
    "Resolves #123",
    "Fixes: https://github.com/<owner>/<repo>/issues/123",
)

NONE_TRAILER_HINT = (
    "a 'Fixes: none' trailer must stand on its own line and carry a reason "
    "after a dash, e.g. 'Fixes: none — part of #123' or 'Fixes: none — "
    "self-motivated'. A bare 'Fixes: none', a punctuation-only reason, the "
    "'<reason>' placeholder, or a line inside a code block or HTML comment "
    "does not count, and close-issues fails the merge on it"
)


def extract(*, body: str, repo: str) -> list[str]:
    """Return `owner/repo#number` refs found in ``body``, first-seen order.

    ``repo`` resolves the bare `GH-N` / `#N` forms; a full URL keeps the
    repository it names. Only `visible_lines` are read, one at a time, so
    a reference in fenced code or an HTML comment closes nothing and a
    keyword never reaches a number across a hidden block.
    """
    found = (
        ref
        for line in visible_lines(body=body)
        for ref in references_in_line(line=line, repo=repo)
    )
    return list(dict.fromkeys(found))


def references_in_line(*, line: str, repo: str) -> list[str]:
    """Return the `owner/repo#number` refs one visible line closes."""
    refs = [
        f"{match.group('repo')}#{match.group('number')}"
        for match in _URL.finditer(line)
        if _ends_visibly(match=match)
    ]
    without_urls = _URL.sub(" ", line)
    refs.extend(
        f"{repo}#{match.group('number')}"
        for match in _BARE.finditer(without_urls)
        if _ends_visibly(match=match)
    )
    return refs


def _ends_visibly(*, match: re.Match[str]) -> bool:
    """Whether the number is not glued to a mark or format character a reader cannot see."""
    following = match.string[match.end() : match.end() + 1]
    return not following or unicodedata.category(following) not in _HIDDEN_CATEGORIES


def declares_none(*, line: str) -> bool:
    """Whether ``line`` is an attempt at a `Fixes: none` trailer, valid or not."""
    return _DECLARES_NONE.match(line.strip()) is not None


def is_usable_reason(*, reason: str) -> bool:
    stripped = reason.strip()
    return bool(_WORD.search(stripped)) and _PLACEHOLDER.fullmatch(stripped) is None


def visible_lines(*, body: str) -> list[str]:
    """Return the stripped lines a reader sees: no fenced code, no HTML comments."""
    return list(visible_lines_by_index(body=body).values())


def visible_lines_by_index(*, body: str) -> dict[int, str]:
    """Map each visible line's index in ``body.split("\\n")`` to its stripped text."""
    visible: dict[int, str] = {}
    fence: str | None = None
    in_comment = False
    for index, raw in enumerate(body.split("\n")):
        text = raw
        if in_comment:
            close = text.find(_COMMENT_CLOSE)
            if close < 0:
                continue
            text = text[close + len(_COMMENT_CLOSE) :]
            in_comment = False
        candidate = _fence_candidate(text=text)
        if fence is not None:
            if candidate is not None and _closes_fence(stripped=candidate, fence=fence):
                fence = None
            continue
        opening = None if candidate is None else _fence_opener(stripped=candidate)
        if opening is not None:
            fence = opening
            continue
        text, in_comment = _without_comments(text=text)
        visible[index] = text.strip()
    return visible


def _fence_candidate(*, text: str) -> str | None:
    """The line as a fence marker sees it, or None when indented as code."""
    unindented = text.lstrip(" ")
    if len(text) - len(unindented) > _MAX_FENCE_INDENT:
        return None
    return unindented.rstrip()


def _fence_opener(*, stripped: str) -> str | None:
    match = _FENCE_OPEN.match(stripped)
    if match is None:
        return None
    marker = match.group("marker")
    if marker.startswith("`") and "`" in match.group("info"):
        return None
    return marker


def _closes_fence(*, stripped: str, fence: str) -> bool:
    return len(stripped) >= len(fence) and stripped == fence[0] * len(stripped)


def _without_comments(*, text: str) -> tuple[str, bool]:
    kept: list[str] = []
    position = 0
    while True:
        start = text.find(_COMMENT_OPEN, position)
        if start < 0:
            kept.append(text[position:])
            return "".join(kept), False
        kept.append(text[position:start])
        close = text.find(_COMMENT_CLOSE, start + len(_COMMENT_OPEN))
        if close < 0:
            return "".join(kept), True
        position = close + len(_COMMENT_CLOSE)


def explicit_none_reason(*, body: str) -> str | None:
    """Return the reason of a usable `Fixes: none — <reason>` line, else None."""
    for line in visible_lines(body=body):
        match = _EXPLICIT_NONE.fullmatch(line)
        if match is None:
            continue
        reason = match.group("reason").strip()
        if is_usable_reason(reason=reason):
            return reason
    return None


def workflow_data(*, text: str) -> str:
    """Make PR-author text safe inside a GitHub workflow command."""
    printable = "".join(ch for ch in text if unicodedata.category(ch) != "Cc")
    return printable.replace("%", "%25")


def verdict(*, body: str, repo: str) -> tuple[int, list[str]]:
    """Decide what close-issues does with ``body``: exit code and lines to print.

    `EXIT_REFS` prints the references to close, `EXIT_DECLARED_NONE` a
    notice, and `EXIT_MISSING` the errors that fail the merged PR.
    """
    refs = extract(body=body, repo=repo)
    if refs:
        return EXIT_REFS, refs

    reason = explicit_none_reason(body=body)
    if reason is not None:
        notice = f"PR declares 'Fixes: none' ({reason}); nothing to close."
        return EXIT_DECLARED_NONE, [f"::notice::{workflow_data(text=notice)}"]

    lines = ["::error::No closable issue references found in the PR body."]
    if any(declares_none(line=line) for line in visible_lines(body=body)):
        lines.append(f"::error::{workflow_data(text=NONE_TRAILER_HINT)}.")
    shapes = ", ".join(f"'{shape}'" for shape in RECOGNIZED_SHAPES)
    lines.append(f"Recognized shapes: {shapes}.")
    lines.append("A PR that closes nothing declares 'Fixes: none — <reason>'.")
    return EXIT_MISSING, lines


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Decide which issues a merged PR body closes. Exit 0 prints the "
            f"references, {EXIT_DECLARED_NONE} a declared-none notice, "
            f"{EXIT_MISSING} the errors."
        )
    )
    parser.add_argument(
        "--repo",
        required=True,
        help="owner/repo that bare GH-N / #N references resolve against",
    )
    args = parser.parse_args()

    code, lines = verdict(body=sys.stdin.read(), repo=args.repo)
    for line in lines:
        print(line)
    return code
