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

_URL = re.compile(
    r"https://github\.com/(?P<repo>[\w.-]+/[\w.-]+)/issues/(?P<number>\d+)",
    re.IGNORECASE,
)

_KEYWORDS = r"(?:fixes|closes|resolves)"
_BARE = re.compile(
    rf"\b{_KEYWORDS}:?\s+(?:GH-|#)(?P<number>\d+)\b",
    re.IGNORECASE,
)

_DECLARES_NONE = re.compile(r"fixes:[ \t]*none(?![\w-])", re.IGNORECASE)
_EXPLICIT_NONE = re.compile(
    r"fixes:[ \t]*none(?![\w-])[ \t]*[-–—]+(?P<reason>.*)",
    re.IGNORECASE,
)
_WORD = re.compile(r"[^\W_]")
_PLACEHOLDER = re.compile(r"<[^<>]*>")
_FENCE_MARKERS = ("```", "~~~")
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
    repository it names.
    """
    found: list[str] = []
    seen: set[str] = set()

    def add(*, target_repo: str, number: str) -> None:
        ref = f"{target_repo}#{number}"
        if ref not in seen:
            seen.add(ref)
            found.append(ref)

    for match in _URL.finditer(body):
        add(target_repo=match.group("repo"), number=match.group("number"))

    without_urls = _URL.sub(" ", body)
    for match in _BARE.finditer(without_urls):
        add(target_repo=repo, number=match.group("number"))

    return found


def closes_any(*, body: str) -> bool:
    """Whether ``body`` carries a reference close-issues would act on."""
    return bool(extract(body=body, repo=""))


def declares_none(*, line: str) -> bool:
    """Whether ``line`` is an attempt at a `Fixes: none` trailer, valid or not."""
    return _DECLARES_NONE.match(line.strip()) is not None


def is_usable_reason(*, reason: str) -> bool:
    stripped = reason.strip()
    return bool(_WORD.search(stripped)) and _PLACEHOLDER.fullmatch(stripped) is None


def visible_lines(*, body: str) -> list[str]:
    """Return the stripped lines a reader sees: no fenced code, no HTML comments."""
    visible: list[str] = []
    fence: str | None = None
    in_comment = False
    for raw in body.splitlines():
        text = raw
        if in_comment:
            close = text.find(_COMMENT_CLOSE)
            if close < 0:
                continue
            text = text[close + len(_COMMENT_CLOSE) :]
            in_comment = False
        stripped = text.strip()
        if fence is not None:
            if stripped.startswith(fence):
                fence = None
            continue
        opening = next((m for m in _FENCE_MARKERS if stripped.startswith(m)), None)
        if opening is not None:
            fence = opening
            continue
        text, in_comment = _without_comments(text=text)
        visible.append(text.strip())
    return visible


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
