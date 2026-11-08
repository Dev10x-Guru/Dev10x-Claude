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

from dev10x.coding.github import bot_review_config, bot_reviews
from dev10x.core.github import _gateway
from dev10x.domain.common.repository_ref import RepositoryRef
from dev10x.domain.common.result import ErrorResult, Result, SuccessResult, err, ok
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

_NEEDS_OPEN_PR = frozenset({"approved", "bot_at_head", "head_changed"})
_OVERHEAD_SECONDS = 60
_MIN_POLL_INTERVAL = 5


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
    bots: tuple[dict[str, Any], ...] = ()

    @property
    def is_open(self) -> bool:
        return self.state == "open"


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


def _bot_at_head(*, snapshot: PrSnapshot) -> dict[str, Any] | None:
    return next((row for row in snapshot.bots if row.get("at_head") is True), None)


def is_met(
    *,
    until: str,
    snapshot: PrSnapshot,
    baseline_sha: str,
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
    return _bot_at_head(snapshot=snapshot) is not None


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
    the verdict ``approved`` depends on.
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


async def _fetch_bots(*, repo: str, pr_number: int, bot: str | None) -> Result[tuple[dict, ...]]:
    """``bot_review_status``'s per-bot rows, narrowed to ``bot`` when named.

    One definition of "a bot reviewed the head" (GH-1857): a bot that
    only comments counts on the timestamp basis, and bot-ness comes from
    the GraphQL account type rather than a login suffix.
    """
    node = await bot_reviews.fetch_pull_request(ref=RepositoryRef.parse(repo), pr_number=pr_number)
    if not isinstance(node, SuccessResult):
        return node
    globs = (bot_review_config.normalize_login(bot),) if bot else ()
    rows = bot_reviews.summarize(pr=node.value, blocking_globs=globs)["bots"]
    return ok(tuple(row for row in rows if not bot or row["blocking"]))


async def _fetch_snapshot(
    *,
    repo: str,
    pr_number: int,
    until: str,
    bot: str | None,
) -> Result[PrSnapshot]:
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
    if until == "approved":
        listed = await _fetch_reviews(repo=repo, pr_number=pr_number)
        if isinstance(listed, ErrorResult):
            return listed
        reviews = listed.value
    bots: tuple[dict[str, Any], ...] = ()
    if until == "bot_at_head":
        fetched = await _fetch_bots(repo=repo, pr_number=pr_number, bot=bot)
        if isinstance(fetched, ErrorResult):
            return fetched
        bots = fetched.value
    return ok(
        PrSnapshot(
            state=str(payload.get("state") or ""),
            merged=bool(payload.get("merged")),
            head_sha=str((payload.get("head") or {}).get("sha") or ""),
            reviews=reviews,
            bots=bots,
        )
    )


def _observed(
    *,
    snapshot: PrSnapshot,
    until: str,
    baseline_sha: str,
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
        row = _bot_at_head(snapshot=snapshot)
        observed["bot_review"] = (
            None
            if row is None
            else {
                "login": row["login"],
                "kind": row["kind"],
                "state": row["review_state"],
                "commit_id": row["reviewed_sha"],
                "at_head_basis": row["at_head_basis"],
                "last_activity": row["last_activity"],
            }
        )
        observed["bots"] = [row["login"] for row in snapshot.bots]
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
        bot: Bot login or glob for ``bot_at_head`` (``[bot]`` suffix
            optional); any bot account when omitted. "At head" is
            ``bot_review_status``'s definition (GH-1857).

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
        fetched = await _fetch_snapshot(
            repo=resolved_repo, pr_number=pr_number, until=until, bot=bot
        )
        if isinstance(fetched, ErrorResult):
            probe_errors.append(fetched.error)
            log.warning("pr_wait poll %d/%d failed: %s", len(probe_errors), granted, fetched.error)
            return None
        current: PrSnapshot = fetched.value
        snapshots.append(current)
        baseline[0] = baseline[0] or current.head_sha
        met = is_met(until=until, snapshot=current, baseline_sha=baseline[0])
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
            "observed": _observed(snapshot=snapshot, until=until, baseline_sha=baseline_sha),
            "polls": polls,
            "polls_granted": granted,
            "polls_requested": max_polls,
            "budget_clamped": budget.was_clamped,
            "probe_errors": probe_errors,
        }
    )
