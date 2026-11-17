"""Web adapter: Defuddle JSON to a source record (GH-1985)."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest

from dev10x.core import subprocess_utils
from dev10x.core.domain.common.result import ErrorResult, SuccessResult
from dev10x.kb.record import SourceKind, SourceRef
from dev10x.kb.web import fetch_web

REF = SourceRef(kind=SourceKind.WEB, id="web-abc", url="https://example.com/post")

pytestmark = pytest.mark.usefixtures("tools_installed")


def _returns(monkeypatch: pytest.MonkeyPatch, outcome: Any) -> None:
    monkeypatch.setattr(subprocess_utils, "run", lambda args, **_: outcome)


def test_maps_defuddle_fields(monkeypatch: pytest.MonkeyPatch, completed: Any) -> None:
    page = {
        "title": "Post",
        "author": "",
        "site": "Example",
        "published": "2026-11-01",
        "description": "Summary",
        "contentMarkdown": "# Body",
        "wordCount": 2,
    }
    _returns(monkeypatch, completed(stdout=json.dumps(page)))

    result = fetch_web(REF)

    assert isinstance(result, SuccessResult)
    record = result.value
    assert (record.title, record.author, record.transcript, record.metrics) == (
        "Post",
        "Example",
        "# Body",
        {"site": "Example", "words": "2"},
    )


def test_falls_back_to_url_and_domain(monkeypatch: pytest.MonkeyPatch, completed: Any) -> None:
    _returns(monkeypatch, completed(stdout=json.dumps({"domain": "example.com", "title": None})))

    result = fetch_web(REF)

    assert isinstance(result, SuccessResult)
    assert (result.value.title, result.value.author) == (REF.url, "example.com")


@pytest.mark.parametrize(
    ("outcome", "message"),
    [
        ({"returncode": 1, "stderr": "fetch failed"}, "fetch failed"),
        ({"stdout": "<html>"}, "unreadable output"),
        ({"stdout": "[1]"}, "unexpected output"),
    ],
)
def test_reports_defuddle_failures(
    outcome: dict[str, Any], message: str, monkeypatch: pytest.MonkeyPatch, completed: Any
) -> None:
    _returns(monkeypatch, completed(**outcome))

    result = fetch_web(REF)

    assert isinstance(result, ErrorResult)
    assert message in result.error


def test_reports_timeout(monkeypatch: pytest.MonkeyPatch, timeout_run: Callable[..., Any]) -> None:
    monkeypatch.setattr(subprocess_utils, "run", timeout_run)

    result = fetch_web(REF)

    assert isinstance(result, ErrorResult)
    assert result.error == f"defuddle timed out reading {REF.url}. Please try again."


def test_missing_defuddle_names_install_command(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: None)

    result = fetch_web(REF)

    assert isinstance(result, ErrorResult)
    assert "npm install -g defuddle" in result.error
