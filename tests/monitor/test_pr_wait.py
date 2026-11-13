"""pr_wait: one bounded wait for a PR condition (GH-1833)."""

from __future__ import annotations

import importlib
import json
from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from dev10x.domain.common.repository_ref import RepositoryRef
from dev10x.domain.common.result import ErrorResult, SuccessResult, err, ok
from dev10x.domain.transport_budget import tool_call_room

from dev10x.core.github import _gateway
from dev10x.mcp import server_cli as cli_server
from tests.fakers.clock import FakeClock
from tests.fakers.process import completed as _completed

pr_wait_module = importlib.import_module("dev10x.coding.monitor.pr_wait")
polling_module = importlib.import_module("dev10x.core.domain.polling")

PULL = "repos/owner/repo/pulls/7"
REVIEWS = f"{PULL}/reviews?per_page=100"
HEAD = "a" * 40
NEW_HEAD = "b" * 40


def _pull(*, state: str = "open", merged: bool = False, sha: str = HEAD) -> Any:
    return _completed(stdout=json.dumps({"state": state, "merged": merged, "head": {"sha": sha}}))


def _review(*, login: str, state: str, commit: str = HEAD, kind: str = "User") -> dict:
    return {"user": {"login": login, "type": kind}, "state": state, "commit_id": commit}


def _reviews(*items: dict) -> Any:
    return _completed(stdout=json.dumps(list(items)))


def _gql_review(
    *,
    login: str,
    kind: str = "Bot",
    commit: str = HEAD,
    state: str = "COMMENTED",
) -> dict:
    return {
        "author": {"__typename": kind, "login": login},
        "state": state,
        "body": "",
        "submittedAt": "2026-01-02T00:00:00Z",
        "commit": {"oid": commit},
    }


def _gql_comment(*, login: str, at: str, kind: str = "Bot") -> dict:
    return {"author": {"__typename": kind, "login": login}, "createdAt": at}


def _graphql(
    *,
    reviews: tuple[dict, ...] = (),
    comments: tuple[dict, ...] = (),
    older_comments: bool = False,
) -> Any:
    node = {
        "isDraft": False,
        "headRefOid": HEAD,
        "commits": {"nodes": [{"commit": {"oid": HEAD, "committedDate": "2026-01-01T00:00:00Z"}}]},
        "reviews": {"nodes": list(reviews)},
        "reviewThreads": {"nodes": []},
        "comments": {
            "pageInfo": {"hasPreviousPage": older_comments},
            "nodes": list(comments),
        },
    }
    return _completed(stdout=json.dumps({"data": {"repository": {"pullRequest": node}}}))


class Responder:
    def __init__(
        self,
        *,
        pulls: list[Any],
        reviews: Any | None = None,
        review_pages: list[Any] | None = None,
        graphql: Any | None = None,
    ) -> None:
        self.pulls = list(pulls)
        self.review_pages = review_pages or [reviews or _reviews()]
        self.graphql = graphql or _graphql()
        self.calls: list[str] = []

    async def __call__(self, endpoint: str, **_: Any) -> Any:
        self.calls.append(endpoint)
        if endpoint == "graphql":
            return self.graphql
        if endpoint.startswith(REVIEWS):
            _, _, page = endpoint.partition("&page=")
            return self.review_pages[int(page or 1) - 1]
        return self.pulls.pop(0) if len(self.pulls) > 1 else self.pulls[0]


@pytest.fixture(autouse=True)
def mock_resolve_repo() -> Iterator[AsyncMock]:
    with patch.object(
        _gateway,
        "_resolve_repo",
        new_callable=AsyncMock,
        return_value=ok(RepositoryRef(owner="owner", name="repo")),
    ) as mock:
        yield mock


