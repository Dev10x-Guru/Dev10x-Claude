from __future__ import annotations

import json
import multiprocessing as mp
from pathlib import Path

import pytest
import yaml

from dev10x.domain.file_locks import (
    atomic_write_bytes,
    atomic_write_text,
    file_lock,
    locked_json_update,
    locked_yaml_update,
)


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


def _concurrent_increment(path_str: str, key: str) -> None:
    path = Path(path_str)
    with locked_json_update(path) as data:
        data[key] = data.get(key, 0) + 1


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
