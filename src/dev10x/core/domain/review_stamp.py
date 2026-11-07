"""Review stamps: which commit a clean self-review covered (GH-1830).

A clean ``dev10x:review`` round records the head it reviewed, keyed by
``owner/repo`` and branch. The DX019 validator later compares the stamp
with the PR head before ``merge_pr``, ``pr_ready`` or ``request_review``
runs, so a fix pushed after the review no longer looks reviewed.

The stamp keeps the head's tree SHA as well as its commit SHA. A groom
that squashes fixups rewrites every commit SHA yet leaves the final tree
unchanged, and re-reviewing an identical tree would buy nothing.
Matching on the tree accepts exactly that case; any content change still
alters the tree and voids the stamp.

Store layout (``Dev10xConfigDir.review_stamps_json()``)::

    {"<owner>/<repo>": {"<branch>": {"head_sha": "...", "tree_sha": "...",
                                     "reviewed_at": "<ISO-8601 UTC>"}}}
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from dev10x.domain.file_locks import atomic_write_text, file_lock

log = logging.getLogger(__name__)

_SLUG_RE = re.compile(r"[/:](?P<owner>[^/:]+)/(?P<name>[^/]+?)(?:\.git)?/?$")
_PR_URL_RE = re.compile(r"github\.com/(?P<owner>[^/]+)/(?P<name>[^/]+)/pull/\d+")


class CorruptStampStoreError(OSError):
    """The stamp store exists but is not a JSON object; writing would erase it."""


@dataclass(frozen=True)
class ReviewStamp:
    head_sha: str
    tree_sha: str
    reviewed_at: str


class StampVerdict(StrEnum):
    CURRENT = "current"
    SAME_TREE = "same-tree"
    MISSING = "missing"
    STALE = "stale"

    @property
    def passes(self) -> bool:
        return self in (StampVerdict.CURRENT, StampVerdict.SAME_TREE)


def repo_slug_from_remote(*, url: str) -> str | None:
    """``owner/repo`` from an SSH or HTTPS remote URL (ADR-0026), casefolded.

    GitHub owners and repo names are case-insensitive, while a remote may
    spell them differently from the canonical PR URL; casefolding both
    sides keeps the writer and the reader on one key.
    """
    match = _SLUG_RE.search(url.strip())
    if match is None:
        return None
    return f"{match['owner']}/{match['name']}".casefold()


def repo_slug_from_pr_url(*, url: str) -> str | None:
    """``owner/repo`` from a GitHub pull request URL, casefolded."""
    match = _PR_URL_RE.search(url)
    if match is None:
        return None
    return f"{match['owner']}/{match['name']}".casefold()


def evaluate_stamp(
    *,
    stamp: ReviewStamp | None,
    head_sha: str,
    head_tree_sha: str | None,
) -> StampVerdict:
    """Decide whether ``stamp`` covers the PR head.

    ``head_tree_sha`` is ``None`` when the head commit is not available
    locally; only an exact commit match can pass then.
    """
    if stamp is None:
        return StampVerdict.MISSING
    if stamp.head_sha == head_sha:
        return StampVerdict.CURRENT
    if head_tree_sha and stamp.tree_sha == head_tree_sha:
        return StampVerdict.SAME_TREE
    return StampVerdict.STALE


@dataclass(frozen=True)
class ReviewStampStore:
    path: Path

    def read(self, *, slug: str, branch: str) -> ReviewStamp | None:
        repo_entry = self._load().get(slug)
        if not isinstance(repo_entry, dict):
            return None
        entry = repo_entry.get(branch)
        if not isinstance(entry, dict):
            return None
        try:
            return ReviewStamp(
                head_sha=str(entry["head_sha"]),
                tree_sha=str(entry["tree_sha"]),
                reviewed_at=str(entry["reviewed_at"]),
            )
        except KeyError:
            log.warning("malformed review stamp ignored", extra={"slug": slug, "branch": branch})
            return None

    def write(self, *, slug: str, branch: str, stamp: ReviewStamp) -> None:
        """Record ``stamp``; raise ``CorruptStampStoreError`` over a corrupt store."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with file_lock(self.path):
            data = self._load_strict()
            repo_entry = data.get(slug)
            if not isinstance(repo_entry, dict):
                repo_entry = {}
            repo_entry[branch] = asdict(stamp)
            data[slug] = repo_entry
            atomic_write_text(
                path=self.path,
                content=json.dumps(data, indent=2, sort_keys=True) + "\n",
            )

    def _load(self) -> dict[str, Any]:
        try:
            return self._load_strict()
        except CorruptStampStoreError:
            log.warning("unreadable review stamp store treated as empty", exc_info=True)
            return {}

    def _load_strict(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as exc:
            raise CorruptStampStoreError(f"{self.path} is unreadable: {exc}") from exc
        if not isinstance(data, dict):
            raise CorruptStampStoreError(f"{self.path} does not hold a JSON object")
        return data
