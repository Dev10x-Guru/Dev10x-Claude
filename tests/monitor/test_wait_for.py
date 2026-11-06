"""wait_for: one bounded wait for a local condition (GH-1833)."""

from __future__ import annotations

import http.client
import importlib
import os
import subprocess
import urllib.error
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from dev10x.domain.common.result import ErrorResult, SuccessResult, ok
from dev10x.domain.transport_budget import MAX_TOOL_CALL_SECONDS

from dev10x.mcp import server_cli as cli_server
from dev10x.subprocess_utils import use_cwd

wait_for_module = importlib.import_module("dev10x.coding.monitor.wait_for")

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture(autouse=True)
def clock() -> Iterator[FakeClock]:
    fake = FakeClock()
    with (
        patch.object(wait_for_module, "_clock", new=fake),
        patch.object(wait_for_module, "_sleep", new=fake.sleep),
    ):
        yield fake


def _completed(*, stdout: str = "", returncode: int = 0, stderr: str = "") -> Any:
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr
    )


class TestFile:
    @pytest.mark.asyncio
    async def test_met_when_file_exists(self, tmp_path: Path) -> None:
        target = tmp_path / "ready"
        target.write_text("")

        result = await wait_for_module.wait_for(kind="file", target=str(target))

        assert isinstance(result, SuccessResult)
        assert result.value["met"] is True
        assert result.value["timed_out"] is False
        assert result.value["observed"] == {"path": str(target), "exists": True}
        assert result.value["polls"] == 1

    @pytest.mark.asyncio
    async def test_times_out_when_file_never_appears(
        self, tmp_path: Path, clock: FakeClock
    ) -> None:
        result = await wait_for_module.wait_for(
            kind="file", target=str(tmp_path / "missing"), timeout=5, poll_interval=2
        )

        assert result.value["met"] is False
        assert result.value["timed_out"] is True
        assert clock.sleeps == [2, 2, 1]
        assert result.value["polls"] == 4
        assert result.value["elapsed"] == 5

    @pytest.mark.asyncio
    async def test_appears_mid_wait(self, tmp_path: Path, clock: FakeClock) -> None:
        target = tmp_path / "late"

        async def create_then_sleep(seconds: float) -> None:
            target.write_text("")
            clock.now += seconds

        with patch.object(wait_for_module, "_sleep", new=create_then_sleep):
            result = await wait_for_module.wait_for(kind="file", target=str(target), timeout=10)

        assert result.value["met"] is True
        assert result.value["polls"] == 2

    @pytest.mark.asyncio
    async def test_relative_target_resolves_against_bound_cwd(self, tmp_path: Path) -> None:
        (tmp_path / "rel.txt").write_text("")

        with use_cwd(str(tmp_path)):
            result = await wait_for_module.wait_for(kind="file", target="rel.txt", timeout=0)

        assert result.value["met"] is True
        assert result.value["observed"]["path"] == str(tmp_path / "rel.txt")

    @pytest.mark.asyncio
    async def test_poll_interval_has_a_floor(self, tmp_path: Path, clock: FakeClock) -> None:
        await wait_for_module.wait_for(
            kind="file", target=str(tmp_path / "x"), timeout=0.2, poll_interval=0
        )

        assert clock.sleeps[0] == pytest.approx(0.1)


class TestFileText:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("content", "met", "match"),
        [
            ("server started on :8000\n", True, "started"),
            ("booting\n", False, None),
        ],
    )
    async def test_literal_text(
        self, tmp_path: Path, content: str, met: bool, match: str | None
    ) -> None:
        target = tmp_path / "log"
        target.write_text(content)

        result = await wait_for_module.wait_for(
            kind="file_text", target=str(target), pattern="started", timeout=0
        )

        assert result.value["met"] is met
        assert result.value["observed"]["match"] == match

    @pytest.mark.asyncio
    async def test_missing_file_is_not_met(self, tmp_path: Path) -> None:
        result = await wait_for_module.wait_for(
            kind="file_text", target=str(tmp_path / "none"), pattern="x", timeout=0
        )

        assert result.value["met"] is False
        assert result.value["observed"]["exists"] is False

    @pytest.mark.asyncio
    async def test_fifo_is_refused_without_blocking(self, tmp_path: Path) -> None:
        fifo = tmp_path / "pipe"
        os.mkfifo(fifo)

        result = await wait_for_module.wait_for(
            kind="file_text", target=str(fifo), pattern="x", timeout=0
        )

        assert result.value["met"] is False
        assert result.value["observed"]["error"] == "not a regular file"


