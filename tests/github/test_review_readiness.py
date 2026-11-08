"""review_readiness_audit: was a PR ready when review was requested? (GH-1834)"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from dev10x.domain.common.result import ErrorResult, Result, SuccessResult, err

from dev10x.coding.github import review_readiness as rr
from dev10x.coding.github.review_readiness import Problem
from dev10x.core.github import _gateway
from dev10x.mcp import server_cli as cli_server
from tests.github.graphql_doubles import completed, write_merge_settings

FIXTURES = Path(__file__).parents[1] / "fixtures" / "review_readiness"
REQUESTED = "2026-11-01T09:00:00Z"


def _payload() -> dict[str, Any]:
    return json.loads((FIXTURES / "open_prs.json").read_text(encoding="utf-8"))


def _pr(*, number: int) -> dict[str, Any]:
    nodes = _payload()["data"]["repository"]["pullRequests"]["nodes"]
    return next(n for n in nodes if n["number"] == number)


def _row(*, number: int) -> dict[str, Any]:
    return rr.audit_pr(pr=_pr(number=number), blocking_globs=("claude",))


def _pr_with_ci(
    *,
    state: str,
    contexts: list[dict[str, Any]],
    runs: list[dict[str, Any]],
    suites_more: bool = False,
    runs_more: bool = False,
) -> dict[str, Any]:
    check_runs = {"pageInfo": {"hasNextPage": runs_more}, "nodes": runs}
    commit = {
        "statusCheckRollup": {"state": state, "contexts": {"nodes": contexts}},
        "checkSuites": {
            "pageInfo": {"hasNextPage": suites_more},
            "nodes": [{"checkRuns": check_runs}],
        },
    }
    return {"headCommit": {"nodes": [{"commit": commit}]}}


def _kinds(*, row: dict[str, Any]) -> list[str]:
    return [p["kind"] for p in row["problems"]]


class TestClassify:
    @pytest.mark.parametrize(
        ("requested_at", "sinces", "expected"),
        [
            (REQUESTED, [], rr.VERDICT_READY),
            (None, [], rr.VERDICT_READY),
            (None, ["2026-11-01T08:00:00Z"], rr.VERDICT_UNKNOWN),
            (REQUESTED, ["2026-11-01T08:00:00Z"], rr.VERDICT_SENT_NOT_READY),
            (REQUESTED, [REQUESTED], rr.VERDICT_SENT_NOT_READY),
            (REQUESTED, ["2026-11-01T10:00:00Z"], rr.VERDICT_WENT_RED_AFTER),
            (
                REQUESTED,
                ["2026-11-01T10:00:00Z", "2026-11-01T08:00:00Z"],
                rr.VERDICT_SENT_NOT_READY,
            ),
            (REQUESTED, [None], rr.VERDICT_UNKNOWN),
            (REQUESTED, [None, "2026-11-01T08:00:00Z"], rr.VERDICT_SENT_NOT_READY),
            (REQUESTED, [None, "2026-11-01T10:00:00Z"], rr.VERDICT_UNKNOWN),
        ],
        ids=[
            "no-problems",
            "no-problems-no-request",
            "problem-no-request",
            "problem-before",
            "problem-at-request",
            "problem-after",
            "one-before-wins",
            "unknown-since",
            "known-before-beats-unknown",
            "unknown-blocks-went-red",
        ],
    )
    def test_verdict(
        self,
        requested_at: str | None,
        sinces: list[str | None],
        expected: str,
    ) -> None:
        problems = [Problem(kind=rr.KIND_CI, detail="x", since=s) for s in sinces]

        assert rr.classify(requested_at=requested_at, problems=problems) == expected


class TestSentWhileCiWasRed:
    @pytest.fixture
    def row(self) -> dict[str, Any]:
        return _row(number=10)

    def test_verdict(self, row: dict[str, Any]) -> None:
        assert row["verdict"] == rr.VERDICT_SENT_NOT_READY

    def test_lists_ci_and_open_thread(self, row: dict[str, Any]) -> None:
        assert _kinds(row=row) == [rr.KIND_CI, rr.KIND_THREAD]

    def test_ci_detail_names_only_the_failing_check(self, row: dict[str, Any]) -> None:
        assert row["problems"][0]["detail"] == "CI failure: pytest (failure)"

    def test_head_arrival_is_the_first_ci_start(self, row: dict[str, Any]) -> None:
        assert (row["head_arrived_at"], row["head_arrived_basis"]) == (
            "2026-11-01T08:40:00Z",
            "ci_start",
        )

    def test_resolved_thread_is_not_counted(self, row: dict[str, Any]) -> None:
        assert row["problems"][1] == {
            "kind": rr.KIND_THREAD,
            "detail": "1 unresolved review thread(s)",
            "since": "2026-11-01T09:10:00Z",
        }


class TestWentRedAfterForcePush:
    @pytest.fixture
    def row(self) -> dict[str, Any]:
        return _row(number=11)

    def test_verdict(self, row: dict[str, Any]) -> None:
        assert row["verdict"] == rr.VERDICT_WENT_RED_AFTER

    def test_head_arrival_is_the_force_push(self, row: dict[str, Any]) -> None:
        assert (row["head_arrived_at"], row["head_arrived_basis"]) == (
            "2026-11-02T10:00:00Z",
            "force_push",
        )

    def test_pending_and_status_contexts_are_named(self, row: dict[str, Any]) -> None:
        assert row["problems"][0]["detail"] == ("CI pending: pytest (pending), ci/legacy (error)")

    def test_stale_blocking_bot_is_a_problem(self, row: dict[str, Any]) -> None:
        assert row["problems"][1] == {
            "kind": rr.KIND_BOT,
            "detail": "blocking bot not at head: claude",
            "since": "2026-11-02T10:00:00Z",
        }


class TestReady:
    def test_no_problems(self) -> None:
        row = _row(number=12)

        assert (row["verdict"], row["problems"]) == (rr.VERDICT_READY, [])


class TestDraftedAfterRequest:
    @pytest.fixture
    def row(self) -> dict[str, Any]:
        return _row(number=14)

    def test_verdict(self, row: dict[str, Any]) -> None:
        assert row["verdict"] == rr.VERDICT_WENT_RED_AFTER

    def test_draft_since_conversion(self, row: dict[str, Any]) -> None:
        assert row["problems"] == [
            {"kind": rr.KIND_DRAFT, "detail": "PR is a draft", "since": "2026-11-05T11:00:00Z"}
        ]

    def test_head_arrival_falls_back_to_commit_date(self, row: dict[str, Any]) -> None:
        assert row["head_arrived_basis"] == "committed"

    def test_reports_truncated_timeline(self, row: dict[str, Any]) -> None:
        assert row["truncated"] == ["timelineItems"]


class TestNeverRequested:
    @pytest.fixture
    def row(self) -> dict[str, Any]:
        return _row(number=13)

    def test_no_request_time(self, row: dict[str, Any]) -> None:
        assert row["requested_at"] is None

    def test_draft_since_creation(self, row: dict[str, Any]) -> None:
        assert row["problems"][0]["since"] == "2026-11-04T08:00:00Z"

    def test_verdict_is_unknown(self, row: dict[str, Any]) -> None:
        assert row["verdict"] == rr.VERDICT_UNKNOWN


class TestEdgeShapes:
    def test_ci_without_named_contexts(self) -> None:
        pr = {
            "headCommit": {
                "nodes": [{"commit": {"statusCheckRollup": {"state": "EXPECTED", "contexts": {}}}}]
            }
        }

        problems = rr.collect_problems(pr=pr, blocking_globs=())

        assert problems == [
            Problem(kind=rr.KIND_CI, detail="CI expected: no check named", since=None)
        ]

    def test_ci_detail_caps_named_checks(self) -> None:
        contexts = [
            {"__typename": "StatusContext", "context": f"c{i}", "state": "FAILURE"}
            for i in range(7)
        ]
        pr = {
            "headCommit": {
                "nodes": [
                    {
                        "commit": {
                            "statusCheckRollup": {
                                "state": "FAILURE",
                                "contexts": {"nodes": contexts},
                            }
                        }
                    }
                ]
            }
        }

        detail = rr.collect_problems(pr=pr, blocking_globs=())[0].detail

        assert detail.endswith("c4 (failure) (+2 more)")

    def test_ci_is_dated_by_the_failing_check_not_its_siblings(self) -> None:
        contexts = [
            {
                "__typename": "CheckRun",
                "name": "lint",
                "status": "COMPLETED",
                "conclusion": "SUCCESS",
                "startedAt": "2026-11-01T08:00:00Z",
            },
            {
                "__typename": "StatusContext",
                "context": "ci/legacy",
                "state": "SUCCESS",
                "createdAt": "2026-11-01T07:00:00Z",
            },
            {
                "__typename": "CheckRun",
                "name": "pytest",
                "status": "COMPLETED",
                "conclusion": "FAILURE",
                "startedAt": "2026-11-01T10:00:00Z",
            },
        ]
        runs = [
            {k: v for k, v in c.items() if k != "__typename"}
            for c in contexts
            if c["__typename"] == "CheckRun"
        ]
        pr = _pr_with_ci(state="FAILURE", contexts=contexts, runs=runs)

        problems = rr.collect_problems(pr=pr, blocking_globs=())

        assert problems[0].since == "2026-11-01T10:00:00Z"

    @pytest.mark.parametrize(
        ("history", "since", "verdict"),
        [
            (
                [("FAILURE", "2026-11-01T08:00:00Z"), ("FAILURE", "2026-11-01T10:00:00Z")],
                "2026-11-01T08:00:00Z",
                rr.VERDICT_SENT_NOT_READY,
            ),
            (
                [("SUCCESS", "2026-11-01T08:00:00Z"), ("FAILURE", "2026-11-01T10:00:00Z")],
                "2026-11-01T10:00:00Z",
                rr.VERDICT_WENT_RED_AFTER,
            ),
            (
                [("FAILURE", "2026-11-01T08:50:00Z")],
                "2026-11-01T08:50:00Z",
                rr.VERDICT_SENT_NOT_READY,
            ),
            (
                [("FAILURE", None), ("FAILURE", "2026-11-01T10:00:00Z")],
                None,
                rr.VERDICT_UNKNOWN,
            ),
        ],
        ids=[
            "red-at-request-then-rerun-red",
            "green-at-request-then-rerun-red",
            "single-run-started-before-request",
            "undated-attempt-is-unknown",
        ],
    )
    def test_ci_is_dated_by_the_current_red_streak(
        self,
        history: list[tuple[str, str | None]],
        since: str | None,
        verdict: str,
    ) -> None:
        runs = [
            {"name": "pytest", "status": "COMPLETED", "conclusion": c, "startedAt": s}
            for c, s in history
        ]
        latest = runs[-1] | {"__typename": "CheckRun"}
        pr = _pr_with_ci(state="FAILURE", contexts=[latest], runs=runs)

        problems = rr.collect_problems(pr=pr, blocking_globs=())

        assert (problems[0].since, rr.classify(requested_at=REQUESTED, problems=problems)) == (
            since,
            verdict,
        )

    @pytest.mark.parametrize(
        ("suites_more", "runs_more", "history_name"),
        [
            (False, False, "lint"),
            (True, False, "pytest"),
            (False, True, "pytest"),
        ],
        ids=["missing-from-history", "more-suites-than-fetched", "more-runs-than-fetched"],
    )
    def test_incomplete_history_gives_an_unknown_start(
        self,
        suites_more: bool,
        runs_more: bool,
        history_name: str,
    ) -> None:
        latest = {
            "__typename": "CheckRun",
            "name": "pytest",
            "status": "COMPLETED",
            "conclusion": "FAILURE",
            "startedAt": "2026-11-01T10:00:00Z",
        }
        run = latest | {"name": history_name}
        pr = _pr_with_ci(
            state="FAILURE",
            contexts=[latest],
            runs=[run],
            suites_more=suites_more,
            runs_more=runs_more,
        )

        problems = rr.collect_problems(pr=pr, blocking_globs=())

        assert (problems[0].since, rr.classify(requested_at=REQUESTED, problems=problems)) == (
            None,
            rr.VERDICT_UNKNOWN,
        )

    def test_run_window_cut_in_another_suite_gives_an_unknown_start(self) -> None:
        failing = {
            "name": "pytest",
            "status": "COMPLETED",
            "conclusion": "FAILURE",
            "startedAt": "2026-11-05T10:00:00Z",
        }
        pr = _pr_with_ci(
            state="FAILURE",
            contexts=[failing | {"__typename": "CheckRun"}],
            runs=[failing],
        )
        suites = pr["headCommit"]["nodes"][0]["commit"]["checkSuites"]["nodes"]
        suites.append({"checkRuns": {"pageInfo": {"hasNextPage": True}, "nodes": []}})

        problems = rr.collect_problems(pr=pr, blocking_globs=())

        assert problems[0].since is None

    @pytest.mark.parametrize(
        ("suites_more", "runs_more", "expected"),
        [
            (False, False, []),
            (True, False, ["checkSuites"]),
            (False, True, ["checkRuns"]),
        ],
        ids=["complete", "suites-cut", "runs-cut"],
    )
    def test_reports_check_history_truncation(
        self,
        suites_more: bool,
        runs_more: bool,
        expected: list[str],
    ) -> None:
        run = {"name": "pytest", "status": "COMPLETED", "conclusion": "SUCCESS", "startedAt": "t"}
        pr = _pr_with_ci(
            state="SUCCESS",
            contexts=[],
            runs=[run],
            suites_more=suites_more,
            runs_more=runs_more,
        )

        assert rr.audit_pr(pr=pr, blocking_globs=())["truncated"] == expected

    def test_reports_a_cut_suite_with_no_visible_runs(self) -> None:
        pr = _pr_with_ci(state="SUCCESS", contexts=[], runs=[], runs_more=True)

        assert rr.audit_pr(pr=pr, blocking_globs=())["truncated"] == ["checkRuns"]

    def test_reports_status_context_truncation(self) -> None:
        pr = _pr_with_ci(state="FAILURE", contexts=[], runs=[])
        rollup = pr["headCommit"]["nodes"][0]["commit"]["statusCheckRollup"]
        rollup["contexts"]["pageInfo"] = {"hasNextPage": True}

        assert rr.audit_pr(pr=pr, blocking_globs=())["truncated"] == ["contexts"]

    @pytest.fixture
    def undated_check_problems(self) -> list[Problem]:
        contexts = [
            {
                "__typename": "CheckRun",
                "name": "pytest",
                "status": "COMPLETED",
                "conclusion": "FAILURE",
                "startedAt": "2026-11-01T10:00:00Z",
            },
            {"__typename": "CheckRun", "name": "e2e", "status": "QUEUED", "startedAt": None},
        ]
        runs = [{k: v for k, v in c.items() if k != "__typename"} for c in contexts]
        pr = _pr_with_ci(state="PENDING", contexts=contexts, runs=runs)
        return rr.collect_problems(pr=pr, blocking_globs=())

    def test_undated_failing_check_is_not_hidden_behind_a_later_one(
        self,
        undated_check_problems: list[Problem],
    ) -> None:
        assert [(p.detail, p.since) for p in undated_check_problems] == [
            ("CI pending: pytest (failure)", "2026-11-01T10:00:00Z"),
            ("CI pending with no start time: e2e (pending)", None),
        ]

    def test_undated_failing_check_classifies_unknown(
        self,
        undated_check_problems: list[Problem],
    ) -> None:
        verdict = rr.classify(requested_at=REQUESTED, problems=undated_check_problems)

        assert verdict == rr.VERDICT_UNKNOWN

    def test_thread_without_timestamp_has_unknown_since(self) -> None:
        pr = {"reviewThreads": {"nodes": [{"isResolved": False, "first": {"nodes": []}}]}}

        assert rr.collect_problems(pr=pr, blocking_globs=()) == [
            Problem(
                kind=rr.KIND_THREAD,
                detail="1 unresolved review thread(s) with no start time",
                since=None,
            )
        ]

    def test_undated_thread_is_not_hidden_behind_a_later_one(self) -> None:
        threads = [
            {"isResolved": False, "first": {"nodes": [{"createdAt": "2026-11-01T10:00:00Z"}]}},
            {"isResolved": False, "first": {"nodes": []}},
        ]
        problems = rr.collect_problems(pr={"reviewThreads": {"nodes": threads}}, blocking_globs=())

        assert rr.classify(requested_at=REQUESTED, problems=problems) == rr.VERDICT_UNKNOWN

    def test_missing_blocking_bot_is_a_problem(self) -> None:
        problems = rr.collect_problems(pr={}, blocking_globs=("claude",))

        assert problems == [
            Problem(kind=rr.KIND_BOT, detail="blocking bot not at head: claude", since=None)
        ]

    def test_empty_pr_has_no_arrival(self) -> None:
        assert rr.head_arrival(pr={}) == (None, None)

    def test_force_push_to_another_sha_is_ignored(self) -> None:
        pr = {
            "headRefOid": "b",
            "readinessEvents": {
                "nodes": [
                    {
                        "__typename": "HeadRefForcePushedEvent",
                        "createdAt": "2026-11-01T10:00:00Z",
                        "afterCommit": {"oid": "a"},
                    }
                ]
            },
        }

        assert rr.head_arrival(pr=pr) == (None, None)


@pytest.mark.usefixtures("mock_resolve_repo")
class TestAuditTool:
    @pytest.fixture
    def outcome(self, mock_graphql: AsyncMock) -> Result[dict[str, Any]]:
        write_merge_settings(text="blocking_bots: [claude]\n")
        mock_graphql.return_value = completed(stdout=json.dumps(_payload()))
        return asyncio.run(rr.review_readiness_audit(limit=500))

    @pytest.fixture
    def result(self, outcome: Result[dict[str, Any]]) -> dict[str, Any]:
        return outcome.value

    def test_succeeds(self, outcome: Result[dict[str, Any]]) -> None:
        assert isinstance(outcome, SuccessResult)

    def test_skips_prs_never_sent_for_review(self, result: dict[str, Any]) -> None:
        assert [p["number"] for p in result["prs"]] == [10, 11, 12, 14]

    def test_counts_by_verdict(self, result: dict[str, Any]) -> None:
        assert result["counts"] == {
            rr.VERDICT_SENT_NOT_READY: 1,
            rr.VERDICT_WENT_RED_AFTER: 2,
            rr.VERDICT_READY: 1,
        }

    def test_reports_scan_window(self, result: dict[str, Any]) -> None:
        assert (result["scanned"], result["more_open_prs"]) == (5, True)

    def test_reports_blocking_bots(self, result: dict[str, Any]) -> None:
        assert result["blocking_bots"] == ["claude"]

    @pytest.mark.asyncio
    async def test_mcp_handler_returns_the_wire_payload(self, mock_graphql: AsyncMock) -> None:
        mock_graphql.return_value = completed(stdout=json.dumps(_payload()))

        wire = await cli_server.review_readiness_audit(limit=5)

        assert (wire["repo"], wire["scanned"]) == ("owner/repo", 5)

    @pytest.mark.usefixtures("mock_resolve_repo", "outcome")
    def test_limit_is_clamped(self, mock_graphql: AsyncMock) -> None:
        query = mock_graphql.call_args.kwargs["fields"]["query"]

        assert f"pullRequests(states: OPEN, first: {rr.MAX_LIMIT}," in query

    def test_limit_has_a_floor_of_one(self, mock_graphql: AsyncMock) -> None:
        mock_graphql.return_value = completed(stdout=json.dumps(_payload()))

        asyncio.run(rr.review_readiness_audit(limit=0))

        assert (
            "pullRequests(states: OPEN, first: 1,"
            in (mock_graphql.call_args.kwargs["fields"]["query"])
        )

    @pytest.mark.asyncio
    async def test_single_pr_is_reported_without_a_request(self, mock_graphql: AsyncMock) -> None:
        payload = {"data": {"repository": {"pullRequest": _pr(number=13)}}}
        mock_graphql.return_value = completed(stdout=json.dumps(payload))

        outcome = await rr.review_readiness_audit(pr_number=13)

        assert [p["number"] for p in outcome.value["prs"]] == [13]

    @pytest.mark.asyncio
    async def test_single_pr_is_queried_by_number(self, mock_graphql: AsyncMock) -> None:
        payload = {"data": {"repository": {"pullRequest": _pr(number=13)}}}
        mock_graphql.return_value = completed(stdout=json.dumps(payload))

        await rr.review_readiness_audit(pr_number=13)

        assert "pullRequest(number: 13)" in mock_graphql.call_args.kwargs["fields"]["query"]

    @pytest.mark.asyncio
    async def test_missing_single_pr_is_an_error(self, mock_graphql: AsyncMock) -> None:
        payload = {"data": {"repository": {"pullRequest": None}}}
        mock_graphql.return_value = completed(stdout=json.dumps(payload))

        outcome = await rr.review_readiness_audit(pr_number=99)

        assert isinstance(outcome, ErrorResult)
        assert outcome.error == "PR #99 not found in owner/repo"

    @pytest.mark.asyncio
    async def test_missing_pr_list_is_an_error(self, mock_graphql: AsyncMock) -> None:
        payload = {"data": {"repository": {"pullRequests": None}}}
        mock_graphql.return_value = completed(stdout=json.dumps(payload))

        outcome = await rr.review_readiness_audit()

        assert isinstance(outcome, ErrorResult)
        assert outcome.error == "pullRequests missing from GitHub response in owner/repo"

    @pytest.mark.asyncio
    async def test_missing_repository_is_an_error(self, mock_graphql: AsyncMock) -> None:
        mock_graphql.return_value = completed(stdout=json.dumps({"data": {"repository": None}}))

        outcome = await rr.review_readiness_audit()

        assert outcome.error == "Repository not found in GitHub GraphQL response"

    @pytest.mark.asyncio
    async def test_api_failure_is_an_error(self, mock_graphql: AsyncMock) -> None:
        mock_graphql.return_value = completed(returncode=1, stderr="HTTP 502")

        outcome = await rr.review_readiness_audit()

        assert isinstance(outcome, ErrorResult)
        assert "HTTP 502" in outcome.error

    @pytest.mark.asyncio
    async def test_malformed_config_stops_before_the_api(self, mock_graphql: AsyncMock) -> None:
        write_merge_settings(text="blocking_bots: {claude: true}\n")

        outcome = await rr.review_readiness_audit()

        assert isinstance(outcome, ErrorResult)
        mock_graphql.assert_not_called()


@pytest.mark.asyncio
async def test_unresolvable_repo_is_an_error() -> None:
    with patch.object(
        _gateway, "_resolve_repo", new_callable=AsyncMock, return_value=err("no repo")
    ):
        outcome = await rr.review_readiness_audit()

    assert isinstance(outcome, ErrorResult)
