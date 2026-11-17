"""Routing a link to its adapter and writing the record (GH-1985)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from dev10x.core.domain.common.result import ErrorResult, SuccessResult, err, ok
from dev10x.kb import fetch
from dev10x.kb.record import SourceKind, SourceRecord, SourceRef


@pytest.fixture
def seen(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, Any]]:
    calls: list[tuple[str, Any]] = []

    def adapter(name: str) -> Any:
        def run(ref: SourceRef, **kwargs: Any) -> Any:
            calls.append((name, kwargs.get("model")))
            return ok(SourceRecord(id=ref.id, kind=ref.kind, url=ref.url, title=name))

        return run

    monkeypatch.setattr(fetch, "fetch_youtube", adapter("youtube"))
    monkeypatch.setattr(fetch, "fetch_web", adapter("web"))
    monkeypatch.setattr(fetch, "fetch_spotify", adapter("spotify"))
    return calls


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://youtu.be/abc", ("youtube", None)),
        ("https://example.com/a", ("web", None)),
        ("https://open.spotify.com/episode/7ywcdUyAXA3dNFKU4xjFeY", ("spotify", "base")),
    ],
)
def test_dispatches_by_kind(
    url: str, expected: tuple[str, Any], seen: list[tuple[str, Any]], tmp_path: Path
) -> None:
    result = fetch.fetch_source(url=url, model="base", directory=tmp_path)

    assert isinstance(result, SuccessResult)
    assert seen == [expected]


def test_writes_the_record(seen: list[tuple[str, Any]], tmp_path: Path) -> None:
    result = fetch.fetch_source(url="https://youtu.be/abc", directory=tmp_path)

    assert isinstance(result, SuccessResult)
    assert (result.value.kind, result.value.meta.parent) == (SourceKind.YOUTUBE, tmp_path)


def test_rejects_unsupported_link(seen: list[tuple[str, Any]]) -> None:
    result = fetch.fetch_source(url="mailto:a@b")

    assert (isinstance(result, ErrorResult), seen) == (True, [])


def test_propagates_adapter_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fetch, "fetch_web", lambda ref: err("defuddle missing"))

    result = fetch.fetch_source(url="https://example.com")

    assert isinstance(result, ErrorResult)
    assert result.error == "defuddle missing"
