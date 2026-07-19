from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from dev10x.domain.claude_paths import CLAUDE_HOME_ENV_VAR
from dev10x.domain.common.result import SuccessResult
from dev10x.domain.usage import reader
from dev10x.domain.usage.reader import UsageEntry


def _record(
    *,
    ts: str,
    rid: str | None = "req_1",
    mid: str | None = "msg_1",
    model: str = "claude-opus-4-8",
    inp: int = 100,
    out: int = 200,
    cc: int = 10,
    cr: int = 20,
    cost: float | None = None,
) -> dict[str, Any]:
    return {
        "type": "assistant",
        "timestamp": ts,
        "requestId": rid,
        "costUSD": cost,
        "message": {
            "id": mid,
            "model": model,
            "usage": {
                "input_tokens": inp,
                "output_tokens": out,
                "cache_creation_input_tokens": cc,
                "cache_read_input_tokens": cr,
            },
        },
    }


def _write_jsonl(directory: Path, name: str, records: list[dict[str, Any]]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return path


def _entry(ts: datetime, **overrides: Any) -> UsageEntry:
    # Derive ids from the timestamp so entries at distinct times are distinct
    # (no accidental dedup), while two entries at the same time collide.
    stamp = ts.isoformat()
    base = {
        "timestamp": ts,
        "request_id": f"req-{stamp}",
        "message_id": f"msg-{stamp}",
        "model": "claude-opus-4-8",
        "input_tokens": 10,
        "output_tokens": 20,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "cost_usd": None,
    }
    base.update(overrides)
    return UsageEntry(**base)  # type: ignore[arg-type]


class TestParseEntry:
    def test_valid_record(self) -> None:
        entry = reader.parse_entry(_record(ts="2026-07-19T07:10:00.000Z"))
        assert entry is not None
        assert entry.input_tokens == 100
        assert entry.output_tokens == 200
        assert entry.cache_creation_input_tokens == 10
        assert entry.cache_read_input_tokens == 20
        assert entry.model == "claude-opus-4-8"
        assert entry.timestamp == datetime(2026, 7, 19, 7, 10, tzinfo=UTC)

    def test_cost_present(self) -> None:
        entry = reader.parse_entry(_record(ts="2026-07-19T07:10:00.000Z", cost=1.25))
        assert entry is not None
        assert entry.cost_usd == 1.25

    def test_message_not_dict_returns_none(self) -> None:
        assert reader.parse_entry({"message": "nope", "timestamp": "x"}) is None

    def test_missing_usage_returns_none(self) -> None:
        assert reader.parse_entry({"message": {"model": "m"}, "timestamp": "x"}) is None

    def test_non_string_timestamp_returns_none(self) -> None:
        rec = _record(ts="2026-07-19T07:10:00Z")
        rec["timestamp"] = 12345
        assert reader.parse_entry(rec) is None

    def test_bad_timestamp_returns_none(self) -> None:
        assert reader.parse_entry(_record(ts="not-a-timestamp")) is None

    def test_naive_timestamp_assumed_utc(self) -> None:
        entry = reader.parse_entry(_record(ts="2026-07-19T07:10:00"))
        assert entry is not None
        assert entry.timestamp.tzinfo == UTC

    def test_synthetic_model_skipped(self) -> None:
        assert reader.parse_entry(_record(ts="2026-07-19T07:10:00Z", model="<synthetic>")) is None


class TestIterEntries:
    def test_missing_dir_yields_nothing(self, tmp_path: Path) -> None:
        assert list(reader.iter_entries(tmp_path / "absent")) == []

    def test_reads_and_skips_bad_lines(self, tmp_path: Path) -> None:
        proj = tmp_path / "projects" / "repo"
        proj.mkdir(parents=True)
        path = proj / "s.jsonl"
        good = json.dumps(_record(ts="2026-07-19T07:10:00Z"))
        list_line = json.dumps([1, 2, 3])  # valid JSON, not a dict
        path.write_text(f"{good}\n\n{{bad json}}\n{list_line}\n", encoding="utf-8")
        entries = list(reader.iter_entries(tmp_path / "projects"))
        assert len(entries) == 1

    def test_oserror_on_directory_named_jsonl_is_skipped(self, tmp_path: Path) -> None:
        # rglob matches a directory named *.jsonl; read_text raises OSError.
        (tmp_path / "trap.jsonl").mkdir()
        assert list(reader.iter_entries(tmp_path)) == []


class TestDedup:
    def test_drops_duplicate_keyed_entries(self) -> None:
        ts = datetime(2026, 7, 19, 7, 0, tzinfo=UTC)
        entries = [_entry(ts), _entry(ts)]
        assert len(reader._dedup(entries)) == 1

    def test_keeps_entries_without_ids(self) -> None:
        ts = datetime(2026, 7, 19, 7, 0, tzinfo=UTC)
        entries = [_entry(ts, message_id=None), _entry(ts, request_id=None)]
        assert len(reader._dedup(entries)) == 2


class TestBuildBlocks:
    def test_empty(self) -> None:
        assert reader.build_blocks([]) == []

    def test_entries_within_window_one_block(self) -> None:
        start = datetime(2026, 7, 19, 7, 5, tzinfo=UTC)
        entries = [_entry(start), _entry(start + timedelta(hours=2))]
        blocks = reader.build_blocks(entries)
        assert len(blocks) == 1
        assert blocks[0].start == datetime(2026, 7, 19, 7, 0, tzinfo=UTC)

    def test_span_over_five_hours_splits(self) -> None:
        start = datetime(2026, 7, 19, 7, 5, tzinfo=UTC)
        entries = [
            _entry(start),
            _entry(start + timedelta(hours=1)),
            _entry(start + timedelta(hours=6)),
        ]
        assert len(reader.build_blocks(entries)) == 2

    def test_gap_over_five_hours_splits(self) -> None:
        start = datetime(2026, 7, 19, 7, 5, tzinfo=UTC)
        entries = [_entry(start), _entry(start + timedelta(hours=5, minutes=30))]
        assert len(reader.build_blocks(entries)) == 2


class TestIsActive:
    def test_active_recent_block(self) -> None:
        now = datetime(2026, 7, 19, 9, 0, tzinfo=UTC)
        block = reader.UsageBlock(
            start=datetime(2026, 7, 19, 7, 0, tzinfo=UTC),
            entries=[_entry(datetime(2026, 7, 19, 8, 55, tzinfo=UTC))],
        )
        assert reader.is_active(block, now) is True

    def test_inactive_past_end_time(self) -> None:
        now = datetime(2026, 7, 19, 13, 0, tzinfo=UTC)
        block = reader.UsageBlock(
            start=datetime(2026, 7, 19, 7, 0, tzinfo=UTC),
            entries=[_entry(datetime(2026, 7, 19, 7, 30, tzinfo=UTC))],
        )
        assert reader.is_active(block, now) is False

    def test_active_at_exact_last_minute_of_window(self) -> None:
        block = reader.UsageBlock(
            start=datetime(2026, 7, 19, 7, 0, tzinfo=UTC),
            entries=[_entry(datetime(2026, 7, 19, 7, 1, tzinfo=UTC))],
        )
        # 11:59 is inside the 07:00–12:00 window → still active.
        assert reader.is_active(block, datetime(2026, 7, 19, 11, 59, tzinfo=UTC)) is True
        # 12:00 is the window end (exclusive) → no longer active.
        assert reader.is_active(block, datetime(2026, 7, 19, 12, 0, tzinfo=UTC)) is False


class TestBlocksReport:
    def _home(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        home = tmp_path / "claude"
        monkeypatch.setenv(CLAUDE_HOME_ENV_VAR, str(home))
        return home

    def test_active_block_shape(self, tmp_path: Path) -> None:
        proj = tmp_path / "projects" / "repo"
        now = datetime(2026, 7, 19, 8, 30, tzinfo=UTC)
        _write_jsonl(
            proj,
            "s.jsonl",
            [
                _record(ts="2026-07-19T07:10:00.000Z"),
                _record(ts="2026-07-19T08:00:00.000Z", mid="msg_2"),
            ],
        )
        result = reader.blocks_report(
            active_only=True, now=now, projects_dir=tmp_path / "projects"
        )
        assert isinstance(result, SuccessResult)
        payload = result.value
        assert payload["pricingSource"] == "offline-estimate"
        assert len(payload["blocks"]) == 1
        block = payload["blocks"][0]
        assert block["isActive"] is True
        assert block["entries"] == 2
        assert block["tokenCounts"]["inputTokens"] == 200
        assert block["remainingMinutes"] == 210  # 12:00 - 08:30
        assert block["burnRate"] is not None
        assert block["projection"]["remainingMinutes"] == 210

    def test_active_only_filters_closed_block(self, tmp_path: Path) -> None:
        proj = tmp_path / "projects" / "repo"
        now = datetime(2026, 7, 19, 20, 0, tzinfo=UTC)
        _write_jsonl(proj, "s.jsonl", [_record(ts="2026-07-19T07:10:00.000Z")])
        result = reader.blocks_report(
            active_only=True, now=now, projects_dir=tmp_path / "projects"
        )
        assert isinstance(result, SuccessResult)
        assert result.value["blocks"] == []

    def test_all_includes_closed_block_without_burn_rate(self, tmp_path: Path) -> None:
        proj = tmp_path / "projects" / "repo"
        now = datetime(2026, 7, 19, 20, 0, tzinfo=UTC)
        _write_jsonl(proj, "s.jsonl", [_record(ts="2026-07-19T07:10:00.000Z")])
        result = reader.blocks_report(
            active_only=False, now=now, projects_dir=tmp_path / "projects"
        )
        assert isinstance(result, SuccessResult)
        block = result.value["blocks"][0]
        assert block["isActive"] is False
        assert block["burnRate"] is None
        assert block["projection"] is None
        assert block["remainingMinutes"] == 0

    def test_active_block_zero_elapsed_has_no_burn_rate(self, tmp_path: Path) -> None:
        proj = tmp_path / "projects" / "repo"
        # now exactly at the (floored) block start → elapsedMinutes == 0.
        now = datetime(2026, 7, 19, 7, 0, tzinfo=UTC)
        _write_jsonl(proj, "s.jsonl", [_record(ts="2026-07-19T07:00:00.000Z")])
        result = reader.blocks_report(
            active_only=True, now=now, projects_dir=tmp_path / "projects"
        )
        assert isinstance(result, SuccessResult)
        block = result.value["blocks"][0]
        assert block["elapsedMinutes"] == 0
        assert block["burnRate"] is None

    def test_unpriced_model_surfaced(self, tmp_path: Path) -> None:
        proj = tmp_path / "projects" / "repo"
        now = datetime(2026, 7, 19, 8, 30, tzinfo=UTC)
        _write_jsonl(
            proj, "s.jsonl", [_record(ts="2026-07-19T08:00:00.000Z", model="claude-fable-5")]
        )
        result = reader.blocks_report(
            active_only=True, now=now, projects_dir=tmp_path / "projects"
        )
        assert isinstance(result, SuccessResult)
        assert result.value["unpricedModels"] == ["claude-fable-5"]
        assert result.value["blocks"][0]["costUSD"] == 0.0

    def test_uses_recorded_cost_when_present(self, tmp_path: Path) -> None:
        proj = tmp_path / "projects" / "repo"
        now = datetime(2026, 7, 19, 8, 30, tzinfo=UTC)
        _write_jsonl(
            proj,
            "s.jsonl",
            [_record(ts="2026-07-19T08:00:00.000Z", model="claude-fable-5", cost=2.5)],
        )
        result = reader.blocks_report(
            active_only=True, now=now, projects_dir=tmp_path / "projects"
        )
        assert isinstance(result, SuccessResult)
        assert result.value["blocks"][0]["costUSD"] == 2.5
        assert result.value["unpricedModels"] == []

    def test_defaults_now_and_projects_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Point ClaudeDir at an empty home; no now/projects_dir args.
        monkeypatch.setenv(CLAUDE_HOME_ENV_VAR, str(tmp_path / "claude"))
        result = reader.blocks_report()
        assert isinstance(result, SuccessResult)
        assert result.value["blocks"] == []
