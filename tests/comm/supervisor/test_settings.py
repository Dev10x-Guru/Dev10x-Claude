"""Tests for the supervisor page settings (GH-1754)."""

from __future__ import annotations

from pathlib import Path

import pytest

from dev10x.comm.supervisor.settings import (
    ANSWER_WAIT_DEFAULT,
    ANSWER_WAIT_MAX,
    PageSettings,
    SettingsStore,
)


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return tmp_path / "settings.json"


def test_load_defaults_without_a_file(path: Path) -> None:
    assert SettingsStore(path=path).load() == PageSettings(answer_wait_seconds=ANSWER_WAIT_DEFAULT)


@pytest.mark.parametrize(
    "content",
    ["not json", "[]", '{"answer_wait_seconds": "soon"}', "{}"],
    ids=["garbage", "not-object", "not-number", "no-key"],
)
def test_load_falls_back_to_the_default(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")

    assert SettingsStore(path=path).load() == PageSettings(answer_wait_seconds=ANSWER_WAIT_DEFAULT)


@pytest.mark.parametrize(
    ("asked", "kept"),
    [(45, 45), (0, 0), (-5, 0), (9999, ANSWER_WAIT_MAX)],
    ids=["in-range", "off", "negative", "too-long"],
)
def test_save_clamps_and_round_trips(path: Path, asked: int, kept: int) -> None:
    store = SettingsStore(path=path)

    saved = store.save(settings=PageSettings(answer_wait_seconds=asked))

    assert (saved, store.load()) == (
        PageSettings(answer_wait_seconds=kept),
        PageSettings(answer_wait_seconds=kept),
    )
