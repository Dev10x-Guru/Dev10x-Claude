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

_URL = re.compile(
    r"https://github\.com/(?P<repo>[\w.-]+/[\w.-]+)/issues/(?P<number>\d+)",
    re.IGNORECASE,
)

_KEYWORDS = r"(?:fixes|closes|resolves)"
_BARE = re.compile(
    rf"\b{_KEYWORDS}:?\s+(?:GH-|#)(?P<number>\d+)\b",
    re.IGNORECASE,
)

_EXPLICIT_NONE = re.compile(
    r"fixes:[ \t]*none(?![\w-])[ \t]*[-–—]+(?P<reason>.*)",
    re.IGNORECASE,
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


def explicit_none_reason(*, body: str) -> str | None:
    """Return the reason of a `Fixes: none — <reason>` line, else None."""
    for line in body.splitlines():
        match = _EXPLICIT_NONE.fullmatch(line.strip())
        if match is None:
            continue
        reason = match.group("reason").strip()
        if reason:
            return reason
    return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract closable issue references from a PR body on stdin."
    )
    parser.add_argument(
        "--repo",
        help="owner/repo that bare GH-N / #N references resolve against",
    )
    parser.add_argument(
        "--explicit-none",
        action="store_true",
        help="print the reason of a `Fixes: none — <reason>` trailer instead",
    )
    args = parser.parse_args()
    if not args.explicit_none and not args.repo:
        parser.error("--repo is required unless --explicit-none is given")

    body = sys.stdin.read()
    if args.explicit_none:
        reason = explicit_none_reason(body=body)
        if reason is not None:
            print(reason)
        return 0

    for ref in extract(body=body, repo=args.repo):
        print(ref)
    return 0
