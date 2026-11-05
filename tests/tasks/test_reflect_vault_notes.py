"""Locked, idempotent index/log writes for dev10x:reflect (GH-1822)."""

from __future__ import annotations

import multiprocessing
from collections.abc import Generator
from datetime import date
from pathlib import Path

import pytest
from dev10x.domain.common.result import ErrorResult, SuccessResult
from dev10x.domain.dev10x_paths import Dev10xConfigDir
from dev10x.domain.file_locks import LockTimeoutError

from dev10x.tasks.reflect import (
    NoteAction,
    NoteWrite,
    VaultConfig,
    add_index_line,
    add_log_entry,
    vault_notes,
)

DAY = date(2026, 11, 5)
WRITERS = 8


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    path = tmp_path / "vault"
    (path / "Retros").mkdir(parents=True)
    return path


@pytest.fixture
def config(vault: Path) -> VaultConfig:
    return VaultConfig(source="test", configured=True, vault=vault, folders={"retro": "Retros"})


def _write(result: object) -> NoteWrite:
    assert isinstance(result, SuccessResult), result
    return result.value


def _index(config: VaultConfig, line: str, *, seed: bool = False) -> NoteWrite:
    return _write(add_index_line(config=config, folder="Retros", line=line, seed_listing=seed))


def _log(config: VaultConfig, entry: str, *, day: date = DAY, create: bool = True) -> NoteWrite:
    return _write(
        add_log_entry(config=config, folder="Retros", entry=entry, day=day, create=create)
    )


class TestIndex:
    def test_creates_titled_index(self, config: VaultConfig, vault: Path) -> None:
        written = _index(config, "- [[A]] — first")

        assert written.action is NoteAction.CREATED
        assert (vault / "Retros" / "index.md").read_text() == "# Retros\n\n- [[A]] — first\n"

    def test_seed_listing_names_existing_notes(self, config: VaultConfig, vault: Path) -> None:
        (vault / "Retros" / "Old.md").write_text("x")
        (vault / "Retros" / "log.md").write_text("x")

        _index(config, "- [[New]]", seed=True)

        assert (vault / "Retros" / "index.md").read_text() == (
            "# Retros\n\n- [[Old]]\n- [[New]]\n"
        )

    def test_seed_listing_in_new_folder(self, config: VaultConfig, vault: Path) -> None:
        written = _write(
            add_index_line(config=config, folder="Fresh", line="- [[A]]", seed_listing=True)
        )

        assert written.path.read_text() == "# Fresh\n\n- [[A]]\n"

    def test_appends_and_is_idempotent(self, config: VaultConfig, vault: Path) -> None:
        (vault / "Retros" / "index.md").write_text("# Retros\n- [[A]]")

        first = _index(config, "- [[B]]")
        again = _index(config, "  - [[B]]  ")

        assert (first.action, again.action) == (NoteAction.APPENDED, NoteAction.UNCHANGED)
        assert (vault / "Retros" / "index.md").read_text() == "# Retros\n- [[A]]\n- [[B]]\n"

    def test_lock_lives_outside_the_vault(self, config: VaultConfig, vault: Path) -> None:
        _index(config, "- [[A]]")

        assert sorted(p.name for p in (vault / "Retros").iterdir()) == ["index.md"]
        assert any(Dev10xConfigDir.reflect_locks_dir().iterdir())

    @pytest.mark.parametrize(
        ("folder", "line", "message"),
        [
            ("../escape", "- x", "must not contain"),
            ("Retros", "   ", "must not be empty"),
            ("Retros", "- [[A]]\n- [[B]]", "single line"),
            ("Retros", "- [[A]]\r- [[B]]", "single line"),
        ],
    )
    def test_rejects_bad_input(
        self, config: VaultConfig, folder: str, line: str, message: str
    ) -> None:
        result = add_index_line(config=config, folder=folder, line=line)

        assert isinstance(result, ErrorResult)
        assert message in result.error

    def test_unconfigured_vault_is_an_error(self) -> None:
        config = VaultConfig(source="test", configured=False, reason="no vault")

        result = add_index_line(config=config, folder="Retros", line="- x")

        assert isinstance(result, ErrorResult)
        assert result.error == "no vault"


