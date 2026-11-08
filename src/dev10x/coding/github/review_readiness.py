"""Was a PR ready when review was requested, or did it go red later? (GH-1834)

A reviewer who opens a PR with red CI, an unresolved thread, a bot that
never saw the head, or a draft flag spends time on something that was
never ready. The audit tells two cases apart by event time:

- ``SENT-NOT-READY`` — at least one current problem already existed when
  the latest review request was made;
- ``WENT-RED-AFTER`` — every current problem appeared after it.

:func:`collect_problems` and :func:`classify` are pure functions over one
``pullRequest`` GraphQL node, so recorded payloads test them directly.
A CI problem starts where each not-green check's current run of
not-green attempts began, read from the check-run history, so a check
already red at the request and re-run since is dated before it, and a
check that went red on a re-run after a green attempt is dated after.
A bot problem starts at the head's arrival: GitHub records no push time
for a commit, so that is the force-push event that produced it, else
the earliest CI start on it, else its committed date
(``head_arrived_basis`` names which). Anything with no start time
becomes its own problem with an unknown start, so it is listed on its
own rather than folded into a dated one.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any

from dev10x.coding.github import bot_review_config, bot_reviews
from dev10x.core.github import _gateway
from dev10x.domain.common.result import ErrorResult, Result, SuccessResult, err, ok

VERDICT_READY = "READY"
VERDICT_SENT_NOT_READY = "SENT-NOT-READY"
VERDICT_WENT_RED_AFTER = "WENT-RED-AFTER"
VERDICT_UNKNOWN = "UNKNOWN"

KIND_DRAFT = "draft"
KIND_CI = "ci"
KIND_THREAD = "thread"
KIND_BOT = "bot"

MAX_LIMIT = 50
_NOT_GREEN = frozenset({"FAILURE", "ERROR", "PENDING", "EXPECTED"})
_GREEN_CONCLUSIONS = frozenset({"SUCCESS", "NEUTRAL", "SKIPPED"})
_DETAIL_NAMES = 5

_AUDIT_FIELDS = (
    "number title url createdAt "
    "readinessEvents: timelineItems(last: 100, itemTypes: [REVIEW_REQUESTED_EVENT, "
    "CONVERT_TO_DRAFT_EVENT, HEAD_REF_FORCE_PUSHED_EVENT]) { "
    "pageInfo { hasPreviousPage } nodes { __typename "
    "... on ReviewRequestedEvent { createdAt } "
    "... on ConvertToDraftEvent { createdAt } "
    "... on HeadRefForcePushedEvent { createdAt afterCommit { oid } } } } "
    "headCommit: commits(last: 1) { nodes { commit { oid "
    "statusCheckRollup { state contexts(first: 100) { "
    "pageInfo { hasNextPage } nodes { __typename "
    "... on CheckRun { name status conclusion startedAt } "
    "... on StatusContext { context state createdAt } } } } "
    "checkSuites(first: 20) { pageInfo { hasNextPage } nodes { "
    "checkRuns(first: 50, filterBy: {checkType: ALL}) { pageInfo { hasNextPage } "
    "nodes { name status conclusion startedAt } } } } } } } "
)
_PR_SELECTION = f"{bot_reviews.PR_FIELDS}{_AUDIT_FIELDS}"


@dataclass(frozen=True)
class Problem:
    kind: str
    detail: str
    since: str | None


def classify(*, requested_at: str | None, problems: list[Problem]) -> str:
    """Name when the PR's current problems appeared relative to the request."""
    if not problems:
        return VERDICT_READY
    if requested_at is None:
        return VERDICT_UNKNOWN
    if any(p.since is not None and p.since <= requested_at for p in problems):
        return VERDICT_SENT_NOT_READY
    if any(p.since is None for p in problems):
        return VERDICT_UNKNOWN
    return VERDICT_WENT_RED_AFTER


def _events(*, pr: dict[str, Any], typename: str) -> list[dict[str, Any]]:
    return [
        n
        for n in bot_reviews.connection_nodes(pr.get("readinessEvents"))
        if n.get("__typename") == typename
    ]