class TestRegex:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("content", "met", "match"),
        [
            ("line\nPORT=8123\n", True, "PORT=8123"),
            ("PORT=\n", False, None),
        ],
    )
    async def test_multiline_regex(
        self, tmp_path: Path, content: str, met: bool, match: str | None
    ) -> None:
        target = tmp_path / "env"
        target.write_text(content)

        result = await wait_for_module.wait_for(
            kind="regex", target=str(target), pattern=r"^PORT=\d+$", timeout=0
        )

        assert result.value["met"] is met
        assert result.value["observed"]["match"] == match

    @pytest.mark.asyncio
    async def test_invalid_regex_is_an_error(self, tmp_path: Path) -> None:
        result = await wait_for_module.wait_for(
            kind="regex", target=str(tmp_path / "f"), pattern="(", timeout=0
        )

        assert isinstance(result, ErrorResult)
        assert "invalid regex" in result.error


class TestHttp:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("status", "expect_status", "met"),
        [
            (200, None, True),
            (302, None, True),
            (503, None, False),
            (404, 404, True),
            (200, 204, False),
            (None, None, False),
        ],
    )
    async def test_status_decides(
        self, status: int | None, expect_status: int | None, met: bool
    ) -> None:
        with patch.object(wait_for_module, "_http_status", return_value=(status, None)):
            result = await wait_for_module.wait_for(
                kind="http",
                target="http://localhost:8000/health",
                expect_status=expect_status,
                timeout=0,
            )

        assert result.value["met"] is met
        assert result.value["observed"]["status"] == status

    def test_http_status_reads_response(self) -> None:
        response = MagicMock(status=204)
        response.__enter__.return_value = response
        with patch.object(wait_for_module.urllib.request, "urlopen", return_value=response):
            assert wait_for_module._http_status(url="http://x") == (204, None)

    def test_http_status_reads_error_code(self) -> None:
        error = urllib.error.HTTPError("http://x", 500, "boom", {}, None)  # type: ignore[arg-type]
        with patch.object(wait_for_module.urllib.request, "urlopen", side_effect=error):
            assert wait_for_module._http_status(url="http://x") == (500, None)

    @pytest.mark.parametrize(
        ("raised", "fragment"),
        [
            (urllib.error.URLError("refused"), "refused"),
            (http.client.BadStatusLine("garbage"), "garbage"),
            (http.client.IncompleteRead(b"par"), "IncompleteRead"),
        ],
    )
    def test_http_status_reports_probe_failure(self, raised: Exception, fragment: str) -> None:
        with patch.object(wait_for_module.urllib.request, "urlopen", side_effect=raised):
            status, error = wait_for_module._http_status(url="http://x")

        assert status is None
        assert fragment in str(error)


class TestProcessGone:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(("alive", "met"), [(True, False), (False, True)])
    async def test_pid(self, alive: bool, met: bool) -> None:
        with patch.object(wait_for_module, "is_pid_alive", return_value=alive):
            result = await wait_for_module.wait_for(kind="process_gone", target="4242", timeout=0)

        assert result.value["met"] is met
        assert result.value["observed"] == {"pid": 4242, "alive": alive}

    @pytest.mark.asyncio
    async def test_own_pid_is_not_gone(self) -> None:
        result = await wait_for_module.wait_for(
            kind="process_gone", target=str(os.getpid()), timeout=0
        )

        assert result.value["met"] is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("completed", "met", "observed"),
        [
            (_completed(stdout="12\n34\n"), False, {"pattern": "uvicorn", "pids": [12, 34]}),
            (_completed(returncode=1), True, {"pattern": "uvicorn", "pids": []}),
            (
                _completed(returncode=2, stderr="bad regex"),
                False,
                {"pattern": "uvicorn", "error": "bad regex"},
            ),
            (_completed(returncode=-1), False, {"pattern": "uvicorn", "error": "pgrep failed"}),
        ],
    )
    async def test_pattern_uses_pgrep(self, completed: Any, met: bool, observed: dict) -> None:
        with patch.object(
            wait_for_module, "async_run", new_callable=AsyncMock, return_value=completed
        ) as run:
            result = await wait_for_module.wait_for(
                kind="process_gone", target="uvicorn", timeout=0
            )

        assert result.value["met"] is met
        assert result.value["observed"] == observed
        assert run.await_args.kwargs["args"] == ["pgrep", "-f", "--", "uvicorn"]

    @pytest.mark.asyncio
    async def test_missing_pgrep_is_reported_not_raised(self) -> None:
        with patch.object(
            wait_for_module,
            "async_run",
            new_callable=AsyncMock,
            side_effect=FileNotFoundError("pgrep"),
        ):
            result = await wait_for_module.wait_for(
                kind="process_gone", target="uvicorn", timeout=0
            )

        assert result.value["met"] is False
        assert result.value["observed"]["error"] == "pgrep unavailable: pgrep"