class SlowResponder(Responder):
    """A responder whose PR reads take ``probe_seconds`` of fake time each."""

    def __init__(self, *, clock: FakeClock, probe_seconds: list[float], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.clock = clock
        self.probe_seconds = list(probe_seconds)

    async def __call__(self, endpoint: str, **kwargs: Any) -> Any:
        self.clock.advance(self.probe_seconds.pop(0))
        return await super().__call__(endpoint, **kwargs)


@pytest.fixture(autouse=True)
def clock() -> Iterator[FakeClock]:
    fake = FakeClock()
    with (
        patch.object(polling_module, "_clock", new=fake),
        patch.object(polling_module, "_sleep", new=fake.sleep),
    ):
        yield fake


@pytest.fixture
def room() -> float:
    return tool_call_room(overhead=pr_wait_module._OVERHEAD_SECONDS)


async def _wait(*, responder: Responder, **kwargs: Any) -> Any:
    with patch.object(_gateway, "_gh_api_raw", new=responder):
        return await pr_wait_module.pr_wait(pr_number=7, **kwargs)


class TestStateConditions:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("until", "state", "merged", "met", "unreachable"),
        [
            ("merged", "closed", True, True, False),
            ("merged", "closed", False, False, True),
            ("closed", "closed", False, True, False),
            ("closed", "closed", True, False, True),
            ("merged_or_closed", "closed", True, True, False),
            ("merged_or_closed", "closed", False, True, False),
            ("head_changed", "closed", False, False, True),
            ("approved", "closed", True, False, True),
            ("bot_at_head", "closed", False, False, True),
        ],
    )
    async def test_settles_on_first_poll(
        self,
        until: str,
        state: str,
        merged: bool,
        met: bool,
        unreachable: bool,
    ) -> None:
        result = await _wait(
            responder=Responder(pulls=[_pull(state=state, merged=merged)]), until=until
        )

        assert isinstance(result, SuccessResult)
        assert (result.value["met"], result.value["unreachable"]) == (met, unreachable)
        assert result.value["timed_out"] is False
        assert result.value["polls"] == 1

    @pytest.mark.asyncio
    async def test_keeps_polling_until_merge_lands(self, clock: FakeClock) -> None:
        responder = Responder(pulls=[_pull(), _pull(), _pull(state="closed", merged=True)])

        result = await _wait(responder=responder, until="merged", poll_interval=10)

        assert result.value["met"] is True
        assert result.value["polls"] == 3
        assert clock.sleeps == [10, 10]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("until", ["merged", "closed", "merged_or_closed"])
    async def test_open_pr_times_out_after_granted_polls(self, until: str) -> None:
        result = await _wait(responder=Responder(pulls=[_pull()]), until=until, max_polls=3)

        assert result.value["timed_out"] is True
        assert result.value["met"] is False
        assert result.value["polls"] == 3
        assert result.value["observed"] == {"state": "open", "merged": False, "head_sha": HEAD}


class TestHeadChanged:
    @pytest.mark.asyncio
    async def test_baseline_defaults_to_first_head(self) -> None:
        responder = Responder(pulls=[_pull(), _pull(sha=NEW_HEAD)])

        result = await _wait(responder=responder, until="head_changed")

        assert result.value["met"] is True
        assert result.value["observed"]["baseline_sha"] == HEAD
        assert result.value["observed"]["head_sha"] == NEW_HEAD

    @pytest.mark.asyncio
    async def test_explicit_since_sha_is_compared_on_first_poll(self) -> None:
        result = await _wait(
            responder=Responder(pulls=[_pull()]), until="head_changed", since_sha=NEW_HEAD
        )

        assert result.value["met"] is True
        assert result.value["polls"] == 1


class TestApproved:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("reviews", "met"),
        [
            ((_review(login="ann", state="APPROVED"),), True),
            ((_review(login="ann", state="COMMENTED"),), False),
            ((_review(login="ann", state="PENDING"),), False),
            (
                (
                    _review(login="ann", state="APPROVED"),
                    _review(login="ann", state="PENDING"),
                ),
                True,
            ),
            (
                (
                    _review(login="ann", state="APPROVED"),
                    _review(login="bob", state="CHANGES_REQUESTED"),
                ),
                False,
            ),
            (
                (
                    _review(login="ann", state="CHANGES_REQUESTED"),
                    _review(login="ann", state="APPROVED"),
                ),
                True,
            ),
            (
                (
                    _review(login="ann", state="APPROVED"),
                    _review(login="ann", state="COMMENTED"),
                ),
                True,
            ),
        ],
    )
    async def test_uses_each_reviewers_latest_verdict(
        self, reviews: tuple[dict, ...], met: bool
    ) -> None:
        result = await _wait(
            responder=Responder(pulls=[_pull()], reviews=_reviews(*reviews)),
            until="approved",
            max_polls=1,
        )

        assert result.value["met"] is met