def _latest_event_at(*, pr: dict[str, Any], typename: str) -> str | None:
    return bot_reviews.latest_timestamp(
        *(e.get("createdAt") for e in _events(pr=pr, typename=typename))
    )


def _head_commit(*, pr: dict[str, Any]) -> dict[str, Any]:
    return bot_reviews.first_node(pr.get("headCommit")).get("commit") or {}


def _contexts(*, pr: dict[str, Any]) -> list[dict[str, Any]]:
    rollup = _head_commit(pr=pr).get("statusCheckRollup") or {}
    return bot_reviews.connection_nodes(rollup.get("contexts"))


def _context_started_at(context: dict[str, Any]) -> str | None:
    return context.get("startedAt") or context.get("createdAt")


def head_arrival(*, pr: dict[str, Any]) -> tuple[str | None, str | None]:
    """Return ``(timestamp, basis)`` for when the head commit reached the PR."""
    head_sha = pr.get("headRefOid")
    forced = [
        e.get("createdAt")
        for e in _events(pr=pr, typename="HeadRefForcePushedEvent")
        if (e.get("afterCommit") or {}).get("oid") == head_sha
    ]
    forced_at = bot_reviews.latest_timestamp(*forced)
    if forced_at:
        return forced_at, "force_push"
    starts = [s for s in (_context_started_at(c) for c in _contexts(pr=pr)) if s]
    if starts:
        return min(starts), "ci_start"
    committed = (bot_reviews.first_node(pr.get("commits")).get("commit") or {}).get(
        "committedDate"
    )
    if committed:
        return committed, "committed"
    return None, None


def _not_green_label(context: dict[str, Any]) -> str | None:
    if context.get("__typename") == "CheckRun":
        if context.get("status") != "COMPLETED":
            return f"{context.get('name')} (pending)"
        if context.get("conclusion") not in _GREEN_CONCLUSIONS:
            return f"{context.get('name')} ({str(context.get('conclusion')).lower()})"
        return None
    if context.get("state") != "SUCCESS":
        return f"{context.get('context')} ({str(context.get('state')).lower()})"
    return None


def _check_list(*, names: list[str]) -> str:
    shown = ", ".join(names[:_DETAIL_NAMES])
    more = f" (+{len(names) - _DETAIL_NAMES} more)" if len(names) > _DETAIL_NAMES else ""
    return f"{shown}{more}"


@dataclass(frozen=True)
class RunHistory:
    runs: dict[str, list[dict[str, Any]]]
    runs_truncated: bool
    suites_truncated: bool

    def complete_for(self, *, name: str) -> list[dict[str, Any]] | None:
        """Every attempt of ``name``, or None when the window may have cut some off."""
        if self.suites_truncated or self.runs_truncated:
            return None
        return self.runs.get(name) or None


def _has_next_page(connection: Any) -> bool:
    page_info = connection.get("pageInfo") if isinstance(connection, dict) else None
    return bool(isinstance(page_info, dict) and page_info.get("hasNextPage"))


def _run_history(*, pr: dict[str, Any]) -> RunHistory:
    suites = _head_commit(pr=pr).get("checkSuites")
    runs: dict[str, list[dict[str, Any]]] = {}
    runs_truncated = False
    for suite in bot_reviews.connection_nodes(suites):
        for run in bot_reviews.connection_nodes(suite.get("checkRuns")):
            runs.setdefault(str(run.get("name")), []).append(run)
        runs_truncated = runs_truncated or _has_next_page(suite.get("checkRuns"))
    return RunHistory(
        runs=runs,
        runs_truncated=runs_truncated,
        suites_truncated=_has_next_page(suites),
    )


def _history_truncated(*, pr: dict[str, Any]) -> list[str]:
    history = _run_history(pr=pr)
    truncated = ["checkSuites"] if history.suites_truncated else []
    if history.runs_truncated:
        truncated.append("checkRuns")
    return truncated


