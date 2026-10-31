from __future__ import annotations

import json
from pathlib import Path

import pytest
from dev10x.hooks.session import _claim_state_file


class TestClaimStateFile:
    @pytest.fixture
    def state_file(self, tmp_path: Path) -> Path:
        path = tmp_path / "state.json"
        path.write_text(
            json.dumps({"session_id": "test-123", "timestamp": "2026-01-01T00:00:00Z"})
        )
        return path

    def test_returns_state_data(self, state_file: Path) -> None:
        result = _claim_state_file(path=state_file)

        assert result["session_id"] == "test-123"

    def test_removes_original_file(self, state_file: Path) -> None:
        _claim_state_file(path=state_file)

        assert not state_file.exists()

    def test_removes_claimed_file(self, state_file: Path) -> None:
        _claim_state_file(path=state_file)

        claimed_files = list(state_file.parent.glob("*.claimed"))
        assert claimed_files == []

    def test_returns_empty_dict_when_file_missing(self, tmp_path: Path) -> None:
        missing = tmp_path / "nonexistent.json"

        result = _claim_state_file(path=missing)

        assert result == {}

    def test_concurrent_claim_only_one_succeeds(self, state_file: Path) -> None:
        first = _claim_state_file(path=state_file)
        second = _claim_state_file(path=state_file)

        assert first["session_id"] == "test-123"
        assert second == {}

    def test_handles_invalid_json(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not json")

        result = _claim_state_file(path=bad_file)

        assert result == {}
        assert not bad_file.exists()
