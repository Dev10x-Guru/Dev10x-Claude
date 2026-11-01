"""ci_rerun: bounded CI re-run through the sanctioned route (GH-1674)."""

from __future__ import annotations

import importlib
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from dev10x.domain.common.repository_ref import RepositoryRef
from dev10x.domain.common.result import ErrorResult, SuccessResult, err, ok

import dev10x.github as gh
from dev10x.core.github import _gateway
from dev10x.mcp import server_cli as cli_server

ci_rerun_module = importlib.import_module("dev10x.coding.github.ci_rerun")

SHA = "abc1234"
SUITES = f"repos/owner/repo/commits/{SHA}/check-suites?per_page=100"
RUNS = f"repos/owner/repo/actions/runs?head_sha={SHA}&per_page=100"
PULL = "repos/owner/repo/pulls/7"
ACTIONS_APP = {"slug": "github-actions", "name": "GitHub Actions"}
CODECOV_APP = {"slug": "codecov", "name": "Codecov"}


def _completed(
    *, returncode: int = 0, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr
    )


def _suite(*, id: int, app: dict[str, str], conclusion: str, status: str = "completed") -> dict:
    return {"id": id, "app": app, "conclusion": conclusion, "status": status}


def _run(*, id: int, suite: int, name: str, attempt: int = 1) -> dict:
    return {"id": id, "check_suite_id": suite, "name": name, "run_attempt": attempt}


SUITE_LIST = [
    _suite(id=1, app=ACTIONS_APP, conclusion="failure"),
    _suite(id=2, app=CODECOV_APP, conclusion="failure"),
    _suite(id=3, app=ACTIONS_APP, conclusion="success"),
    _suite(id=4, app=ACTIONS_APP, conclusion="failure"),
    _suite(id=5, app={"slug": "sonar", "name": "Sonar"}, conclusion="", status="in_progress"),
]
RUN_LIST = [
    _run(id=100, suite=1, name="CI"),
    _run(id=101, suite=3, name="Lint"),
    _run(id=102, suite=4, name="Slow", attempt=3),
]


