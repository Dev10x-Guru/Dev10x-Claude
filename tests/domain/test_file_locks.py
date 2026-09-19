from __future__ import annotations

import json
import multiprocessing as mp
import time
from pathlib import Path

import pytest
import yaml

from dev10x.domain.file_locks import (
    LOCK_TIMEOUT_SECONDS,
    CorruptYamlError,
    LockTimeoutError,
    atomic_append_line,
    atomic_write_bytes,
    atomic_write_text,
    file_lock,
    locked_json_update,
    locked_yaml_update,
)
from tests.lock_helpers import hold_sidecar


class TestAtomicWriteText:
    def test_creates_file(self, tmp_path: Path) -> None:
        target = tmp_path / "subdir" / "out.txt"
        atomic_write_text(target, "hello")
        assert target.read_text() == "hello"

    def test_overwrites_existing(self, tmp_path: Path) -> None:
        target = tmp_path / "out.txt"
        target.write_text("old")
        atomic_write_text(target, "new")
        assert target.read_text() == "new"

    def test_no_stale_tmp_after_success(self, tmp_path: Path) -> None:
        target = tmp_path / "out.txt"
        atomic_write_text(target, "hello")
        leftovers = [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]
        assert leftovers == []


class TestAtomicWriteBytes:
    def test_writes_binary(self, tmp_path: Path) -> None:
        target = tmp_path / "out.bin"
        atomic_write_bytes(target, b"\x00\x01\x02")
        assert target.read_bytes() == b"\x00\x01\x02"


class TestAtomicAppendLine:
    def test_creates_file_and_adds_newline(self, tmp_path: Path) -> None:
        target = tmp_path / "subdir" / "sink.md"
        atomic_append_line(target, "first")
        assert target.read_text() == "first\n"

    def test_appends_without_truncating(self, tmp_path: Path) -> None:
        target = tmp_path / "sink.md"
        atomic_append_line(target, "one")
        atomic_append_line(target, "two")
        assert target.read_text() == "one\ntwo\n"

    def test_preserves_existing_trailing_newline(self, tmp_path: Path) -> None:
        target = tmp_path / "sink.md"
        atomic_append_line(target, "line\n")
        assert target.read_text() == "line\n"

    def test_concurrent_appends_do_not_interleave(self, tmp_path: Path) -> None:
        target = tmp_path / "sink.md"
        ctx = mp.get_context("fork")
        workers = 8
        processes = [
            ctx.Process(target=_concurrent_append, args=(str(target), f"rec-{i}"))
            for i in range(workers)
        ]
        for p in processes:
            p.start()
        for p in processes:
            p.join(timeout=10)
            assert p.exitcode == 0, f"worker failed with {p.exitcode}"
        lines = target.read_text().splitlines()
        assert sorted(lines) == sorted(f"rec-{i}" for i in range(workers))


class TestFileLock:
    def test_creates_sidecar(self, tmp_path: Path) -> None:
        target = tmp_path / "data.json"
        with file_lock(target):
            assert (tmp_path / "data.json.lock").exists()
        # Sidecar is intentionally left in place after release to avoid
        # the unlink-race that breaks mutual exclusion under contention.
        assert (tmp_path / "data.json.lock").exists()

    def test_no_suffix_path(self, tmp_path: Path) -> None:
        target = tmp_path / "data"
        with file_lock(target):
            assert (tmp_path / "data.lock").exists()


class TestLockTimeout:
    def test_default_timeout_constant(self) -> None:
        assert LOCK_TIMEOUT_SECONDS == 10.0

    def test_raises_when_held(self, tmp_path: Path) -> None:
        target = tmp_path / "data.json"
        with hold_sidecar(tmp_path / "data.json.lock"):
            with pytest.raises(LockTimeoutError) as exc:
                with file_lock(target, timeout=0.2):
                    pass
        assert "locked by another process" in str(exc.value)

    def test_is_oserror_subclass(self, tmp_path: Path) -> None:
        target = tmp_path / "data.json"
        with hold_sidecar(tmp_path / "data.json.lock"):
            with pytest.raises(OSError):
                with file_lock(target, timeout=0.1):
                    pass

    def test_locked_json_update_times_out(self, tmp_path: Path) -> None:
        target = tmp_path / "settings.json"
        with hold_sidecar(tmp_path / "settings.lock"):
            with pytest.raises(LockTimeoutError):
                with locked_json_update(target, timeout=0.1):
                    pass

    def test_locked_yaml_update_times_out(self, tmp_path: Path) -> None:
        target = tmp_path / "plan.yaml"
        with hold_sidecar(tmp_path / "plan.yaml.lock"):
            with pytest.raises(LockTimeoutError):
                with locked_yaml_update(target, timeout=0.1):
                    pass

    def test_acquires_after_holder_releases(self, tmp_path: Path) -> None:
        target = tmp_path / "data.json"
        with hold_sidecar(tmp_path / "data.json.lock"):
            pass  # released here
        with file_lock(target, timeout=0.5):
            assert (tmp_path / "data.json.lock").exists()

    def test_zero_timeout_blocks_until_available(self, tmp_path: Path) -> None:
        target = tmp_path / "data.json"
        start = time.monotonic()
        with file_lock(target, timeout=0):
            pass
        # Uncontended acquire returns immediately under the legacy path.
        assert time.monotonic() - start < 1.0