def _red_streak_start(*, context: dict[str, Any], history: RunHistory) -> str | None:
    """When the check's current unbroken run of not-green attempts began.

    A status context has no attempt history, so its own time stands. A
    check run whose history is missing or may be cut off has an unknown
    start: dating it from the attempts that happen to be visible could
    put a streak that began before the request after it.
    """
    if context.get("__typename") != "CheckRun":
        return _context_started_at(context)
    attempts = history.complete_for(name=str(context.get("name")))
    if attempts is None or any(not run.get("startedAt") for run in attempts):
        return None
    start: str | None = None
    for run in sorted(attempts, key=lambda r: r["startedAt"], reverse=True):
        if _not_green_label(run | {"__typename": "CheckRun"}) is None:
            break
        start = run["startedAt"]
    return start


def _ci_problems(*, pr: dict[str, Any]) -> list[Problem]:
    rollup = _head_commit(pr=pr).get("statusCheckRollup") or {}
    state = rollup.get("state")
    if state not in _NOT_GREEN:
        return []
    labelled = [(label, c) for c in _contexts(pr=pr) if (label := _not_green_label(c))]
    if not labelled:
        return [Problem(kind=KIND_CI, detail=f"CI {state.lower()}: no check named", since=None)]
    history = _run_history(pr=pr)
    starts = [(label, _red_streak_start(context=c, history=history)) for label, c in labelled]
    dated = [(label, start) for label, start in starts if start]
    undated = [label for label, start in starts if not start]
    problems: list[Problem] = []
    if dated:
        problems.append(
            Problem(
                kind=KIND_CI,
                detail=f"CI {state.lower()}: {_check_list(names=[n for n, _ in dated])}",
                since=min(start for _, start in dated),
            )
        )
    if undated:
        problems.append(
            Problem(
                kind=KIND_CI,
                detail=f"CI {state.lower()} with no start time: {_check_list(names=undated)}",
                since=None,
            )
        )
    return problems


def _thread_problems(*, pr: dict[str, Any]) -> list[Problem]:
    opened = [
        bot_reviews.first_node(t.get("first")).get("createdAt")
        for t in bot_reviews.connection_nodes(pr.get("reviewThreads"))
        if not t.get("isResolved")
    ]
    dated = [o for o in opened if o]
    undated = len(opened) - len(dated)
    problems: list[Problem] = []
    if dated:
        problems.append(
            Problem(
                kind=KIND_THREAD,
                detail=f"{len(dated)} unresolved review thread(s)",
                since=min(dated),
            )
        )
    if undated:
        problems.append(
            Problem(
                kind=KIND_THREAD,
                detail=f"{undated} unresolved review thread(s) with no start time",
                since=None,
            )
        )
    return problems


def _bot_problem(
    *,
    pr: dict[str, Any],
    blocking_globs: tuple[str, ...],
    head_at: str | None,
) -> Problem | None:
    report = bot_reviews.summarize(pr=pr, blocking_globs=blocking_globs)
    behind = [b["login"] for b in report["bots"] if b["blocking"] and b["at_head"] is not True]
    lagging = [*report["missing_blocking_bots"], *behind]
    if not lagging:
        return None
    return Problem(
        kind=KIND_BOT,
        detail=f"blocking bot not at head: {', '.join(lagging)}",
        since=head_at,
    )


def collect_problems(
    *,
    pr: dict[str, Any],
    blocking_globs: tuple[str, ...],
) -> list[Problem]:
    """List what currently stops ``pr`` being ready, each with when it began."""
    head_at, _ = head_arrival(pr=pr)
    problems: list[Problem] = []
    if pr.get("isDraft"):
        since = _latest_event_at(pr=pr, typename="ConvertToDraftEvent") or pr.get("createdAt")
        problems.append(Problem(kind=KIND_DRAFT, detail="PR is a draft", since=since))
    problems.extend(_ci_problems(pr=pr))
    problems.extend(_thread_problems(pr=pr))
    bot = _bot_problem(pr=pr, blocking_globs=blocking_globs, head_at=head_at)
    if bot is not None:
        problems.append(bot)
    return problems