@pytest.fixture(autouse=True)
def config_home(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    home = tmp_path / "config"
    monkeypatch.setenv("DEV10X_CONFIG_HOME", str(home))
    return home


@pytest.fixture
def mock_resolve_repo():
    with patch.object(
        _gateway,
        "_resolve_repo",
        new_callable=AsyncMock,
        return_value=ok(RepositoryRef(owner="owner", name="repo")),
    ) as mock:
        yield mock


@pytest.fixture
def routes() -> dict[str, subprocess.CompletedProcess[str]]:
    return {
        PULL: _completed(stdout=f"{SHA}\n"),
        SUITES: _completed(stdout=json.dumps({"check_suites": SUITE_LIST})),
        RUNS: _completed(stdout=json.dumps({"workflow_runs": RUN_LIST})),
        "repos/owner/repo/actions/runs/100/rerun-failed-jobs": _completed(),
        "repos/owner/repo/actions/runs/100/rerun": _completed(),
        "repos/owner/repo/actions/runs/101/rerun": _completed(),
        "repos/owner/repo/check-suites/2/rerequest": _completed(),
    }


@pytest.fixture
def gateway(routes: dict[str, Any], mock_resolve_repo: AsyncMock):
    with patch.object(
        _gateway,
        "_gh_api_raw",
        new_callable=AsyncMock,
        side_effect=lambda endpoint, **_: routes[endpoint],
    ) as mock:
        yield mock


def _posted(*, gateway: AsyncMock) -> list[str]:
    return [call.args[0] for call in gateway.call_args_list if call.kwargs.get("method") == "POST"]


def _skipped(*, result: SuccessResult) -> dict[str, str]:
    return {item["name"]: item["reason"] for item in result.value["skipped"]}


class TestFailedOnly:
    @pytest.mark.asyncio
    async def test_retries_failed_actions_run_and_third_party_suite(
        self, gateway: AsyncMock
    ) -> None:
        result = await gh.ci_rerun(head_sha=SHA)

        assert _posted(gateway=gateway) == [
            "repos/owner/repo/actions/runs/100/rerun-failed-jobs",
            "repos/owner/repo/check-suites/2/rerequest",
        ]
        assert [item["kind"] for item in result.value["retried"]] == [
            "actions-run",
            "check-suite",
        ]

    @pytest.mark.asyncio
    async def test_records_each_retry_with_its_attempt(self, gateway: AsyncMock) -> None:
        result = await gh.ci_rerun(head_sha=SHA)

        assert result.value["retried"][0] == {
            "kind": "actions-run",
            "id": 100,
            "name": "CI",
            "attempt_before": 1,
            "endpoint": "repos/owner/repo/actions/runs/100/rerun-failed-jobs",
        }

    @pytest.mark.asyncio
    async def test_first_third_party_retry_reports_attempt_one(self, gateway: AsyncMock) -> None:
        result = await gh.ci_rerun(head_sha=SHA)

        assert result.value["retried"][1]["attempt_before"] == 1

    @pytest.mark.asyncio
    async def test_reports_why_each_suite_was_skipped(self, gateway: AsyncMock) -> None:
        result = await gh.ci_rerun(head_sha=SHA)

        assert _skipped(result=result) == {
            "Lint": "not failed",
            "Slow": "retry cap reached (attempt 3)",
            "Sonar": "still running",
        }

    @pytest.mark.asyncio
    async def test_payload_names_repo_sha_and_cap(self, gateway: AsyncMock) -> None:
        result = await gh.ci_rerun(head_sha=SHA)

        assert (
            result.value["repo"],
            result.value["head_sha"],
            result.value["failed_only"],
            result.value["max_attempts"],
            result.value["truncated"],
            result.value["warnings"],
        ) == ("owner/repo", SHA, True, 3, False, [])


class TestFullRerun:
    @pytest.mark.asyncio
    async def test_failed_only_false_uses_full_rerun_and_covers_green_runs(
        self, gateway: AsyncMock
    ) -> None:
        await gh.ci_rerun(head_sha=SHA, failed_only=False)

        assert _posted(gateway=gateway) == [
            "repos/owner/repo/actions/runs/100/rerun",
            "repos/owner/repo/check-suites/2/rerequest",
            "repos/owner/repo/actions/runs/101/rerun",
        ]


class TestChecksFilter:
    @pytest.mark.parametrize(
        ("checks", "expected"),
        [
            (["ci"], ["repos/owner/repo/actions/runs/100/rerun-failed-jobs"]),
            (["CODECOV"], ["repos/owner/repo/check-suites/2/rerequest"]),
            (["github-actions"], ["repos/owner/repo/actions/runs/100/rerun-failed-jobs"]),
            (["nothing-like-this"], []),
        ],
    )
    @pytest.mark.asyncio
    async def test_restricts_to_named_checks(
        self, gateway: AsyncMock, checks: list[str], expected: list[str]
    ) -> None:
        await gh.ci_rerun(head_sha=SHA, checks=checks)

        assert _posted(gateway=gateway) == expected


class TestPrResolution:
    @pytest.mark.asyncio
    async def test_resolves_head_sha_from_the_pr(self, gateway: AsyncMock) -> None:
        result = await gh.ci_rerun(pr_number=7)

        assert result.value["head_sha"] == SHA

    @pytest.mark.parametrize(
        "pull",
        [_completed(returncode=1, stderr="not found"), _completed(stdout="\n")],
    )
    @pytest.mark.asyncio
    async def test_unresolvable_head_is_an_error(
        self, gateway: AsyncMock, routes: dict[str, Any], pull: Any
    ) -> None:
        routes[PULL] = pull

        result = await gh.ci_rerun(pr_number=7)

        assert isinstance(result, ErrorResult)


class TestArgumentValidation:
    @pytest.mark.parametrize("kwargs", [{}, {"pr_number": 7, "head_sha": SHA}])
    @pytest.mark.asyncio
    async def test_requires_exactly_one_target(self, kwargs: dict[str, Any]) -> None:
        result = await gh.ci_rerun(**kwargs)

        assert isinstance(result, ErrorResult)

    @pytest.mark.parametrize("kwargs", [{"pr_number": 0}, {"pr_number": -3}, {"head_sha": ""}])
    @pytest.mark.asyncio
    async def test_rejects_non_positive_pr_and_empty_sha(
        self, gateway: AsyncMock, kwargs: dict[str, Any]
    ) -> None:
        result = await gh.ci_rerun(**kwargs)

        assert isinstance(result, ErrorResult)

    @pytest.mark.parametrize(
        "head_sha",
        ["abc123", "abc1234/../x", "abc1234?per_page=1", "abc1234&x=1", "g" * 7, "a" * 41],
    )
    @pytest.mark.asyncio
    async def test_rejects_malformed_head_sha(self, gateway: AsyncMock, head_sha: str) -> None:
        result = await gh.ci_rerun(head_sha=head_sha)

        assert isinstance(result, ErrorResult)

    @pytest.mark.asyncio
    async def test_accepts_uppercase_head_sha(
        self, gateway: AsyncMock, routes: dict[str, Any]
    ) -> None:
        upper = SHA.upper()
        routes[f"repos/owner/repo/commits/{upper}/check-suites?per_page=100"] = routes[SUITES]
        routes[f"repos/owner/repo/actions/runs?head_sha={upper}&per_page=100"] = routes[RUNS]

        result = await gh.ci_rerun(head_sha=upper)

        assert isinstance(result, SuccessResult)

    @pytest.mark.asyncio
    async def test_propagates_repo_resolution_failure(self) -> None:
        with patch.object(
            _gateway, "_resolve_repo", new_callable=AsyncMock, return_value=err("no repo")
        ):
            result = await gh.ci_rerun(head_sha=SHA)

        assert isinstance(result, ErrorResult)


class TestListingFailures:
    @pytest.mark.parametrize("endpoint", [SUITES, RUNS])
    @pytest.mark.asyncio
    async def test_listing_failure_is_an_error(
        self, gateway: AsyncMock, routes: dict[str, Any], endpoint: str
    ) -> None:
        routes[endpoint] = _completed(returncode=1, stderr="boom")

        result = await gh.ci_rerun(head_sha=SHA)

        assert isinstance(result, ErrorResult)


class TestMalformedListings:
    @pytest.mark.parametrize("endpoint", [SUITES, RUNS])
    @pytest.mark.parametrize("stdout", ["not json", "[]", '{"workflow_runs": "x"}', "{}"])
    @pytest.mark.asyncio
    async def test_unparseable_listing_is_an_error_not_an_empty_success(
        self, gateway: AsyncMock, routes: dict[str, Any], endpoint: str, stdout: str
    ) -> None:
        routes[endpoint] = _completed(stdout=stdout)

        result = await gh.ci_rerun(head_sha=SHA)

        assert isinstance(result, ErrorResult)


class TestMissingWorkflowRun:
    @pytest.mark.asyncio
    async def test_actions_suite_without_a_run_is_skipped(
        self, gateway: AsyncMock, routes: dict[str, Any]
    ) -> None:
        routes[RUNS] = _completed(stdout=json.dumps({"workflow_runs": []}))

        result = await gh.ci_rerun(head_sha=SHA, checks=["github-actions"])

        assert [item["reason"] for item in result.value["skipped"]] == [
            "no workflow run found for suite",
            "not failed",
            "no workflow run found for suite",
        ]


class TestRefusedRerun:
    @pytest.mark.asyncio
    async def test_partial_refusal_is_reported_not_fatal(
        self, gateway: AsyncMock, routes: dict[str, Any]
    ) -> None:
        routes["repos/owner/repo/check-suites/2/rerequest"] = _completed(
            returncode=1, stderr="403"
        )

        result = await gh.ci_rerun(head_sha=SHA)

        assert result.value["failed"] == [{"name": "Codecov", "error": "403"}]

    @pytest.mark.asyncio
    async def test_total_refusal_is_an_error(
        self, gateway: AsyncMock, routes: dict[str, Any]
    ) -> None:
        routes["repos/owner/repo/check-suites/2/rerequest"] = _completed(
            returncode=1, stderr="403"
        )

        result = await gh.ci_rerun(head_sha=SHA, checks=["codecov"])

        assert isinstance(result, ErrorResult)


class TestPerCallBound:
    @pytest.mark.asyncio
    async def test_caps_retries_issued_by_one_call(
        self, gateway: AsyncMock, routes: dict[str, Any]
    ) -> None:
        extra = [
            _suite(id=1000 + n, app={"slug": f"app{n}", "name": f"App{n}"}, conclusion="failure")
            for n in range(ci_rerun_module.MAX_RETRIES_PER_CALL + 2)
        ]
        routes[SUITES] = _completed(stdout=json.dumps({"check_suites": extra}))
        for suite in extra:
            routes[f"repos/owner/repo/check-suites/{suite['id']}/rerequest"] = _completed()

        result = await gh.ci_rerun(head_sha=SHA)

        assert (len(result.value["retried"]), len(result.value["skipped"])) == (
            ci_rerun_module.MAX_RETRIES_PER_CALL,
            2,
        )


def _codecov_suites(*, ids: range) -> list[dict]:
    return [_suite(id=n, app=CODECOV_APP, conclusion="success") for n in ids]


class TestPagination:
    @pytest.mark.asyncio
    async def test_follows_pages_until_a_short_one(
        self, gateway: AsyncMock, routes: dict[str, Any]
    ) -> None:
        full = _codecov_suites(ids=range(10_000, 10_000 + ci_rerun_module.PAGE_SIZE))
        routes[SUITES] = _completed(stdout=json.dumps({"check_suites": full}))
        routes[f"{SUITES}&page=2"] = _completed(
            stdout=json.dumps(
                {"check_suites": [_suite(id=2, app=CODECOV_APP, conclusion="failure")]}
            )
        )

        result = await gh.ci_rerun(head_sha=SHA)

        assert (_posted(gateway=gateway), result.value["truncated"]) == (
            ["repos/owner/repo/check-suites/2/rerequest"],
            False,
        )

    @pytest.mark.asyncio
    async def test_reports_truncation_at_the_page_ceiling(
        self, gateway: AsyncMock, routes: dict[str, Any]
    ) -> None:
        size = ci_rerun_module.PAGE_SIZE
        for page in range(1, ci_rerun_module.MAX_LISTING_PAGES + 1):
            endpoint = SUITES if page == 1 else f"{SUITES}&page={page}"
            suites = _codecov_suites(ids=range(page * 1000, page * 1000 + size))
            routes[endpoint] = _completed(stdout=json.dumps({"check_suites": suites}))

        result = await gh.ci_rerun(head_sha=SHA)

        assert result.value["truncated"] is True

    @pytest.mark.parametrize(
        "page_two",
        [_completed(returncode=1, stderr="boom"), _completed(stdout="not json")],
    )
    @pytest.mark.asyncio
    async def test_a_failed_later_page_is_an_error(
        self, gateway: AsyncMock, routes: dict[str, Any], page_two: Any
    ) -> None:
        full = _codecov_suites(ids=range(10_000, 10_000 + ci_rerun_module.PAGE_SIZE))
        routes[SUITES] = _completed(stdout=json.dumps({"check_suites": full}))
        routes[f"{SUITES}&page=2"] = page_two

        result = await gh.ci_rerun(head_sha=SHA)

        assert isinstance(result, ErrorResult)


class TestThirdPartyCap:
    @pytest.mark.asyncio
    async def test_cap_persists_across_calls(self, gateway: AsyncMock) -> None:
        for _ in range(ci_rerun_module.MAX_RUN_ATTEMPTS - 1):
            await gh.ci_rerun(pr_number=7, checks=["codecov"])

        result = await gh.ci_rerun(pr_number=7, checks=["codecov"])

        assert (result.value["retried"], _skipped(result=result)) == (
            [],
            {"Codecov": "retry cap reached (attempt 3)"},
        )

    @pytest.mark.asyncio
    async def test_counts_are_keyed_per_pr(self, gateway: AsyncMock) -> None:
        await gh.ci_rerun(pr_number=7, checks=["codecov"])

        stored = json.loads(ci_rerun_module.attempts_path().read_text())

        assert stored == {"owner/repo#7": {"2": 1}}

    @pytest.mark.asyncio
    async def test_head_sha_calls_key_by_sha(self, gateway: AsyncMock) -> None:
        await gh.ci_rerun(head_sha=SHA, checks=["codecov"])

        stored = json.loads(ci_rerun_module.attempts_path().read_text())

        assert stored == {f"owner/repo@{SHA}": {"2": 1}}

    @pytest.mark.asyncio
    async def test_actions_runs_are_not_counted_locally(self, gateway: AsyncMock) -> None:
        await gh.ci_rerun(pr_number=7, checks=["ci"])

        assert not ci_rerun_module.attempts_path().exists()

    @pytest.mark.parametrize("content", ["not json", "[]", '{"owner/repo#7": "x"}'])
    @pytest.mark.asyncio
    async def test_unreadable_store_reads_as_no_attempts(
        self, gateway: AsyncMock, config_home: Any, content: str
    ) -> None:
        config_home.mkdir(parents=True)
        ci_rerun_module.attempts_path().write_text(content)

        result = await gh.ci_rerun(pr_number=7, checks=["codecov"])

        assert result.value["retried"][0]["attempt_before"] == 1

    @pytest.mark.asyncio
    async def test_store_write_failure_is_a_warning_not_an_error(
        self, gateway: AsyncMock, config_home: Any
    ) -> None:
        config_home.mkdir(parents=True)
        ci_rerun_module.attempts_path().write_text("not json")

        result = await gh.ci_rerun(pr_number=7, checks=["codecov"])

        assert (len(result.value["retried"]), len(result.value["warnings"])) == (1, 1)

    def test_concurrent_records_lose_no_count(self) -> None:
        workers = 8
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(
                pool.map(
                    lambda _: ci_rerun_module._record_third_party_attempt(key="k", suite_id=2),
                    range(workers),
                )
            )

        stored = json.loads(ci_rerun_module.attempts_path().read_text())

        assert stored == {"k": {"2": workers}}


class TestMcpHandler:
    @pytest.mark.asyncio
    @patch("dev10x.github.ci_rerun", new_callable=AsyncMock)
    async def test_delegates_and_wires_result(self, mock_fn: AsyncMock) -> None:
        mock_fn.return_value = ok({"retried": []})

        result = await cli_server.ci_rerun(pr_number=7, checks=["ci"], failed_only=False)

        assert (result, mock_fn.call_args.kwargs) == (
            {"retried": []},
            {
                "pr_number": 7,
                "head_sha": None,
                "checks": ["ci"],
                "failed_only": False,
                "repo": None,
            },
        )

    @pytest.mark.asyncio
    @patch("dev10x.github.ci_rerun", new_callable=AsyncMock)
    async def test_error_becomes_error_payload(self, mock_fn: AsyncMock) -> None:
        mock_fn.return_value = err("nope")

        result = await cli_server.ci_rerun(pr_number=7)

        assert "error" in result
