#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Extract closable issue references from a PR body (GH-1196).

`close-issues.yml` used to require a full GitHub URL after `Fixes: `.
`create_pr`'s generated body emits that shape via `fixes_url`, so the
happy path worked -- but `create_pr(body=...)` is used verbatim
(GH-1073) whenever a PR needs more than one `Fixes:` line, which is
exactly the milestone/bundle case where closing constituents matters
most. A hand-written body using the repo's own documented `Fixes: GH-N`
shape matched nothing, and the workflow exited 0 reporting success.

This module is the extractor, split out of the workflow so the body
shapes are covered by a regression test rather than by a merge.

Reads the body on stdin, writes one `<owner>/<repo>#<number>` line per
reference to stdout, deduplicated and in first-seen order.
"""

from __future__ import annotations

import argparse
import re
import sys

# A full URL carries its own repo, so it can close an issue in another
# repository. Everything else is bare and resolves against --repo.
_URL = re.compile(
    r"https://github\.com/(?P<repo>[\w.-]+/[\w.-]+)/issues/(?P<number>\d+)",
    re.IGNORECASE,
)

# `Fixes:` is this repo's documented trailer (colon form). GitHub's own
# keywords take no colon. Both are accepted: a body that says
# `Closes #123` means it just as plainly as one that says `Fixes: GH-123`,
# and rejecting one of them on punctuation is how eight issues stayed open.
_KEYWORDS = r"(?:fixes|closes|resolves)"
_BARE = re.compile(
    rf"\b{_KEYWORDS}:?\s+(?:GH-|#)(?P<number>\d+)\b",
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

    # Strip URLs before scanning bare forms: `Fixes: https://.../issues/5`
    # would otherwise also match nothing useful, and a trailing `#5`
    # fragment in a link should not read as a second reference.
    without_urls = _URL.sub(" ", body)
    for match in _BARE.finditer(without_urls):
        add(target_repo=repo, number=match.group("number"))

    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo",
        required=True,
        help="owner/repo that bare GH-N / #N references resolve against",
    )
    args = parser.parse_args()

    for ref in extract(body=sys.stdin.read(), repo=args.repo):
        print(ref)
    return 0


if __name__ == "__main__":
    sys.exit(main())
