"""`repo` is optional and resolved from cwd, like pr_get / merge_pr (GH-1683 F2)."""

from __future__ import annotations

import subprocess
from unittest.mock import AsyncMock, patch

import pytest
from dev10x.domain.common.result import ErrorResult, SuccessResult

from dev10x import monitor as monitor_mod
from dev10x.coding.github import reviews

_DETECTED = "detected-owner/detected-repo"


def _completed(*, stdout: str) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")


@pytest.fixture
def detected_repo():
    with patch(
        "dev10x.core.github._gateway._detect_repo",
        new_callable=AsyncMock,
        return_value=_DETECTED,
    ) as mock_detect:
        yield mock_detect


@pytest.fixture
def undetectable_repo():
    with patch(
        "dev10x.core.github._gateway._detect_repo",
        new_callable=AsyncMock,
        return_value=None,
    ) as mock_detect:
        yield mock_detect


@pytest.fixture
def script_runner():
    with patch(
        "dev10x.core.github._gateway.async_run_script",
        new_callable=AsyncMock,
        return_value=_completed(stdout="[]"),
    ) as mock_run:
        yield mock_run


@pytest.fixture
def monitor_runner():
    with patch(
        "dev10x.monitor.async_run",
        new_callable=AsyncMock,
        return_value=_completed(stdout='{"verdict": "green"}'),
    ) as mock_run:
        yield mock_run


@pytest.mark.asyncio
async def test_check_top_level_comments_detects_repo(detected_repo, script_runner) -> None:
    result = await reviews.check_top_level_comments(pr_number=7)

    assert isinstance(result, SuccessResult)
    assert script_runner.call_args.args[1:] == ("detected-owner", "detected-repo", "7")


@pytest.mark.asyncio
async def test_unresolved_threads_sweep_detects_repo(detected_repo, script_runner) -> None:
    result = await reviews.unresolved_threads(limit=5)

    assert isinstance(result, SuccessResult)
    assert script_runner.call_args.args[1:] == ("--repo", _DETECTED, "--limit", "5")


@pytest.mark.asyncio
async def test_ci_check_status_detects_repo(detected_repo, monitor_runner) -> None:
    result = await monitor_mod.ci_check_status(pr_number=7)

    assert isinstance(result, SuccessResult)
    args = monitor_runner.call_args.kwargs["args"]
    assert args[args.index("--repo") + 1] == _DETECTED


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "call",
    [
        lambda: reviews.check_top_level_comments(pr_number=7),
        lambda: reviews.unresolved_threads(),
        lambda: monitor_mod.ci_check_status(pr_number=7),
    ],
    ids=["check_top_level_comments", "unresolved_threads", "ci_check_status"],
)
async def test_undetectable_repo_is_an_error(undetectable_repo, call) -> None:
    result = await call()

    assert isinstance(result, ErrorResult)
    assert "Could not detect repository" in result.error