class TestTime:
    @pytest.fixture(autouse=True)
    def fixed_now(self, clock: FakeClock) -> Iterator[None]:
        def now() -> datetime:
            return NOW + timedelta(seconds=clock.now - 100.0)

        with patch.object(wait_for_module, "_now", new=now):
            yield

    @pytest.mark.asyncio
    async def test_sleeps_until_moment(self, clock: FakeClock) -> None:
        target = (NOW + timedelta(seconds=30)).isoformat()

        result = await wait_for_module.wait_for(kind="time", target=target, timeout=60)

        assert result.value["met"] is True
        assert clock.sleeps == [30]

    @pytest.mark.asyncio
    async def test_moment_beyond_timeout_times_out(self, clock: FakeClock) -> None:
        target = (NOW + timedelta(seconds=90)).isoformat()

        result = await wait_for_module.wait_for(kind="time", target=target, timeout=60)

        assert result.value["timed_out"] is True
        assert clock.sleeps == [60]

    @pytest.mark.asyncio
    async def test_past_moment_is_met_without_sleeping(self, clock: FakeClock) -> None:
        result = await wait_for_module.wait_for(kind="time", target="2025-01-01T00:00:00")

        assert result.value["met"] is True
        assert result.value["observed"]["target"] == "2025-01-01T00:00:00+00:00"
        assert clock.sleeps == []


class TestBudget:
    def test_now_is_timezone_aware(self) -> None:
        assert wait_for_module._now().tzinfo is UTC

    @pytest.mark.asyncio
    async def test_timeout_is_clamped_to_transport_budget(self, tmp_path: Path) -> None:
        target = tmp_path / "x"
        target.write_text("")

        result = await wait_for_module.wait_for(kind="file", target=str(target), timeout=99999)

        assert result.value["timeout"] == MAX_TOOL_CALL_SECONDS
        assert result.value["timeout_requested"] == 99999
        assert result.value["clamped"] is True


class TestValidation:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            ({"kind": "socket", "target": "x"}, "kind must be one of"),
            ({"kind": "file", "target": "  "}, "target must not be empty"),
            ({"kind": "file", "target": "x", "timeout": -1}, "finite, non-negative"),
            ({"kind": "file", "target": "x", "timeout": float("nan")}, "finite, non-negative"),
            ({"kind": "file", "target": "x", "timeout": float("inf")}, "finite, non-negative"),
            (
                {"kind": "file", "target": "x", "poll_interval": float("nan")},
                "poll_interval must be a finite",
            ),
            ({"kind": "file_text", "target": "x"}, "needs a 'pattern'"),
            ({"kind": "regex", "target": "x"}, "needs a 'pattern'"),
            ({"kind": "http", "target": "file:///etc/passwd"}, "needs an http(s) URL"),
            ({"kind": "time", "target": "tomorrow"}, "needs an ISO-8601"),
        ],
    )
    async def test_rejects_bad_arguments(self, kwargs: dict, message: str) -> None:
        result = await wait_for_module.wait_for(**kwargs)

        assert isinstance(result, ErrorResult)
        assert message in result.error

    def test_read_text_refuses_a_directory(self, tmp_path: Path) -> None:
        assert wait_for_module._read_text(path=tmp_path) == (None, "not a regular file")

    def test_read_text_reports_an_unreadable_file(self, tmp_path: Path) -> None:
        target = tmp_path / "locked"
        target.write_text("x")

        with patch.object(Path, "open", side_effect=PermissionError("denied")):
            assert wait_for_module._read_text(path=target) == (None, "denied")


class TestMcpHandler:
    @pytest.mark.asyncio
    async def test_routes_through_to_wire(self) -> None:
        with patch.object(
            wait_for_module, "wait_for", new_callable=AsyncMock, return_value=ok({"met": True})
        ) as mock:
            payload = await cli_server.wait_for(kind="file", target="/tmp/x", timeout=5)

        assert payload == {"met": True}
        assert mock.await_args.kwargs["timeout"] == 5
