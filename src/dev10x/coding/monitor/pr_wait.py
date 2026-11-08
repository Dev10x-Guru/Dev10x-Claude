"""Wait for a PR condition inside one bounded tool call (GH-1833).

Sessions used to hand-roll a polling script per condition — merged,
closed, head moved, approved, a bot reviewed the head — and every one
skipped the transport budget (GH-1288), the retry policy (GH-1423) and
the subprocess cap (GH-1422). This loop polls through the Gateway, so it
inherits the last two, sizes its poll count with the same
``polls_within_budget`` that bounds ``ci_check_status``, and runs on the
shared ``poll_until`` loop (GH-1852).

Dependencies are reached through ``_gateway.<name>`` (ADR-0027 D2).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from dev10x.core.github import _gateway
from dev10x.domain.common.result import ErrorResult, Result, err, ok
from dev10x.domain.polling import Deadline, poll_until
from dev10x.domain.transport_budget import polls_within_budget

log = logging.getLogger(__name__)

CONDITIONS: tuple[str, ...] = (
    "merged",
    "closed",
    "merged_or_closed",
    "head_changed",
    "approved",
    "bot_at_head",
)

_NEEDS_REVIEWS = frozenset({"approved", "bot_at_head"})
_NEEDS_OPEN_PR = _NEEDS_REVIEWS | {"head_changed"}
_OVERHEAD_SECONDS = 60
_MIN_POLL_INTERVAL = 5
_BOT_SUFFIX = "[bot]"


@dataclass(frozen=True)
class _Verdict:
    met: bool
    unreachable: bool


@dataclass(frozen=True)
class PrSnapshot:
    state: str
    merged: bool
    head_sha: str
    reviews: tuple[dict[str, Any], ...] = ()

    @property
    def is_open(self) -> bool:
        return self.state == "open"


def _normalize_login(login: str) -> str:
    lowered = login.strip().lower()
    return lowered.removesuffix(_BOT_SUFFIX)


def _is_bot_review(*, review: dict[str, Any], bot: str | None) -> bool:
    user = review.get("user") or {}
    login = str(user.get("login") or "")
    if bot:
        return _normalize_login(login) == _normalize_login(bot)
    return user.get("type") == "Bot" or login.lower().endswith(_BOT_SUFFIX)


def _latest_review_states(*, reviews: tuple[dict[str, Any], ...]) -> dict[str, str]:
    latest: dict[str, str] = {}
    for review in reviews:
        state = str(review.get("state") or "")
        if state in {"COMMENTED", "PENDING", ""}:
            continue
        login = str((review.get("user") or {}).get("login") or "")
        latest[login] = state
    return latest


def _is_approved(*, snapshot: PrSnapshot) -> bool:
    states = set(_latest_review_states(reviews=snapshot.reviews).values())
    return "APPROVED" in states and "CHANGES_REQUESTED" not in states


def _bot_review_at_head(*, snapshot: PrSnapshot, bot: str | None) -> dict[str, Any] | None:
    for review in reversed(snapshot.reviews):
        if review.get("commit_id") != snapshot.head_sha:
            continue
        if _is_bot_review(review=review, bot=bot):
            return review
    return None


def is_met(
    *,
    until: str,
    snapshot: PrSnapshot,
    baseline_sha: str,
    bot: str | None,
) -> bool:
    if until == "merged":
        return snapshot.merged
    if until == "closed":
        return snapshot.state == "closed" and not snapshot.merged
    if until == "merged_or_closed":
        return snapshot.state == "closed"
    if until == "head_changed":
        return snapshot.head_sha != baseline_sha
    if until == "approved":
        return _is_approved(snapshot=snapshot)
    return _bot_review_at_head(snapshot=snapshot, bot=bot) is not None


def is_unreachable(*, until: str, snapshot: PrSnapshot) -> bool:
    if until == "merged":
        return snapshot.state == "closed" and not snapshot.merged
    if until == "closed":
        return snapshot.merged
    if until in _NEEDS_OPEN_PR:
        return not snapshot.is_open
    return False


async def _fetch_reviews(*, repo: str, pr_number: int) -> Result[tuple[dict[str, Any], ...]]:
    """Every review, oldest first; a listing past the page ceiling is an error.

    The newest review is last, so a cut-off listing would hide exactly
    the verdict ``approved`` and ``bot_at_head`` depend on.
    """
    listed = await _gateway._gh_api_paginated(
        f"repos/{repo}/pulls/{pr_number}/reviews",
        label=f"reviews for PR {pr_number}",
        repo=repo,
    )
    if isinstance(listed, ErrorResult):
        return listed
    if listed.value.truncated:
        ceiling = _gateway.MAX_LISTING_PAGES * _gateway.PAGE_SIZE
        return err(f"PR {pr_number} has more than {ceiling} reviews; the newest could not be read")
    return ok(listed.value.items)


async def _fetch_snapshot(*, repo: str, pr_number: int, until: str) -> Result[PrSnapshot]:
    pull = await _gateway._gh_api_raw(f"repos/{repo}/pulls/{pr_number}", repo=repo)
    if pull.returncode != 0:
        return err(pull.stderr.strip() or f"could not read PR {pr_number}")
    try:
        payload = json.loads(pull.stdout)
    except json.JSONDecodeError:
        return err(f"could not parse PR {pr_number} as JSON")
    if not isinstance(payload, dict):
        return err(f"unexpected PR {pr_number} payload shape")
    reviews: tuple[dict[str, Any], ...] = ()
    if until in _NEEDS_REVIEWS:
        listed = await _fetch_reviews(repo=repo, pr_number=pr_number)
        if isinstance(listed, ErrorResult):
            return listed
        reviews = listed.value
    return ok(
        PrSnapshot(
            state=str(payload.get("state") or ""),
            merged=bool(payload.get("merged")),
            head_sha=str((payload.get("head") or {}).get("sha") or ""),
            reviews=reviews,
        )
    )


def _observed(
    *,
    snapshot: PrSnapshot,
    until: str,
    baseline_sha: str,
    bot: str | None,
) -> dict[str, Any]:
    observed: dict[str, Any] = {
        "state": snapshot.state,
        "merged": snapshot.merged,
        "head_sha": snapshot.head_sha,
    }
    if until == "head_changed":
        observed["baseline_sha"] = baseline_sha
    if until == "approved":
        observed["review_states"] = _latest_review_states(reviews=snapshot.reviews)
    if until == "bot_at_head":
        review = _bot_review_at_head(snapshot=snapshot, bot=bot)
        observed["bot_review"] = (
            None
            if review is None
            else {
                "login": (review.get("user") or {}).get("login"),
                "state": review.get("state"),
                "commit_id": review.get("commit_id"),
            }
        )
    return observed


async def pr_wait(
    *,
    pr_number: int,
    until: str,
    repo: str | None = None,
    poll_interval: int = 30,
    max_polls: int = 40,
    since_sha: str | None = None,
    bot: str | None = None,
) -> Result[dict[str, Any]]:
    """Poll a PR until ``until`` holds, it cannot hold, or the budget ends.

    Args:
        pr_number: PR to watch.
        until: One of ``CONDITIONS``.
        repo: Repository (owner/repo). Auto-detected if omitted.
        poll_interval: Seconds between polls; floored at 5.
        max_polls: Polls requested; granted only as far as the transport
            budget affords.
        since_sha: Baseline for ``head_changed``; defaults to the head
            read on the first poll.
        bot: Bot login for ``bot_at_head`` (``[bot]`` suffix optional);
            any bot reviewer when omitted.

    Returns:
        ``{"pr_number", "repo", "until", "met", "timed_out", "unreachable",
        "observed", "polls", "polls_granted", "polls_requested",
        "budget_clamped", "probe_errors"}``. An error only when the
        arguments are invalid or no poll could read the PR at all.
    """
    if until not in CONDITIONS:
        return err(f"until must be one of {', '.join(CONDITIONS)}, got {until!r}")
    if pr_number <= 0:
        return err(f"pr_number must be positive, got {pr_number}")
    if max_polls < 1:
        return err(f"max_polls must be at least 1, got {max_polls}")

    repo_result = await _gateway._resolve_repo(repo)
    if isinstance(repo_result, ErrorResult):
        return repo_result
    resolved_repo = str(repo_result.value)

    interval = max(poll_interval, _MIN_POLL_INTERVAL)
    budget = polls_within_budget(
        requested=max_polls,
        poll_interval=interval,
        initial_wait=0,
        overhead=_OVERHEAD_SECONDS,
    )
    granted = max(budget.polls, 1)

    baseline = [since_sha or ""]
    probe_errors: list[str] = []
    snapshots: list[PrSnapshot] = []

    async def probe() -> _Verdict | None:
        fetched = await _fetch_snapshot(repo=resolved_repo, pr_number=pr_number, until=until)
        if isinstance(fetched, ErrorResult):
            probe_errors.append(fetched.error)
            log.warning("pr_wait poll %d/%d failed: %s", len(probe_errors), granted, fetched.error)
            return None
        current: PrSnapshot = fetched.value
        snapshots.append(current)
        baseline[0] = baseline[0] or current.head_sha
        met = is_met(until=until, snapshot=current, baseline_sha=baseline[0], bot=bot)
        unreachable = not met and is_unreachable(until=until, snapshot=current)
        return _Verdict(met=met, unreachable=unreachable)

    run = await poll_until(
        probe=probe,
        done=lambda verdict: verdict is not None and (verdict.met or verdict.unreachable),
        deadline=Deadline.for_tool_call(overhead=_OVERHEAD_SECONDS),
        interval=interval,
        max_polls=granted,
    )

    if not snapshots:
        return err(f"every poll failed to read PR {pr_number}: {probe_errors[-1]}")
    snapshot = snapshots[-1]
    baseline_sha = baseline[0]
    last_good = run.last or _Verdict(met=False, unreachable=False)
    met, unreachable = last_good.met, last_good.unreachable
    polls = run.polls
    return ok(
        {
            "pr_number": pr_number,
            "repo": resolved_repo,
            "until": until,
            "met": met,
            "timed_out": not met and not unreachable,
            "unreachable": unreachable,
            "observed": _observed(
                snapshot=snapshot, until=until, baseline_sha=baseline_sha, bot=bot
            ),
            "polls": polls,
            "polls_granted": granted,
            "polls_requested": max_polls,
            "budget_clamped": budget.was_clamped,
            "probe_errors": probe_errors,
        }
    )
