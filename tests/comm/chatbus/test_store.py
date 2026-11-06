from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from dev10x.domain.common.result import ErrorResult, SuccessResult

from dev10x.comm.chatbus.schema import SCHEMA_VERSION
from dev10x.comm.chatbus.store import _rollback, migrate, open_store, write_transaction


class TestChatBusDbPath:
    def test_lives_under_config_home(self, config_home: Path, db_path: Path) -> None:
        assert db_path == config_home / "chat-bus" / "bus.sqlite3"


class TestOpenStore:
    @pytest.fixture
    def tables(self, conn: sqlite3.Connection) -> set[str]:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        return {row[0] for row in rows}

    def test_creates_every_table(self, tables: set[str]) -> None:
        assert tables == {
            "events",
            "commands",
            "work_items",
            "cursors",
            "reaction_snapshot",
            "gaps",
        }

    def test_records_schema_version(self, conn: sqlite3.Connection) -> None:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION

    def test_uses_wal_journal(self, conn: sqlite3.Connection) -> None:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"

    def test_enforces_foreign_keys(self, conn: sqlite3.Connection) -> None:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


class TestPrivateFiles:
    """The store holds untrusted message text, so only the owner may read it."""

    @pytest.fixture
    def modes(self, conn: sqlite3.Connection, db_path: Path) -> dict[str, int]:
        conn.execute(
            "INSERT INTO cursors (space, last_event_time, last_resource_name, updated_at)"
            " VALUES ('spaces/X', 't', 'n', 'u')"
        )
        return {
            "dir": db_path.parent.stat().st_mode & 0o777,
            "db": db_path.stat().st_mode & 0o777,
            "wal": db_path.with_name(db_path.name + "-wal").stat().st_mode & 0o777,
        }

    def test_owner_only(self, modes: dict[str, int]) -> None:
        assert modes == {"dir": 0o700, "db": 0o600, "wal": 0o600}


class TestExistingWideDirectory:
    @pytest.fixture
    def mode(self, db_path: Path) -> Iterator[int]:
        db_path.parent.mkdir(mode=0o755, parents=True)
        db_path.parent.chmod(0o755)
        opened = open_store(path=db_path)
        assert isinstance(opened, SuccessResult)
        yield db_path.parent.stat().st_mode & 0o777
        opened.value.close()

    def test_tightens_existing_directory(self, mode: int) -> None:
        assert mode == 0o700


class TestChmodFailure:
    @pytest.fixture
    def result(self, db_path: Path, monkeypatch: pytest.MonkeyPatch) -> ErrorResult:
        def refuse(self: Path, mode: int) -> None:
            raise PermissionError(f"chmod {mode:o} refused")

        monkeypatch.setattr(Path, "chmod", refuse)
        opened = open_store(path=db_path)
        assert isinstance(opened, ErrorResult)
        return opened

    def test_reports_restriction_failure(self, result: ErrorResult) -> None:
        assert "Cannot restrict access" in result.error


class TestReopen:
    @pytest.fixture
    def reopened(self, conn: sqlite3.Connection, db_path: Path) -> Iterator[SuccessResult]:
        result = open_store(path=db_path)
        assert isinstance(result, SuccessResult)
        yield result
        result.value.close()

    def test_second_open_keeps_version(self, reopened: SuccessResult) -> None:
        assert reopened.value.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION


class TestNewerSchema:
    @pytest.fixture
    def result(self, conn: sqlite3.Connection, db_path: Path) -> ErrorResult:
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
        opened = open_store(path=db_path)
        assert isinstance(opened, ErrorResult)
        return opened

    def test_refuses_to_open(self, result: ErrorResult) -> None:
        assert "newer dev10x" in result.error

    def test_reports_versions(self, result: ErrorResult) -> None:
        assert result.details == {"found": SCHEMA_VERSION + 1, "supported": SCHEMA_VERSION}


class TestUnopenablePath:
    @pytest.fixture
    def result(self, tmp_path: Path) -> ErrorResult:
        blocker = tmp_path / "not-a-dir"
        blocker.write_text("")
        opened = open_store(path=blocker / "bus.sqlite3")
        assert isinstance(opened, ErrorResult)
        return opened

    def test_reports_path(self, result: ErrorResult, tmp_path: Path) -> None:
        assert str(tmp_path / "not-a-dir") in result.error


