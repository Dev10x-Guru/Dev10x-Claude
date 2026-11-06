from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from dev10x.domain.dev10x_paths import Dev10xConfigDir

from dev10x.comm.chatbus.store import open_store
from tests.comm.chatbus.factories import unwrap

# Config-home isolation comes from the autouse fixture in tests/conftest.py.


@pytest.fixture
def db_path() -> Path:
    return Dev10xConfigDir.chat_bus_db()


@pytest.fixture
def conn(db_path: Path) -> Iterator[sqlite3.Connection]:
    connection = unwrap(open_store(path=db_path))
    yield connection
    connection.close()