class TestLog:
    def test_skips_folder_without_log(self, config: VaultConfig) -> None:
        written = _log(config, "entry", create=False)

        assert written.action is NoteAction.SKIPPED
        assert not written.path.exists()

    def test_creates_log_with_day_heading(self, config: VaultConfig, vault: Path) -> None:
        written = _log(config, "Retro: checkout outage")

        assert written.action is NoteAction.CREATED
        assert (vault / "Retros" / "log.md").read_text() == (
            "# Retros\n\n## 2026-11-05\n- Retro: checkout outage\n"
        )

    @pytest.mark.parametrize(
        ("initial", "expected"),
        [
            pytest.param(
                "# Log\n\n## 2026-11-01\n- o\n",
                "# Log\n\n## 2026-11-05\n- x\n\n## 2026-11-01\n- o\n",
                id="above-older-days",
            ),
            pytest.param(
                "# Log\n\n## 2026-11-09\n- n\n\n## 2026-11-01\n- o\n",
                "# Log\n\n## 2026-11-09\n- n\n\n## 2026-11-05\n- x\n\n## 2026-11-01\n- o\n",
                id="between-newer-and-older",
            ),
            pytest.param(
                "# Log\n\n## 2026-11-09\n- n\n",
                "# Log\n\n## 2026-11-09\n- n\n\n## 2026-11-05\n- x\n",
                id="after-all-newer-days",
            ),
        ],
    )
    def test_new_day_keeps_newest_first_order(
        self, config: VaultConfig, vault: Path, initial: str, expected: str
    ) -> None:
        (vault / "Retros" / "log.md").write_text(initial)

        _log(config, "- x")

        assert (vault / "Retros" / "log.md").read_text() == expected

    def test_same_day_entries_stack_under_one_heading(
        self, config: VaultConfig, vault: Path
    ) -> None:
        (vault / "Retros" / "log.md").write_text("# Log\n\n## 2026-11-05\n- a\n\n## 2026-11-01\n")

        appended = _log(config, "b")
        repeated = _log(config, "a")

        assert (appended.action, repeated.action) == (NoteAction.APPENDED, NoteAction.UNCHANGED)
        assert (vault / "Retros" / "log.md").read_text() == (
            "# Log\n\n## 2026-11-05\n- a\n- b\n\n## 2026-11-01\n"
        )

    @pytest.mark.parametrize(
        ("entry", "message"),
        [
            (" ", "must not be empty"),
            ("ok\n## 2026-01-01", "single line"),
        ],
    )
    def test_rejects_bad_entry(self, config: VaultConfig, entry: str, message: str) -> None:
        result = add_log_entry(config=config, folder="Retros", entry=entry, day=DAY)

        assert isinstance(result, ErrorResult)
        assert message in result.error

    def test_rejects_escaping_folder(self, config: VaultConfig) -> None:
        result = add_log_entry(config=config, folder="/tmp", entry="x", day=DAY)

        assert isinstance(result, ErrorResult)

    def test_note_write_serializes(self, config: VaultConfig) -> None:
        payload = _log(config, "x").to_dict()

        assert payload["action"] == "created"
        assert payload["reason"] == ""


class TestFailures:
    @pytest.fixture
    def held_lock(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def refuse(*_args: object, **_kwargs: object) -> None:
            raise LockTimeoutError("busy. Please try again.")

        monkeypatch.setattr(vault_notes, "file_lock", refuse)

    @pytest.fixture
    def broken_writer(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def explode(*_args: object, **_kwargs: object) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(vault_notes, "atomic_write_text", explode)

    @pytest.mark.usefixtures("held_lock")
    def test_index_lock_timeout(self, config: VaultConfig) -> None:
        result = add_index_line(config=config, folder="Retros", line="- x")

        assert isinstance(result, ErrorResult)
        assert "Please try again" in result.error

    @pytest.mark.usefixtures("held_lock")
    def test_log_lock_timeout(self, config: VaultConfig) -> None:
        result = add_log_entry(config=config, folder="Retros", entry="x", day=DAY, create=True)

        assert isinstance(result, ErrorResult)

    @pytest.mark.usefixtures("broken_writer")
    def test_index_write_error(self, config: VaultConfig) -> None:
        result = add_index_line(config=config, folder="Retros", line="- x")

        assert isinstance(result, ErrorResult)
        assert "disk full" in result.error

    @pytest.mark.usefixtures("broken_writer")
    def test_log_write_error(self, config: VaultConfig) -> None:
        result = add_log_entry(config=config, folder="Retros", entry="x", day=DAY, create=True)

        assert isinstance(result, ErrorResult)
        assert "disk full" in result.error


def _concurrent_writer(config: VaultConfig, number: int) -> None:
    indexed = add_index_line(config=config, folder="Retros", line=f"- [[Note {number}]]")
    logged = add_log_entry(
        config=config, folder="Retros", entry=f"note {number}", day=DAY, create=True
    )
    assert isinstance(indexed, SuccessResult), indexed
    assert isinstance(logged, SuccessResult), logged


@pytest.fixture
def worker_exit_codes(config: VaultConfig) -> Generator[list[int | None], None, None]:
    context = multiprocessing.get_context("fork")
    workers = [
        context.Process(target=_concurrent_writer, args=(config, number))
        for number in range(WRITERS)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=30)
    yield [worker.exitcode for worker in workers]
    for worker in workers:
        worker.kill()


def test_concurrent_writers_lose_nothing(worker_exit_codes: list[int | None], vault: Path) -> None:
    index = (vault / "Retros" / "index.md").read_text()
    log = (vault / "Retros" / "log.md").read_text()
    assert worker_exit_codes == [0] * WRITERS
    assert all(f"- [[Note {n}]]" in index for n in range(WRITERS))
    assert all(f"- note {n}\n" in log for n in range(WRITERS))
    assert log.count("## 2026-11-05") == 1
