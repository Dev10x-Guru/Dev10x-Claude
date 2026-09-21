"""GH-1421: a failed `pr_notify` send leaves a durable trace."""

from __future__ import annotations

import subprocess

import pytest

import dev10x.github as gh
from dev10x.domain.common.result import ErrorResult, SuccessResult


@pytest.fixture
def recorded(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    entries: list[dict] = []
    monkeypatch.setattr(gh, "record_undelivered", lambda **kwargs: entries.append(kwargs))
    return entries


@pytest.fixture
def script_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """`pr_notify` returns early when its uv-script is missing."""
    monkeypatch.setattr(gh.Path, "exists", lambda _self: True)


def _stub_run(*, returncode: int, stderr: str = "", stdout: str = ""):
    async def fake_async_run(**_kwargs) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["uv"], returncode=returncode, stdout=stdout, stderr=stderr
        )

    return fake_async_run


class TestPrNotifyDeadLetters:
    @pytest.mark.asyncio
    async def test_a_failed_send_is_recorded(
        self,
        monkeypatch: pytest.MonkeyPatch,
        recorded: list[dict],
        script_present: None,
    ) -> None:
        monkeypatch.setattr(
            gh, "async_run", _stub_run(returncode=1, stderr="slack transport down")
        )

        result = await gh.pr_notify(
            pr_number=42,
            repo="o/r",
            action="send",
            channel="#reviews",
            message="PR ready for review",
        )

        assert isinstance(result, ErrorResult)
        assert len(recorded) == 1
        assert recorded[0]["transport"] == "pr_notify"
        assert recorded[0]["channel"] == "#reviews"
        assert recorded[0]["error"] == "slack transport down"
        assert recorded[0]["context"]["pr_number"] == 42

    @pytest.mark.asyncio
    async def test_a_failed_prepare_is_not_recorded(
        self,
        monkeypatch: pytest.MonkeyPatch,
        recorded: list[dict],
        script_present: None,
    ) -> None:
        """`prepare` dispatches nothing, so nothing was lost."""
        monkeypatch.setattr(gh, "async_run", _stub_run(returncode=1, stderr="bad args"))

        result = await gh.pr_notify(pr_number=42, repo="o/r", action="prepare")

        assert isinstance(result, ErrorResult)
        assert recorded == []

    @pytest.mark.asyncio
    async def test_a_successful_send_records_nothing(
        self,
        monkeypatch: pytest.MonkeyPatch,
        recorded: list[dict],
        script_present: None,
    ) -> None:
        monkeypatch.setattr(gh, "async_run", _stub_run(returncode=0, stdout='{"ts": "1.0"}'))

        result = await gh.pr_notify(pr_number=42, repo="o/r", action="send", channel="#reviews")

        assert isinstance(result, SuccessResult)
        assert recorded == []

    @pytest.mark.asyncio
    async def test_a_send_without_a_channel_still_records(
        self,
        monkeypatch: pytest.MonkeyPatch,
        recorded: list[dict],
        script_present: None,
    ) -> None:
        """The channel came from config downstream; the loss is still real."""
        monkeypatch.setattr(gh, "async_run", _stub_run(returncode=1, stderr="down"))

        await gh.pr_notify(pr_number=7, repo="o/r", action="send")

        assert recorded[0]["channel"] == "(default)"
