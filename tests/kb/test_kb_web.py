"""Web adapter: Defuddle JSON to a source record (GH-1985)."""

from __future__ import annotations

import json
import subprocess
from typing import Any

import pytest

from dev10x.core import subprocess_utils
from dev10x.core.domain.common.result import ErrorResult, SuccessResult
from dev10x.kb.record import SourceKind, SourceRef
from dev10x.kb.web import fetch_web

REF = SourceRef(kind=SourceKind.WEB, id="web-abc", url="https://example.com/post")


def _completed(*, returncode: int = 0, stdout: str = "", stderr: str = "") -> Any:
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr
    )


@pytest.fixture(autouse=True)
def installed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: f"/bin/{name}")


def _returns(monkeypatch: pytest.MonkeyPatch, completed: Any) -> None:
    monkeypatch.setattr(subprocess_utils, "run", lambda args, **_: completed)


def test_maps_defuddle_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    page = {
        "title": "Post",
        "author": "",
        "site": "Example",
        "published": "2026-11-01",
        "description": "Summary",
        "contentMarkdown": "# Body",
        "wordCount": 2,
    }
    _returns(monkeypatch, _completed(stdout=json.dumps(page)))

    result = fetch_web(REF)

    assert isinstance(result, SuccessResult)
    record = result.value
    assert (record.title, record.author, record.transcript, record.metrics) == (
        "Post",
        "Example",
        "# Body",
        {"site": "Example", "words": "2"},
    )


def test_falls_back_to_url_and_domain(monkeypatch: pytest.MonkeyPatch) -> None:
    _returns(monkeypatch, _completed(stdout=json.dumps({"domain": "example.com", "title": None})))

    result = fetch_web(REF)

    assert isinstance(result, SuccessResult)
    assert (result.value.title, result.value.author) == (REF.url, "example.com")


@pytest.mark.parametrize(
    ("completed", "message"),
    [
        (_completed(returncode=1, stderr="fetch failed"), "fetch failed"),
        (_completed(stdout="<html>"), "unreadable output"),
        (_completed(stdout="[1]"), "unexpected output"),
    ],
)
def test_reports_defuddle_failures(
    completed: Any, message: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _returns(monkeypatch, completed)

    result = fetch_web(REF)

    assert isinstance(result, ErrorResult)
    assert message in result.error


def test_reports_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def run(args: list[str], **_: Any) -> Any:
        raise subprocess.TimeoutExpired(cmd=args, timeout=1)

    monkeypatch.setattr(subprocess_utils, "run", run)

    result = fetch_web(REF)

    assert isinstance(result, ErrorResult)
    assert "Please try again" in result.error


def test_missing_defuddle_names_install_command(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: None)

    result = fetch_web(REF)

    assert isinstance(result, ErrorResult)
    assert "npm install -g defuddle" in result.error
