"""Reconcile a PR's ``Fixes:``/``Closes:`` links against its commits (GH-1241).

Check 1d asks whether each linked issue's *scope* was delivered — a
reasoning judgment about titled capabilities. That judgment is the right
instrument for the hard case (a commit exists but does not deliver what
the issue titled) and the wrong one for the easy case, which is what
actually shipped wrong: PR #1228 declared six links and carried commits
for five, and GH-1221 closed with no commit behind it at all.

A link with *no* commit mentioning its ticket needs no judgment. This
module answers that half deterministically so it cannot be missed under
session-close pressure, and the judgment pass layers on top for the rest.

A wrongly-closed issue is worse than an un-merged PR: it reads as settled
and drops out of every future sweep, so the defect stays live in shipped
code with nothing tracking it.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Standalone-script territory: this module is also the body of
# `skills/gh-pr-merge/scripts/reconcile-fixes-links.py`, which runs in a
# fresh uv process whose CWD is already the checkout being merged.
_SUBPROCESS_TIMEOUT_SECONDS = 60

# `Fixes:`/`Closes:` and the rest of GitHub's closing-keyword set. Matched
# case-insensitively and only where the keyword introduces the reference,
# so prose mentioning "#1228" in passing is not read as a link.
_CLOSING_KEYWORDS = (
    "close",
    "closes",
    "closed",
    "fix",
    "fixes",
    "fixed",
    "resolve",
    "resolves",
    "resolved",
)

# How a GitHub issue is referenced inline. Shared by both patterns below
# so the two cannot drift: a link the body writes one way and a commit
# writes the other must resolve to the same number, or the reconciliation
# reports a difference that only exists in the regexes.
_TICKET_REF = r"(?:GH-|#)(?P<num>\d+)"

_LINK = re.compile(
    # The separator is `\s*`, not `\s+`: a body written `Fixes:GH-1221`
    # with no space is still a link GitHub honours, and failing to parse
    # one is a false negative in the exact direction this module exists
    # to prevent — the check would pass a PR whose link it never saw.
    # Nothing new matches by accident, because the alternation below
    # still requires a `GH-`/`#` prefix or an issues URL.
    r"\b(?:" + "|".join(_CLOSING_KEYWORDS) + r")\b\s*:?\s*"
    r"(?:https?://\S*?/issues/(?P<url>\d+)|" + _TICKET_REF + r")",
    re.IGNORECASE,
)

# A commit subject carries its ticket as `GH-1234` or `#1234`, usually
# after the gitmoji. The body may carry more (a batched commit lists every
# member), so callers pass whole commit messages rather than subjects only.
_TICKET = re.compile(_TICKET_REF, re.IGNORECASE)


def _issue_numbers(pattern: re.Pattern[str], *texts: str) -> tuple[int, ...]:
    """Every issue number ``pattern`` finds, deduplicated, first-seen order.

    ``groupdict`` rather than ``group("url")`` because ``_TICKET`` has no
    ``url`` group at all — indexing it directly would raise on the very
    pattern this helper exists to share.
    """
    found: list[int] = []
    for text in texts:
        for match in pattern.finditer(text or ""):
            groups = match.groupdict()
            number = int(groups.get("url") or groups["num"])
            if number not in found:
                found.append(number)
    return tuple(found)


@dataclass(frozen=True)
class ScopeReconciliation:
    """What the deterministic half of Check 1d found."""

    linked: tuple[int, ...] = ()
    delivered: tuple[int, ...] = ()
    unbacked: tuple[int, ...] = field(default=())

    @property
    def ok(self) -> bool:
        return not self.unbacked

    def summary(self) -> str:
        if not self.linked:
            return "no Fixes:/Closes: links to reconcile"
        if self.ok:
            return f"all {len(self.linked)} linked issue(s) have a backing commit"
        names = ", ".join(f"GH-{number}" for number in self.unbacked)
        return (
            f"{len(self.unbacked)} of {len(self.linked)} linked issue(s) have no"
            f" commit mentioning them: {names}"
        )


def fixes_links(body: str) -> tuple[int, ...]:
    """Issue numbers a PR body would auto-close on merge, in first-seen order."""
    return _issue_numbers(_LINK, body)


def commit_ticket_ids(commit_messages: list[str]) -> tuple[int, ...]:
    """Ticket numbers mentioned anywhere in the given commit messages.

    The whole message is scanned, not just the subject: a batched commit
    names its non-canonical members only in the body, and treating those
    as undelivered would block exactly the multi-issue commit the bundle
    convention asks for.
    """
    return _issue_numbers(_TICKET, *commit_messages)


def reconcile_fixes_links(
    *,
    body: str,
    commit_messages: list[str],
    acknowledged: frozenset[int] | set[int] | None = None,
) -> ScopeReconciliation:
    """Diff a PR body's closing links against its commits' ticket IDs.

    ``acknowledged`` is the explicit escape for a link the author has
    deliberately kept without a commit of its own — an issue delivered by
    a commit that names a sibling, say. It is an argument rather than an
    inferred exception so the decision is recorded by a human somewhere
    rather than guessed here.
    """
    linked = fixes_links(body)
    mentioned = set(commit_ticket_ids(commit_messages))
    waived = set(acknowledged or ())
    delivered = tuple(number for number in linked if number in mentioned)
    unbacked = tuple(
        number for number in linked if number not in mentioned and number not in waived
    )
    return ScopeReconciliation(linked=linked, delivered=delivered, unbacked=unbacked)


def read_commit_messages(*, base: str, head: str = "HEAD") -> list[str]:
    """Full commit messages on ``head`` since ``base``.

    ``%B`` rather than ``%s`` so a batched commit's body — where its
    non-canonical members are listed — is part of the scan.
    """
    result = subprocess.run(
        ["git", "log", "--format=%B%x00", f"{base}..{head}"],
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git log {base}..{head} failed: {result.stderr.strip()}")
    return [chunk for chunk in result.stdout.split("\0") if chunk.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Reconcile a PR body's Fixes:/Closes: links against its commits."
    )
    parser.add_argument("--body-file", required=True, help="file holding the PR body")
    parser.add_argument("--base", required=True, help="base ref, e.g. origin/develop")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument(
        "--acknowledge",
        type=int,
        action="append",
        default=[],
        help="issue number deliberately linked without a commit of its own",
    )
    args = parser.parse_args(argv)

    # stdout is the single channel: this script's output is parsed, so an
    # error on stderr with empty stdout would leave the caller with nothing
    # to read (script-domain-boundaries.md).
    try:
        body = Path(args.body_file).read_text(encoding="utf-8")
        messages = read_commit_messages(base=args.base, head=args.head)
    except (OSError, RuntimeError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 2

    verdict = reconcile_fixes_links(
        body=body,
        commit_messages=messages,
        acknowledged=set(args.acknowledge),
    )
    print(
        json.dumps(
            {
                "ok": verdict.ok,
                "linked": list(verdict.linked),
                "delivered": list(verdict.delivered),
                "unbacked": list(verdict.unbacked),
                "summary": verdict.summary(),
            },
            indent=2,
        )
    )
    return 0 if verdict.ok else 1


if __name__ == "__main__":  # pragma: no cover - exercised via the shim
    sys.exit(main())
