"""Tests for the AbstractHook Template Method base (audit finding A11)."""

from __future__ import annotations

import io

import pytest

from dev10x.hooks.base import AbstractHook, load_hook_stdin


class _RecordingHook(AbstractHook):
    def __init__(self) -> None:
        self.seen: dict | None = None

    def handle(self, *, data: dict) -> None:
        self.seen = data


class TestRun:
    def test_passes_explicit_data_through_without_reading_stdin(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom() -> dict:
            raise AssertionError("stdin must not be read when data is provided")

        monkeypatch.setattr("dev10x.hooks.base.load_hook_stdin", _boom)
        hook = _RecordingHook()

        hook.run({"tool_input": {"skill": "Dev10x:x"}})

        assert hook.seen == {"tool_input": {"skill": "Dev10x:x"}}

    def test_reads_stdin_when_data_is_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("dev10x.hooks.base.load_hook_stdin", lambda: {"from": "stdin"})
        hook = _RecordingHook()

        hook.run(None)

        assert hook.seen == {"from": "stdin"}


class TestLoadHookStdin:
    def test_parses_valid_json(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO('{"a": 1}'))

        assert load_hook_stdin() == {"a": 1}

    def test_returns_empty_dict_on_invalid_json(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO("not json"))

        assert load_hook_stdin() == {}