class TestBotAtHead:
    """``bot_at_head`` delegates to ``bot_review_status`` (GH-1857)."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("review", "bot", "met"),
        [
            (_gql_review(login="claude"), None, True),
            (_gql_review(login="claude"), "claude", True),
            (_gql_review(login="claude"), "Claude[bot]", True),
            (_gql_review(login="claude"), "clau*", True),
            (_gql_review(login="other"), "claude", False),
            (_gql_review(login="ann", kind="User", state="APPROVED"), None, False),
            (_gql_review(login="claude-fan", kind="User"), None, False),
            (_gql_review(login="claude", commit=NEW_HEAD), None, False),
        ],
    )
    async def test_matches_only_a_bot_review_on_the_head(
        self, review: dict, bot: str | None, met: bool
    ) -> None:
        result = await _wait(
            responder=Responder(pulls=[_pull()], graphql=_graphql(reviews=(review,))),
            until="bot_at_head",
            bot=bot,
            max_polls=1,
        )

        assert result.value["met"] is met

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("at", "met"),
        [("2026-01-03T00:00:00Z", True), ("2025-12-31T00:00:00Z", False)],
    )
    async def test_a_comment_only_bot_counts_on_the_timestamp_basis(
        self, at: str, met: bool
    ) -> None:
        responder = Responder(
            pulls=[_pull()], graphql=_graphql(comments=(_gql_comment(login="sonar", at=at),))
        )

        result = await _wait(responder=responder, until="bot_at_head", max_polls=1)

        assert result.value["met"] is met

    @pytest.mark.asyncio
    async def test_reports_the_matching_row(self) -> None:
        result = await _wait(
            responder=Responder(
                pulls=[_pull()], graphql=_graphql(reviews=(_gql_review(login="claude"),))
            ),
            until="bot_at_head",
        )

        assert result.value["observed"]["bot_review"] == {
            "login": "claude",
            "kind": "review",
            "state": "COMMENTED",
            "commit_id": HEAD,
            "at_head_basis": "sha",
            "last_activity": "2026-01-02T00:00:00Z",
        }
        assert result.value["observed"]["bots"] == ["claude"]

    @pytest.mark.asyncio
    async def test_reports_none_when_no_bot_reviewed(self) -> None:
        result = await _wait(
            responder=Responder(pulls=[_pull()]), until="bot_at_head", max_polls=1
        )

        assert result.value["observed"]["bot_review"] is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize(("older_comments", "truncated"), [(True, ["comments"]), (False, [])])
    async def test_reports_windows_that_ran_past_their_page(
        self, older_comments: bool, truncated: list[str]
    ) -> None:
        responder = Responder(pulls=[_pull()], graphql=_graphql(older_comments=older_comments))

        result = await _wait(responder=responder, until="bot_at_head", max_polls=1)

        assert result.value["observed"]["truncated"] == truncated

    @pytest.mark.asyncio
    async def test_a_graphql_failure_is_a_probe_error(self) -> None:
        responder = Responder(pulls=[_pull()], graphql=_completed(returncode=1, stderr="HTTP 502"))

        result = await _wait(responder=responder, until="bot_at_head", max_polls=1)

        assert isinstance(result, ErrorResult)
        assert "HTTP 502" in result.error

    @pytest.mark.asyncio
    async def test_reviews_are_not_listed_over_rest(self) -> None:
        responder = Responder(pulls=[_pull()])

        await _wait(responder=responder, until="bot_at_head", max_polls=1)

        assert responder.calls == [PULL, "graphql"]


class TestBudget:
    @pytest.mark.asyncio
    async def test_default_request_is_clamped_by_transport_budget(self) -> None:
        result = await _wait(responder=Responder(pulls=[_pull()]), until="merged")

        assert result.value["polls_requested"] == 40
        assert result.value["polls_granted"] == 34
        assert result.value["budget_clamped"] is True

    @pytest.mark.asyncio
    async def test_slow_polls_stop_at_the_wall_clock_deadline(
        self, clock: FakeClock, room: float
    ) -> None:
        responder = SlowResponder(clock=clock, probe_seconds=[room / 2, room / 2], pulls=[_pull()])

        result = await _wait(responder=responder, until="merged")

        assert result.value["timed_out"] is True
        assert result.value["polls"] == 2
        assert clock.sleeps == [30]

    @pytest.mark.asyncio
    async def test_sleep_never_overshoots_the_deadline(
        self, clock: FakeClock, room: float
    ) -> None:
        responder = SlowResponder(clock=clock, probe_seconds=[room - 10.0, 0.0], pulls=[_pull()])

        await _wait(responder=responder, until="merged")

        assert clock.sleeps == [10.0]

    @pytest.mark.asyncio
    async def test_poll_interval_has_a_floor(self, clock: FakeClock) -> None:
        await _wait(responder=Responder(pulls=[_pull()]), until="merged", poll_interval=0)

        assert set(clock.sleeps) == {5}

    @pytest.mark.asyncio
    async def test_reviews_are_fetched_only_when_needed(self) -> None:
        responder = Responder(pulls=[_pull(state="closed", merged=True)])

        await _wait(responder=responder, until="merged")

        assert responder.calls == [PULL]


class TestProbeErrors:
    @pytest.mark.asyncio
    async def test_transient_failure_is_recorded_and_polling_continues(self) -> None:
        responder = Responder(
            pulls=[_completed(returncode=1, stderr="HTTP 502"), _pull(state="closed", merged=True)]
        )

        result = await _wait(responder=responder, until="merged")

        assert result.value["met"] is True
        assert result.value["probe_errors"] == ["HTTP 502"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("pull", "message"),
        [
            (_completed(returncode=1, stderr="HTTP 404"), "HTTP 404"),
            (_completed(returncode=1), "could not read PR 7"),
            (_completed(stdout="not json"), "could not parse PR 7"),
            (_completed(stdout="[]"), "unexpected PR 7 payload"),
        ],
    )
    async def test_every_poll_failing_is_an_error(self, pull: Any, message: str) -> None:
        result = await _wait(responder=Responder(pulls=[pull]), until="merged", max_polls=2)

        assert isinstance(result, ErrorResult)
        assert message in result.error

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("reviews", "message"),
        [
            (_completed(returncode=1, stderr="HTTP 403"), "HTTP 403"),
            (_completed(returncode=1), "could not list reviews"),
            (_completed(stdout="nope"), "could not parse reviews"),
        ],
    )
    async def test_review_listing_failure_is_an_error(self, reviews: Any, message: str) -> None:
        result = await _wait(
            responder=Responder(pulls=[_pull()], reviews=reviews), until="approved", max_polls=1
        )

        assert isinstance(result, ErrorResult)
        assert message in result.error

    @pytest.mark.asyncio
    async def test_reviews_are_read_across_pages(self) -> None:
        first_page = [_review(login=f"u{index}", state="APPROVED") for index in range(100)]
        last_page = [_review(login="bob", state="CHANGES_REQUESTED")]

        result = await _wait(
            responder=Responder(
                pulls=[_pull()], review_pages=[_reviews(*first_page), _reviews(*last_page)]
            ),
            until="approved",
            max_polls=1,
        )

        assert result.value["met"] is False
        assert result.value["observed"]["review_states"]["bob"] == "CHANGES_REQUESTED"

    @pytest.mark.asyncio
    async def test_review_listing_past_the_page_ceiling_is_an_error(self) -> None:
        full_page = _reviews(*[_review(login="ann", state="APPROVED")] * 100)

        result = await _wait(
            responder=Responder(pulls=[_pull()], review_pages=[full_page] * 10),
            until="approved",
            max_polls=1,
        )

        assert isinstance(result, ErrorResult)
        assert "more than 1000 reviews" in result.error

    @pytest.mark.asyncio
    async def test_non_list_reviews_payload_is_an_error(self) -> None:
        result = await _wait(
            responder=Responder(pulls=[_pull()], reviews=_completed(stdout="{}")),
            until="approved",
            max_polls=1,
        )

        assert isinstance(result, ErrorResult)
        assert "unexpected reviews for PR 7 shape" in result.error


class TestValidation:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            ({"until": "deployed"}, "until must be one of"),
            ({"until": "merged", "max_polls": 0}, "max_polls must be at least 1"),
        ],
    )
    async def test_rejects_bad_arguments(self, kwargs: dict, message: str) -> None:
        result = await pr_wait_module.pr_wait(pr_number=7, **kwargs)

        assert isinstance(result, ErrorResult)
        assert message in result.error

    @pytest.mark.asyncio
    async def test_rejects_non_positive_pr_number(self) -> None:
        result = await pr_wait_module.pr_wait(pr_number=0, until="merged")

        assert isinstance(result, ErrorResult)
        assert "pr_number must be positive" in result.error

    @pytest.mark.asyncio
    async def test_repo_resolution_error_is_returned(self, mock_resolve_repo: AsyncMock) -> None:
        mock_resolve_repo.return_value = err("no repo")

        result = await pr_wait_module.pr_wait(pr_number=7, until="merged")

        assert isinstance(result, ErrorResult)
        assert result.error == "no repo"


class TestMcpHandler:
    @pytest.mark.asyncio
    async def test_routes_through_to_wire(self) -> None:
        with patch.object(
            pr_wait_module, "pr_wait", new_callable=AsyncMock, return_value=ok({"met": True})
        ) as mock:
            payload = await cli_server.pr_wait(pr_number=7, until="merged", bot="claude")

        assert payload == {"met": True}
        assert mock.await_args.kwargs["bot"] == "claude"
