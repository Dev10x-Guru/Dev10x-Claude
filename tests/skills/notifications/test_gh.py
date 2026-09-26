"""Tests for the shared gh JSON helper."""

from __future__ import annotations

import subprocess
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from dev10x.skills.notifications import _gh


def _fake_run(recorder: dict[str, Any], *, returncode: int, stdout: str, stderr: str):
    def run(args: list[str], **kwargs: Any) -> SimpleNamespace:
        recorder["args"] = args
        recorder["kwargs"] = kwargs
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

    return run


def test_raises_gh_command_error_on_nonzero_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        _gh.subprocess_utils,
        "run",
        _fake_run({}, returncode=1, stdout="", stderr="boom"),
    )
    with pytest.raises(_gh.GhCommandError, match="boom"):
        _gh.gh_json(args=["pr", "view", "1"])


def test_returns_parsed_json_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        _gh.subprocess_utils,
        "run",
        _fake_run({}, returncode=0, stdout='{"ok": true}', stderr=""),
    )
    assert _gh.gh_json(args=["pr", "view", "1"]) == {"ok": True}


def test_routes_through_subprocess_utils_with_bounded_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder: dict[str, Any] = {}
    monkeypatch.setattr(
        _gh.subprocess_utils,
        "run",
        _fake_run(recorder, returncode=0, stdout="{}", stderr=""),
    )

    _gh.gh_json(args=["pr", "view", "1"])

    assert recorder["args"][0] == "gh"
    assert recorder["kwargs"]["timeout"] == _gh._GH_TIMEOUT_SECONDS


def test_forwards_explicit_cwd(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder: dict[str, Any] = {}
    monkeypatch.setattr(
        _gh.subprocess_utils,
        "run",
        _fake_run(recorder, returncode=0, stdout="{}", stderr=""),
    )

    _gh.gh_json(args=["pr", "view", "1"], cwd="/work/some-worktree")

    assert recorder["kwargs"]["cwd"] == "/work/some-worktree"


class TestGhApiJson:
    """GH-1442: `gh api` calls route through dev10x.github's shared Gateway."""

    def test_returns_parsed_json_on_success(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["gh", "api", "repos/o/r"], returncode=0, stdout='{"ok": true}', stderr=""
        )
        with patch(
            "dev10x.github._gh_api_raw", new_callable=AsyncMock, return_value=completed
        ) as mock_api:
            assert _gh.gh_api_json("repos/o/r") == {"ok": True}
        mock_api.assert_awaited_once_with("repos/o/r", timeout=_gh._GH_TIMEOUT_SECONDS)

    def test_raises_gh_command_error_on_nonzero_exit(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["gh", "api", "repos/o/r"], returncode=1, stdout="", stderr="boom"
        )
        with patch("dev10x.github._gh_api_raw", new_callable=AsyncMock, return_value=completed):
            with pytest.raises(_gh.GhCommandError, match="boom"):
                _gh.gh_api_json("repos/o/r")