class TestNotADatabase:
    """A PRAGMA failing after connect returns an error and closes the handle."""

    @pytest.fixture
    def result(self, tmp_path: Path) -> ErrorResult:
        garbage = tmp_path / "bus.sqlite3"
        garbage.write_bytes(b"this is not an sqlite file" * 100)
        opened = open_store(path=garbage)
        assert isinstance(opened, ErrorResult)
        return opened

    def test_reports_configuration_failure(self, result: ErrorResult) -> None:
        assert "Cannot configure" in result.error


class TestWalUnavailable:
    """An in-memory database cannot use WAL; the store refuses rather than degrade."""

    @pytest.fixture
    def result(self) -> ErrorResult:
        opened = open_store(path=Path(":memory:"))
        assert isinstance(opened, ErrorResult)
        return opened

    def test_names_refused_mode(self, result: ErrorResult) -> None:
        assert result.details == {"path": ":memory:", "journal_mode": "memory"}


class TestMigrationFailure:
    @pytest.fixture
    def result(self, tmp_path: Path) -> ErrorResult:
        raw = sqlite3.connect(tmp_path / "broken.sqlite3", isolation_level=None)
        raw.execute("CREATE TABLE events (id INTEGER)")
        migrated = migrate(conn=raw)
        raw.close()
        assert isinstance(migrated, ErrorResult)
        return migrated

    def test_reports_migration_error(self, result: ErrorResult) -> None:
        assert "migration failed" in result.error


class TestWriteTransaction:
    @pytest.fixture
    def rolled_back(self, conn: sqlite3.Connection) -> int:
        with pytest.raises(RuntimeError), write_transaction(conn=conn) as tx:
            tx.execute(
                "INSERT INTO cursors (space, last_event_time, last_resource_name, updated_at)"
                " VALUES ('spaces/X', 't', 'n', 'u')"
            )
            raise RuntimeError("boom")
        return conn.execute("SELECT COUNT(*) FROM cursors").fetchone()[0]

    def test_rolls_back_on_error(self, rolled_back: int) -> None:
        assert rolled_back == 0


class TestFailedCommit:
    """A COMMIT that fails must not leave the long-lived connection mid-transaction."""

    @pytest.fixture
    def raw(self, tmp_path: Path) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(tmp_path / "deferred.sqlite3", isolation_level=None)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
        connection.execute(
            "CREATE TABLE child (parent_id INTEGER"
            " REFERENCES parent (id) DEFERRABLE INITIALLY DEFERRED)"
        )
        yield connection
        connection.close()

    @pytest.fixture
    def commit_error(self, raw: sqlite3.Connection) -> sqlite3.IntegrityError:
        with pytest.raises(sqlite3.IntegrityError) as caught, write_transaction(conn=raw) as tx:
            tx.execute("INSERT INTO child (parent_id) VALUES (42)")
        return caught.value

    def test_raises_commit_error(self, commit_error: sqlite3.IntegrityError) -> None:
        assert "FOREIGN KEY" in str(commit_error)

    def test_connection_left_outside_transaction(
        self,
        raw: sqlite3.Connection,
        commit_error: sqlite3.IntegrityError,
    ) -> None:
        assert raw.in_transaction is False

    def test_next_transaction_starts(
        self,
        raw: sqlite3.Connection,
        commit_error: sqlite3.IntegrityError,
    ) -> None:
        with write_transaction(conn=raw) as tx:
            tx.execute("INSERT INTO parent (id) VALUES (1)")
        assert raw.execute("SELECT COUNT(*) FROM parent").fetchone()[0] == 1


class TestAlreadyRolledBack:
    """When SQLite has already rolled back, the original error is the one raised."""

    @pytest.fixture
    def raised(self, conn: sqlite3.Connection) -> RuntimeError:
        with pytest.raises(RuntimeError) as caught, write_transaction(conn=conn) as tx:
            tx.execute("ROLLBACK")
            raise RuntimeError("disk full")
        return caught.value

    def test_original_error_surfaces(self, raised: RuntimeError) -> None:
        assert str(raised) == "disk full"


class _RefusingRollback:
    in_transaction = True

    def execute(self, sql: str) -> None:
        raise sqlite3.OperationalError(f"cannot run {sql}")


class TestRollbackFailure:
    """A ROLLBACK that itself fails is logged instead of replacing the original error."""

    @pytest.fixture
    def logged(self, caplog: pytest.LogCaptureFixture) -> list[str]:
        with caplog.at_level(logging.ERROR, logger="dev10x.comm.chatbus.store"):
            _rollback(conn=_RefusingRollback())  # type: ignore[arg-type]
        return [record.getMessage() for record in caplog.records]

    def test_logs_rollback_failure(self, logged: list[str]) -> None:
        assert logged == [
            "Chat bus rollback failed after an earlier error: cannot run ROLLBACK",
        ]
