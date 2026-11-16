"""Tests for the Herdr roster probe and its MCP tool (GH-1984)."""

from __future__ import annotations

import subprocess
from typing import Any

import pytest

from dev10x.core.domain.common.result import ErrorResult, SuccessResult
from dev10x.herdr.mcp import roster_tools
from dev10x.herdr.probes import AGENT_LIST, WORKSPACE_LIST, get_roster
from tests.herdr.factories import AGENTS, K8S_ROOT, POS_ROOT, WORKSPACES

OUTPUTS = {tuple(WORKSPACE_LIST): WORKSPACES, tuple(AGENT_LIST): AGENTS}


def _runner(*, returncode: int = 0, stdout: dict[tuple[str, ...], str] = OUTPUTS):
    def run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=args,
            returncode=returncode,
            stdout=stdout.get(tuple(args), ""),
            stderr="boom",
        )

    return run


def _raising(exc: Exception):
    def run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise exc

    return run


class TestGetRoster:
    def test_success_wraps_the_roster(self) -> None:
        result = get_roster(cwd=POS_ROOT, runner=_runner())

        assert isinstance(result, SuccessResult)
        assert result.value["caller"]["role"] == "main"

    def test_repo_filter_is_applied(self) -> None:
        result = get_roster(repo_root=K8S_ROOT, runner=_runner())

        assert isinstance(result, SuccessResult)
        assert [repo["repo_root"] for repo in result.value["repos"]] == [K8S_ROOT]

    @pytest.mark.parametrize(
        ("runner", "message"),
        [
            (_raising(FileNotFoundError("herdr")), "herdr is not installed"),
            (
                _raising(subprocess.TimeoutExpired(cmd="herdr", timeout=10)),
                "try again",
            ),
            (_runner(returncode=1), "exited 1: boom"),
            (_runner(stdout={}), "invalid JSON"),
        ],
    )
    def test_failures_become_error_results(self, runner, message: str) -> None:
        result = get_roster(runner=runner)

        assert isinstance(result, ErrorResult)
        assert message in result.error


class TestHerdrRosterTool:
    @pytest.fixture
    def calls(self, monkeypatch: pytest.MonkeyPatch) -> list[dict[str, str]]:
        seen: list[dict[str, str]] = []

        def fake_get_roster(*, cwd: str, repo_root: str) -> SuccessResult[dict[str, Any]]:
            seen.append({"cwd": cwd, "repo_root": repo_root})
            return SuccessResult(value={"repos": []})

        monkeypatch.setattr(roster_tools, "get_roster", fake_get_roster)
        return seen

    @pytest.mark.asyncio
    async def test_tool_passes_bound_cwd_and_repo(self, calls: list[dict[str, str]]) -> None:
        payload = await roster_tools.herdr_roster(repo_root=POS_ROOT, cwd=POS_ROOT)

        assert (payload, calls) == ({"repos": []}, [{"cwd": POS_ROOT, "repo_root": POS_ROOT}])

    @pytest.mark.asyncio
    async def test_tool_defaults_repo_to_empty(self, calls: list[dict[str, str]]) -> None:
        await roster_tools.herdr_roster(cwd=POS_ROOT)

        assert calls[0]["repo_root"] == ""
