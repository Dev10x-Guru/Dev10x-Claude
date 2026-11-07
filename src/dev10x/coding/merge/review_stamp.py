"""Record a clean self-review against the checked-out head (GH-1830).

The stamp is built from local git state only — HEAD, its tree and the
``origin`` remote — so the caller cannot name a commit it did not review.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
from datetime import UTC, datetime

from dev10x.domain.common.result import Result, err, ok
from dev10x.domain.dev10x_paths import Dev10xConfigDir
from dev10x.domain.file_locks import LockTimeoutError
from dev10x.domain.git_context import GitContext
from dev10x.domain.review_stamp import ReviewStamp, ReviewStampStore, repo_slug_from_remote

log = logging.getLogger(__name__)

_GIT_TIMEOUT_SECONDS = 5.0
_GIT_FAILURES = (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError)


async def record_clean_review() -> Result[dict]:
    return await asyncio.to_thread(_record_clean_review)


def _record_clean_review() -> Result[dict]:
    git = GitContext()
    try:
        head_sha = git.run("rev-parse", "HEAD", timeout=_GIT_TIMEOUT_SECONDS)
        tree_sha = git.run("rev-parse", "HEAD^{tree}", timeout=_GIT_TIMEOUT_SECONDS)
        remote_url = git.run("remote", "get-url", "origin", timeout=_GIT_TIMEOUT_SECONDS)
    except _GIT_FAILURES as exc:
        return err(f"Cannot read the reviewed head from git: {exc}")

    branch = git.branch
    if branch in ("HEAD", "unknown"):
        return err("HEAD is detached; a review stamp is keyed by branch. Check out the PR branch.")

    slug = repo_slug_from_remote(url=remote_url)
    if slug is None:
        return err(f"Cannot derive owner/repo from the origin remote {remote_url!r}.")

    stamp = ReviewStamp(
        head_sha=head_sha,
        tree_sha=tree_sha,
        reviewed_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )
    store = ReviewStampStore(path=Dev10xConfigDir.review_stamps_json())
    try:
        store.write(slug=slug, branch=branch, stamp=stamp)
    except LockTimeoutError:
        return err("The review stamp store is locked by another session. Please try again.")
    except OSError as exc:
        log.error("review stamp write failed", extra={"path": str(store.path)}, exc_info=True)
        return err(f"Cannot write the review stamp store {store.path}: {exc}")

    log.info("review stamp recorded", extra={"repo": slug, "branch": branch, "head": head_sha})
    return ok(
        {
            "repo": slug,
            "branch": branch,
            "head_sha": head_sha,
            "tree_sha": tree_sha,
            "reviewed_at": stamp.reviewed_at,
            "path": str(store.path),
        }
    )
