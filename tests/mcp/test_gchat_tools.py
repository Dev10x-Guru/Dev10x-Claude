"""Tests for the Google Chat watch MCP adapters (GH-1682)."""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
from dev10x.domain.dev10x_paths import Dev10xConfigDir

from dev10x.comm.mcp import gchat_tools
from dev10x.comm.skills.notifications import gchat_notify

THREAD = "spaces/AAAA/threads/BBBB"


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "gchat-watch.json"
    monkeypatch.setattr(Dev10xConfigDir, "gchat_watch_json", staticmethod(lambda: path))
    monkeypatch.setattr(gchat_notify, "_get_config", lambda: {})
    return path


@pytest_asyncio.fixture
async def armed(store: Path) -> dict:
    return await gchat_tools.gchat_watch_arm(thread=THREAD, notify=["dev10x-7"])


class TestGchatWatchArm:
    @pytest.mark.asyncio
    async def test_returns_armed_watch(self, armed: dict) -> None:
        assert armed["watch"]["thread"] == THREAD
        assert armed["watch"]["notify"] == ["dev10x-7"]

    @pytest.mark.asyncio
    async def test_persists_to_store(self, armed: dict, store: Path) -> None:
        assert store.exists()

    @pytest.mark.asyncio
    async def test_rejects_unknown_mode(self, store: Path) -> None:
        result = await gchat_tools.gchat_watch_arm(
            thread=THREAD, notify=["dev10x-7"], mode="forever"
        )

        assert "Unknown watch mode" in result["error"]


class TestGchatWatchList:
    @pytest.mark.asyncio
    async def test_lists_armed_watches(self, armed: dict) -> None:
        result = await gchat_tools.gchat_watch_list()

        assert result["count"] == 1
        assert result["watches"][0]["id"] == armed["watch"]["id"]

    @pytest.mark.asyncio
    async def test_reports_unreadable_store(self, store: Path) -> None:
        store.write_text("{not json")

        result = await gchat_tools.gchat_watch_list()

        assert "Could not read" in result["error"]


class TestGchatWatchDisarm:
    @pytest.mark.asyncio
    async def test_removes_watch_by_id(self, armed: dict) -> None:
        result = await gchat_tools.gchat_watch_disarm(watch_id=armed["watch"]["id"])

        assert result["watch"]["id"] == armed["watch"]["id"]
        assert (await gchat_tools.gchat_watch_list())["count"] == 0

    @pytest.mark.asyncio
    async def test_removes_watch_by_thread(self, armed: dict) -> None:
        result = await gchat_tools.gchat_watch_disarm(thread=THREAD)

        assert result["watch"]["thread"] == THREAD

    @pytest.mark.asyncio
    async def test_reports_unknown_watch(self, store: Path) -> None:
        result = await gchat_tools.gchat_watch_disarm(watch_id="nope")

        assert "No armed Google Chat watch" in result["error"]
