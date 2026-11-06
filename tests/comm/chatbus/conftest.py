from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from dev10x.domain.common.result import SuccessResult
from dev10x.domain.dev10x_paths import CONFIG_HOME_ENV_VAR, Dev10xConfigDir

from dev10x.comm.chatbus.store import open_store


@pytest.fixture
def config_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    home = tmp_path / "config"
    monkeypatch.setenv(CONFIG_HOME_ENV_VAR, str(home))
    Dev10xConfigDir.reset_cache()
    yield home
    Dev10xConfigDir.reset_cache()


@pytest.fixture
def db_path(config_home: Path) -> Path:
    return Dev10xConfigDir.chat_bus_db()


@pytest.fixture
def conn(db_path: Path) -> Iterator[sqlite3.Connection]:
    opened = open_store(path=db_path)
    assert isinstance(opened, SuccessResult)
    yield opened.value
    opened.value.close()