def _truncated(*, pr: dict[str, Any]) -> list[str]:
    truncated = bot_reviews.truncated_connections(pr=pr)
    page_info = (pr.get("readinessEvents") or {}).get("pageInfo") or {}
    if page_info.get("hasPreviousPage"):
        truncated.append("timelineItems")
    rollup = _head_commit(pr=pr).get("statusCheckRollup") or {}
    if _has_next_page(rollup.get("contexts")):
        truncated.append("contexts")
    return [*truncated, *_history_truncated(pr=pr)]


def audit_pr(*, pr: dict[str, Any], blocking_globs: tuple[str, ...]) -> dict[str, Any]:
    """Fold one ``pullRequest`` node into an audit row."""
    requested_at = _latest_event_at(pr=pr, typename="ReviewRequestedEvent")
    head_at, head_basis = head_arrival(pr=pr)
    problems = collect_problems(pr=pr, blocking_globs=blocking_globs)
    return {
        "number": pr.get("number"),
        "title": pr.get("title"),
        "url": pr.get("url"),
        "is_draft": bool(pr.get("isDraft")),
        "requested_at": requested_at,
        "head_arrived_at": head_at,
        "head_arrived_basis": head_basis,
        "verdict": classify(requested_at=requested_at, problems=problems),
        "problems": [asdict(p) for p in problems],
        "truncated": _truncated(pr=pr),
    }


def _query(*, owner: str, name: str, pr_number: int | None, limit: int) -> str:
    repository = f"repository(owner: {json.dumps(owner)}, name: {json.dumps(name)})"
    if pr_number is not None:
        return (
            f"query {{ {repository} {{ pullRequest(number: {pr_number}) {{ {_PR_SELECTION}}} }} }}"
        )
    return (
        f"query {{ {repository} {{ pullRequests(states: OPEN, first: {limit}, "
        "orderBy: {field: UPDATED_AT, direction: DESC}) { "
        f"pageInfo {{ hasNextPage }} nodes {{ {_PR_SELECTION}}} }} }} }}"
    )


def _pull_requests(
    *,
    repository: dict[str, Any],
    pr_number: int | None,
) -> Result[tuple[list[dict[str, Any]], bool]]:
    if pr_number is not None:
        pr = repository.get("pullRequest")
        if not isinstance(pr, dict):
            return err(f"PR #{pr_number} not found")
        return ok(([pr], False))
    connection = repository.get("pullRequests")
    if not isinstance(connection, dict):
        return err("pullRequests missing from GitHub response")
    more = bool((connection.get("pageInfo") or {}).get("hasNextPage"))
    return ok((bot_reviews.connection_nodes(connection), more))


async def review_readiness_audit(
    *,
    repo: str | None = None,
    pr_number: int | None = None,
    limit: int = 20,
) -> Result[dict[str, Any]]:
    repo_result = await _gateway._resolve_repo(repo)
    if isinstance(repo_result, ErrorResult):
        return repo_result
    ref = repo_result.value
    config = bot_review_config.resolve_blocking_bots(repo=str(ref))
    if not isinstance(config, SuccessResult):
        return config

    bounded = max(1, min(limit, MAX_LIMIT))
    repository = await bot_reviews.fetch_repository_node(
        query=_query(owner=ref.owner, name=ref.name, pr_number=pr_number, limit=bounded)
    )
    if not isinstance(repository, SuccessResult):
        return repository
    found = _pull_requests(repository=repository.value, pr_number=pr_number)
    if not isinstance(found, SuccessResult):
        return err(f"{found.error} in {ref}")
    nodes, more = found.value

    rows = [audit_pr(pr=pr, blocking_globs=config.value.globs) for pr in nodes]
    # A named PR is reported even before anyone was asked to review it.
    requested = rows if pr_number is not None else [r for r in rows if r["requested_at"]]
    return ok(
        {
            "repo": str(ref),
            "scanned": len(rows),
            "more_open_prs": more,
            "prs": requested,
            "counts": dict(Counter(r["verdict"] for r in requested)),
            "blocking_bots": list(config.value.globs),
            "config_source": config.value.source,
        }
    )
