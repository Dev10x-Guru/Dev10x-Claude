from __future__ import annotations

import logging
import os
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from dev10x.domain.common.result import ErrorResult
from dev10x.domain.dev10x_paths import CONFIG_HOME_ENV_VAR

from dev10x.comm.chatbus.schema import MIGRATIONS, SCHEMA_VERSION
from dev10x.comm.chatbus.store import (
    _rollback,
    configure,
    migrate,
    open_store,
    write_transaction,
)
from tests.comm.chatbus.factories import expect_error, unwrap


class TestChatBusDbPath:
    def test_lives_under_config_home(self, db_path: Path) -> None:
        assert db_path == Path(os.environ[CONFIG_HOME_ENV_VAR]) / "chat-bus" / "bus.sqlite3"


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
            "approvals",
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


class TestExistingWideStore:
    """A directory and file left wide by an older version are tightened on open."""

    @pytest.fixture
    def modes(self, db_path: Path) -> Iterator[tuple[int, int]]:
        db_path.parent.mkdir(mode=0o755, parents=True)
        db_path.parent.chmod(0o755)
        db_path.touch()
        db_path.chmod(0o644)
        conn = unwrap(open_store(path=db_path))
        yield (db_path.parent.stat().st_mode & 0o777, db_path.stat().st_mode & 0o777)
        conn.close()

    def test_tightens_directory_and_file(self, modes: tuple[int, int]) -> None:
        assert modes == (0o700, 0o600)


class TestChmodFailure:
    @pytest.mark.parametrize(
        ("refused_mode", "message"),
        [
            pytest.param(0o700, "Cannot open the Chat bus store", id="directory"),
            pytest.param(0o600, "Cannot restrict access", id="file"),
        ],
    )
    def test_reports_failure(
        self,
        db_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        refused_mode: int,
        message: str,
    ) -> None:
        original = Path.chmod

        def refuse(self: Path, mode: int) -> None:
            if mode == refused_mode:
                raise PermissionError(f"chmod {mode:o} refused")
            original(self, mode)

        monkeypatch.setattr(Path, "chmod", refuse)
        assert message in expect_error(open_store(path=db_path)).error


class TestReopen:
    @pytest.fixture
    def reopened(self, conn: sqlite3.Connection, db_path: Path) -> Iterator[sqlite3.Connection]:
        second = unwrap(open_store(path=db_path))
        yield second
        second.close()

    def test_second_open_keeps_version(self, reopened: sqlite3.Connection) -> None:
        assert reopened.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION


class TestUpgradeFromVersionOne:
    """A phase 1 store gains the GH-1839 authorization columns and keeps its rows."""

    @pytest.fixture
    def upgraded(self, tmp_path: Path) -> Iterator[sqlite3.Connection]:
        raw = sqlite3.connect(tmp_path / "v1.sqlite3", isolation_level=None)
        raw.row_factory = sqlite3.Row
        for statement in MIGRATIONS[0]:
            raw.execute(statement)
        raw.execute("PRAGMA user_version = 1")
        raw.execute(
            "INSERT INTO events (event_key, type, space, resource_name, sender, event_time,"
            " received_at, source, payload) VALUES ('k', 't', 's', 'r', 'u', 'x', 'x', 'poll', '{}')"
        )
        raw.execute(
            "INSERT INTO commands (event_id, actor, verb, authorized, reason, created_at)"
            " VALUES (1, 'u', 'v', 0, 'old', 'x')"
        )
        unwrap(migrate(conn=raw))
        yield raw
        raw.close()

    def test_keeps_old_command(self, upgraded: sqlite3.Connection) -> None:
        row = upgraded.execute("SELECT reason, outcome, work_item_id FROM commands").fetchone()
        assert tuple(row) == ("old", None, None)

    def test_one_command_per_event(self, upgraded: sqlite3.Connection) -> None:
        with pytest.raises(sqlite3.IntegrityError):
            upgraded.execute(
                "INSERT INTO commands (event_id, actor, verb, authorized, reason, created_at)"
                " VALUES (1, 'u', 'v', 0, 'again', 'x')"
            )


class TestNewerSchema:
    @pytest.fixture
    def result(self, conn: sqlite3.Connection, db_path: Path) -> ErrorResult:
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
        return expect_error(open_store(path=db_path))

    def test_refuses_to_open(self, result: ErrorResult) -> None:
        assert "newer dev10x" in result.error

    def test_reports_versions(self, result: ErrorResult) -> None:
        assert result.details == {"found": SCHEMA_VERSION + 1, "supported": SCHEMA_VERSION}


class TestUnopenablePath:
    @pytest.fixture
    def result(self, tmp_path: Path) -> ErrorResult:
        blocker = tmp_path / "not-a-dir"
        blocker.write_text("")
        return expect_error(open_store(path=blocker / "bus.sqlite3"))

    def test_reports_path(self, result: ErrorResult, tmp_path: Path) -> None:
        assert str(tmp_path / "not-a-dir") in result.error


class TestNotADatabase:
    """A PRAGMA failing after connect returns an error and closes the handle."""

    @pytest.fixture
    def result(self, tmp_path: Path) -> ErrorResult:
        garbage = tmp_path / "bus.sqlite3"
        garbage.write_bytes(b"this is not an sqlite file" * 100)
        return expect_error(open_store(path=garbage))

    def test_reports_configuration_failure(self, result: ErrorResult) -> None:
        assert "Cannot configure" in result.error


class TestWalUnavailable:
    """An in-memory database cannot use WAL; configuration refuses rather than degrade."""

    @pytest.fixture
    def result(self) -> Iterator[ErrorResult]:
        memory = sqlite3.connect(":memory:", isolation_level=None)
        yield expect_error(configure(conn=memory, path=Path("in-memory")))
        memory.close()

    def test_names_refused_mode(self, result: ErrorResult) -> None:
        assert result.details == {"path": "in-memory", "journal_mode": "memory"}


class TestMigrationFailure:
    @pytest.fixture
    def result(self, tmp_path: Path) -> Iterator[ErrorResult]:
        raw = sqlite3.connect(tmp_path / "broken.sqlite3", isolation_level=None)
        raw.execute("CREATE TABLE events (id INTEGER)")
        yield expect_error(migrate(conn=raw))
        raw.close()

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

    @pytest.mark.usefixtures("commit_error")
    def test_connection_left_outside_transaction(self, raw: sqlite3.Connection) -> None:
        assert raw.in_transaction is False

    @pytest.mark.usefixtures("commit_error")
    def test_next_transaction_starts(self, raw: sqlite3.Connection) -> None:
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
