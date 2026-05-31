"""Tests for the AuditWriter Protocol seam (I6 / ADR-0008)."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import pytest

from dev10x.audit.log_reader import LogReaderAuditWriter
from dev10x.domain.audit_writer import AuditWriter
from dev10x.domain.hook_telemetry import HookOutcome
from dev10x.hooks import audit_emit
from dev10x.hooks.audit_emit import audit_hook, set_audit_writer


@dataclass
class _RecordingWriter:
    enabled: bool = True
    records: list[dict[str, Any]] = field(default_factory=list)

    def audit_enabled(self) -> bool:
        return self.enabled

    def append_record(self, *, record: dict[str, Any]) -> None:
        self.records.append(record)

    def new_span_id(self) -> str:
        return "span-test"

    def current_span_id(self) -> str:
        return "span-test"

    def classify_outcome(self, *, exit_code: int) -> HookOutcome:
        return HookOutcome.from_exit_code(exit_code)


@pytest.fixture()
def reset_writer() -> Iterator[None]:
    yield
    set_audit_writer(None)


def test_log_reader_writer_satisfies_protocol() -> None:
    assert isinstance(LogReaderAuditWriter(), AuditWriter)


def test_default_writer_is_log_reader_backed(reset_writer: None) -> None:
    set_audit_writer(None)
    assert isinstance(audit_emit._get_writer(), LogReaderAuditWriter)


def test_injected_writer_receives_body_record(reset_writer: None) -> None:
    writer = _RecordingWriter()
    set_audit_writer(writer)

    @audit_hook(name="seam-hook", event="PreToolUse")
    def target() -> int:
        return 7

    assert target() == 7
    assert len(writer.records) == 1
    assert writer.records[0]["hook"] == "seam-hook"
    assert writer.records[0]["span_id"] == "span-test"


def test_disabled_writer_skips_record(reset_writer: None) -> None:
    writer = _RecordingWriter(enabled=False)
    set_audit_writer(writer)

    @audit_hook(name="seam-hook", event="PreToolUse")
    def target() -> int:
        return 1

    assert target() == 1
    assert writer.records == []