class TestSidecarNamingConvention:
    """ADR-0011: the two lock helpers must never share a sidecar path.

    `file_lock`/`locked_yaml_update` append `.lock` to the full name
    (`settings.local.json` → `settings.local.json.lock`), while
    `locked_json_update` replaces the suffix (`settings.local.json` →
    `settings.local.lock`). Mixing them on one target would create two
    independent sidecars and silently break mutual exclusion.
    """

    def test_append_vs_replace_diverge_for_json_target(self, tmp_path: Path) -> None:
        target = tmp_path / "settings.local.json"
        append_sidecar = target.with_suffix(target.suffix + ".lock")
        replace_sidecar = target.with_suffix(".lock")
        assert append_sidecar.name == "settings.local.json.lock"
        assert replace_sidecar.name == "settings.local.lock"
        assert append_sidecar != replace_sidecar

    def test_file_lock_uses_append_convention(self, tmp_path: Path) -> None:
        target = tmp_path / "settings.local.json"
        with file_lock(target):
            assert (tmp_path / "settings.local.json.lock").exists()
            assert not (tmp_path / "settings.local.lock").exists()

    def test_locked_json_update_uses_replace_convention(self, tmp_path: Path) -> None:
        target = tmp_path / "settings.local.json"
        target.write_text(json.dumps({}))
        with locked_json_update(target):
            pass
        assert (tmp_path / "settings.local.lock").exists()
        assert not (tmp_path / "settings.local.json.lock").exists()


class TestLockedJsonUpdate:
    def test_load_mutate_save_cycle(self, tmp_path: Path) -> None:
        target = tmp_path / "settings.json"
        target.write_text(json.dumps({"count": 1}))
        with locked_json_update(target) as data:
            data["count"] += 1
        assert json.loads(target.read_text())["count"] == 2


class TestLockedYamlUpdate:
    def test_load_mutate_save_cycle(self, tmp_path: Path) -> None:
        target = tmp_path / "plan.yaml"
        target.write_text(yaml.safe_dump({"tasks": [1]}))
        with locked_yaml_update(target) as data:
            data["tasks"].append(2)
        result = yaml.safe_load(target.read_text())
        assert result["tasks"] == [1, 2]

    def test_creates_when_missing(self, tmp_path: Path) -> None:
        target = tmp_path / "plan.yaml"
        with locked_yaml_update(target) as data:
            data["fresh"] = True
        assert yaml.safe_load(target.read_text()) == {"fresh": True}


class TestCorruptYaml:
    """GH-1413: an unparseable store is data loss, not an empty document."""

    CORRUPT = "projects:\n  - match_repo: 'unterminated\n"

    def test_raises_instead_of_yielding_empty(self, tmp_path: Path) -> None:
        target = tmp_path / "friction.yaml"
        target.write_text(self.CORRUPT)
        with pytest.raises(CorruptYamlError):
            with locked_yaml_update(target):
                pass

    def test_leaves_the_unreadable_file_untouched(self, tmp_path: Path) -> None:
        target = tmp_path / "friction.yaml"
        target.write_text(self.CORRUPT)
        with pytest.raises(CorruptYamlError):
            with locked_yaml_update(target) as data:
                data["clobbered"] = True
        assert target.read_text() == self.CORRUPT

    def test_error_names_the_path(self, tmp_path: Path) -> None:
        target = tmp_path / "friction.yaml"
        target.write_text(self.CORRUPT)
        with pytest.raises(CorruptYamlError, match=str(target)):
            with locked_yaml_update(target):
                pass

    def test_releases_the_lock(self, tmp_path: Path) -> None:
        target = tmp_path / "friction.yaml"
        target.write_text(self.CORRUPT)
        with pytest.raises(CorruptYamlError):
            with locked_yaml_update(target):
                pass
        target.write_text(yaml.safe_dump({"ok": True}))
        with locked_yaml_update(target) as data:
            data["recovered"] = True
        assert yaml.safe_load(target.read_text()) == {"ok": True, "recovered": True}

    def test_empty_file_is_still_an_empty_document(self, tmp_path: Path) -> None:
        target = tmp_path / "friction.yaml"
        target.write_text("")
        with locked_yaml_update(target) as data:
            data["fresh"] = True
        assert yaml.safe_load(target.read_text()) == {"fresh": True}

    def test_is_oserror_subclass(self) -> None:
        assert issubclass(CorruptYamlError, OSError)


def _concurrent_increment(path_str: str, key: str) -> None:
    path = Path(path_str)
    with locked_json_update(path) as data:
        data[key] = data.get(key, 0) + 1


def _concurrent_append(path_str: str, line: str) -> None:
    atomic_append_line(Path(path_str), line)


class TestConcurrency:
    @pytest.mark.parametrize("workers", [4, 8])
    def test_locked_json_update_serializes_writers(self, tmp_path: Path, workers: int) -> None:
        target = tmp_path / "counter.json"
        target.write_text(json.dumps({"n": 0}))

        ctx = mp.get_context("fork")
        processes = [
            ctx.Process(target=_concurrent_increment, args=(str(target), "n"))
            for _ in range(workers)
        ]
        for p in processes:
            p.start()
        for p in processes:
            p.join(timeout=10)
            assert p.exitcode == 0, f"worker failed with {p.exitcode}"

        assert json.loads(target.read_text())["n"] == workers
