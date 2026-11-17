"""Route a pasted link to its source adapter and write the record (GH-1985)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from dev10x.core.domain.common.result import Result, SuccessResult
from dev10x.kb.record import (
    RecordFiles,
    SourceKind,
    SourceRecord,
    SourceRef,
    classify_url,
    write_record,
)
from dev10x.kb.spotify import DEFAULT_MODEL, fetch_spotify
from dev10x.kb.web import fetch_web
from dev10x.kb.youtube import fetch_youtube


def _adapter(*, kind: SourceKind, model: str) -> Callable[[SourceRef], Result[SourceRecord]]:
    if kind is SourceKind.YOUTUBE:
        return fetch_youtube
    if kind is SourceKind.SPOTIFY:
        return lambda ref: fetch_spotify(ref, model=model)
    return fetch_web


def fetch_source(
    *,
    url: str,
    model: str = DEFAULT_MODEL,
    directory: Path | None = None,
) -> Result[RecordFiles]:
    ref = classify_url(url)
    if not isinstance(ref, SuccessResult):
        return ref
    record = _adapter(kind=ref.value.kind, model=model)(ref.value)
    if not isinstance(record, SuccessResult):
        return record
    return write_record(record=record.value, directory=directory)
