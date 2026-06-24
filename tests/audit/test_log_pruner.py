"""Unit tests for dev10x.audit.log_pruner module (GH-530)."""

from __future__ import annotations

import os

from dev10x.audit.log_pruner import prune
from dev10x.audit.log_reader import AUDIT_RETAIN_ENV


class TestPrune:
    def test_deletes_old_files(self, tmp_path) -> None:
        # Create old and new files
        old = tmp_path / "hooks-2026-03-01.jsonl"
        new = tmp_path / "hooks-2026-05-16.jsonl"
        old.write_text("{}\n")
        new.write_text("{}\n")
        # Set mtime to be old
        old.touch()
        old_stat = old.stat()
        os.utime(old, (old_stat.st_atime, old_stat.st_mtime - 100 * 86400))
        # Prune with retain_days=30
        deleted = prune(retain_days=30, base_dir=tmp_path)
        assert deleted == 1
        assert not old.exists()
        assert new.exists()

    def test_missing_dir_returns_zero(self, tmp_path) -> None:
        missing = tmp_path / "missing"
        deleted = prune(retain_days=30, base_dir=missing)
        assert deleted == 0

    def test_no_matching_files_returns_zero(self, tmp_path) -> None:
        unrelated = tmp_path / "other.txt"
        unrelated.write_text("data")
        deleted = prune(retain_days=30, base_dir=tmp_path)
        assert deleted == 0

    def test_uses_env_variable_for_days(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv(AUDIT_RETAIN_ENV, "7")
        old = tmp_path / "hooks-2026-03-01.jsonl"
        old.write_text("{}\n")
        old.touch()
        old_stat = old.stat()
        os.utime(old, (old_stat.st_atime, old_stat.st_mtime - 100 * 86400))
        deleted = prune(base_dir=tmp_path)
        assert deleted == 1

    def test_invalid_env_variable_uses_default(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv(AUDIT_RETAIN_ENV, "not-a-number")
        new = tmp_path / "hooks-2026-05-16.jsonl"
        new.write_text("{}\n")
        deleted = prune(base_dir=tmp_path)
        assert deleted == 0
        assert new.exists()

    def test_skips_nonexistent_files(self, tmp_path) -> None:
        # Even if glob picks up a path that no longer exists (race condition),
        # prune() silently continues
        old = tmp_path / "hooks-2026-03-01.jsonl"
        old.write_text("{}\n")
        old.touch()
        old_stat = old.stat()
        os.utime(old, (old_stat.st_atime, old_stat.st_mtime - 100 * 86400))
        # Delete it before prune runs (simulating a race condition)
        old.unlink()
        deleted = prune(retain_days=30, base_dir=tmp_path)
        # prune() returns the actual count of successfully deleted files
        assert deleted == 0
