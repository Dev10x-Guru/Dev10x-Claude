"""Tests for the read-only Chat bus view on the Overwatch page (GH-1844)."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from dev10x.comm.chatbus.board import AllowlistView, ChatBoard
from dev10x.comm.chatbus.status import BusStatus, empty_queue
from dev10x.comm.overwatch.decisions import DecisionStore
from dev10x.comm.overwatch.server import OverwatchApp, make_server, read_chat_board
from dev10x.core.domain.common.result import Result, err, ok
from dev10x.core.domain.dev10x_paths import Dev10xConfigDir
from tests.comm.chatbus.factories import unwrap
from tests.comm.overwatch.conftest import NOW
from tests.comm.overwatch.test_server import RELAY, TOKEN, call


class BoardReader:
    def __init__(self, *, result: Result[ChatBoard]) -> None:
        self.result = result
        self.calls: list[datetime] = []

    def __call__(self, *, now: datetime) -> Result[ChatBoard]:
        self.calls.append(now)
        return self.result


def _board(*, store: Path) -> ChatBoard:
    return ChatBoard(
        status=BusStatus(store=store, exists=False, queue=empty_queue()),
        allowlist=AllowlistView(config=store.parent / "gchat-config.yaml", owner="users/1"),
    )


@pytest.fixture
def reader(tmp_path: Path) -> BoardReader:
    return BoardReader(result=ok(_board(store=tmp_path / "bus.sqlite3")))


@pytest.fixture
def app(tmp_path: Path, reader: BoardReader) -> OverwatchApp:
    return OverwatchApp(
        store=DecisionStore(path=tmp_path / "decisions.json"),
        bus_root=tmp_path / "bus",
        kb_root=tmp_path / "kb",
        log_path=tmp_path / "actions.jsonl",
        token=TOKEN,
        relay_mailbox=RELAY,
        now=lambda: NOW,
        chat_board_reader=reader,
    )


@pytest.fixture
def port(app: OverwatchApp) -> Iterator[int]:
    server = make_server(app=app, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_address[1]
    app.stop()
    server.shutdown()
    server.server_close()


def test_requires_the_page_token(port: int) -> None:
    assert call(port=port, method="GET", path="/api/chatbus", token=None).status == 403


def test_serves_the_board_at_the_page_clock(port: int, reader: BoardReader) -> None:
    response = call(port=port, method="GET", path="/api/chatbus")
    payload: dict[str, Any] = response.json()

    assert (response.status, payload["exists"], payload["allowlist"]["owner"], reader.calls) == (
        200,
        False,
        {"chat_user": "users/1", "login": None},
        [NOW],
    )


def test_an_unreadable_store_is_unavailable(port: int, reader: BoardReader) -> None:
    reader.result = err("Cannot read the Chat bus store at /x: disk I/O error")

    response = call(port=port, method="GET", path="/api/chatbus")

    assert (response.status, response.json()) == (
        503,
        {"error": "Cannot read the Chat bus store at /x: disk I/O error"},
    )


def test_offers_no_write_route(port: int, reader: BoardReader) -> None:
    response = call(port=port, method="POST", path="/api/chatbus", payload={"approve": 1})

    assert (response.status, reader.calls) == (404, [])


def test_the_default_reader_uses_the_config_home_paths() -> None:
    board = unwrap(read_chat_board(now=NOW))

    assert (board.status.store, board.allowlist.config) == (
        Dev10xConfigDir.chat_bus_db(),
        Dev10xConfigDir.gchat_config_yaml(),
    )
