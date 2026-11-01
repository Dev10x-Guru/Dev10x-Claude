"""GH-1421: a failed `pr_notify` send leaves a durable trace."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import pytest_asyncio
from dev10x.domain.common.result import ErrorResult, SuccessResult

import dev10x.github as gh
from dev10x.core.github import _gateway


@pytest.fixture
def recorded(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    entries: list[dict] = []
    monkeypatch.setattr(gh.notify, "record_undelivered", lambda **kwargs: entries.append(kwargs))
    return entries


def _stub_run(*, returncode: int, stderr: str = "", stdout: str = ""):
    async def fake_async_run(**_kwargs) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["uv"], returncode=returncode, stdout=stdout, stderr=stderr
        )

    return fake_async_run


class TestPrNotifyScriptResolution:
    """GH-1751: the uv-script path pointed at `<root>/src/skills/...`.

    Every other test here stubs the existence check, which is exactly how
    a path that did not exist in the package shipped unnoticed.
    """

    @pytest_asyncio.fixture
    async def launched(self, monkeypatch: pytest.MonkeyPatch) -> list[str]:
        captured: list[str] = []

        async def fake_async_run(
            *, args: list[str], **_kwargs
        ) -> subprocess.CompletedProcess[str]:
            captured.extend(args)
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="{}", stderr="")

        monkeypatch.setattr(_gateway, "async_run", fake_async_run)
        await gh.pr_notify(pr_number=1, repo="o/r", action="prepare")
        return captured

    @pytest.mark.asyncio
    async def test_launches_the_packaged_script(self, launched: list[str]) -> None:
        script = Path(launched[launched.index("--script") + 1])

        assert script.is_file()
        assert script.parts[-4:] == ("skills", "gh-pr-monitor", "scripts", "pr-notify.py")

    @pytest.mark.asyncio
    async def test_a_missing_script_is_named_in_the_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(gh.notify, "resolve_script_path", lambda _rel: tmp_path / "gone.py")

        result = await gh.pr_notify(pr_number=1, repo="o/r")

        assert isinstance(result, ErrorResult)
        assert result.to_dict()["error"] == f"Script not found: {tmp_path / 'gone.py'}"


class TestPrNotifyDeadLetters:
    @pytest.mark.asyncio
    async def test_a_failed_send_is_recorded(
        self,
        monkeypatch: pytest.MonkeyPatch,
        recorded: list[dict],
    ) -> None:
        monkeypatch.setattr(
            _gateway, "async_run", _stub_run(returncode=1, stderr="slack transport down")
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
    ) -> None:
        """`prepare` dispatches nothing, so nothing was lost."""
        monkeypatch.setattr(_gateway, "async_run", _stub_run(returncode=1, stderr="bad args"))

        result = await gh.pr_notify(pr_number=42, repo="o/r", action="prepare")

        assert isinstance(result, ErrorResult)
        assert recorded == []

    @pytest.mark.asyncio
    async def test_a_successful_send_records_nothing(
        self,
        monkeypatch: pytest.MonkeyPatch,
        recorded: list[dict],
    ) -> None:
        monkeypatch.setattr(_gateway, "async_run", _stub_run(returncode=0, stdout='{"ts": "1.0"}'))

        result = await gh.pr_notify(pr_number=42, repo="o/r", action="send", channel="#reviews")

        assert isinstance(result, SuccessResult)
        assert recorded == []

    @pytest.mark.asyncio
    async def test_a_send_without_a_channel_still_records(
        self,
        monkeypatch: pytest.MonkeyPatch,
        recorded: list[dict],
    ) -> None:
        """The channel came from config downstream; the loss is still real."""
        monkeypatch.setattr(_gateway, "async_run", _stub_run(returncode=1, stderr="down"))

        await gh.pr_notify(pr_number=7, repo="o/r", action="send")

        assert recorded[0]["channel"] == "(default)"
