from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from dev10x.comm.chatbus.schema import MIGRATIONS, SCHEMA_VERSION
from dev10x.domain.common.result import ErrorResult, Result, err, ok

BUSY_TIMEOUT_SECONDS = 5.0
# The store holds untrusted Chat message text; keep it private to the
# user. SQLite gives the -wal and -shm files the database file's mode.
STORE_DIR_MODE = 0o700
STORE_FILE_MODE = 0o600

log = logging.getLogger(__name__)


@contextmanager
def write_transaction(*, conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    # ADR-0035 D4: the daemon and the MCP tools both write, so every
    # write takes the RESERVED lock up front instead of upgrading a
    # read lock mid-transaction, which is where SQLITE_BUSY deadlocks.
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        _rollback(conn=conn)
        raise


def _rollback(*, conn: sqlite3.Connection) -> None:
    # SQLite already rolled back on SQLITE_FULL / IOERR / NOMEM, and a
    # second ROLLBACK would raise and hide the error that caused it.
    if not conn.in_transaction:
        return
    try:
        conn.execute("ROLLBACK")
    except sqlite3.Error as exc:
        log.error("Chat bus rollback failed after an earlier error: %s", exc)


def migrate(*, conn: sqlite3.Connection) -> Result[int]:
    try:
        with write_transaction(conn=conn) as tx:
            version = tx.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                return err(
                    "The Chat bus store was written by a newer dev10x. Upgrade dev10x to open it.",
                    found=version,
                    supported=SCHEMA_VERSION,
                )
            for statements in MIGRATIONS[version:]:
                for statement in statements:
                    tx.execute(statement)
            tx.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    except sqlite3.Error as exc:
        log.error("Chat bus schema migration failed: %s", exc)
        return err(f"Chat bus schema migration failed: {exc}")
    return ok(SCHEMA_VERSION)


def configure(*, conn: sqlite3.Connection, path: Path) -> Result[None]:
    try:
        conn.row_factory = sqlite3.Row
        journal_mode = str(conn.execute("PRAGMA journal_mode = WAL").fetchone()[0])
        conn.execute("PRAGMA foreign_keys = ON")
    except sqlite3.Error as exc:
        log.error("Cannot configure the Chat bus store at %s: %s", path, exc)
        return err(f"Cannot configure the Chat bus store at {path}: {exc}", path=str(path))
    # SQLite keeps the old mode instead of raising where WAL is
    # unavailable (e.g. some network filesystems); two writers need WAL.
    if journal_mode.lower() != "wal":
        log.error("Chat bus store at %s refused WAL mode (got %s)", path, journal_mode)
        return err(
            f"The Chat bus store at {path} needs WAL journal mode, got {journal_mode}",
            path=str(path),
            journal_mode=journal_mode,
        )
    return ok(None)


def _restrict_file(*, path: Path) -> Result[None]:
    # The private directory already shields a new file; this repairs a
    # database file left wider by an older version or a manual copy.
    try:
        path.chmod(STORE_FILE_MODE)
    except OSError as exc:
        log.error("Cannot restrict access to the Chat bus store at %s: %s", path, exc)
        return err(f"Cannot restrict access to the Chat bus store at {path}: {exc}")
    return ok(None)


def open_store(*, path: Path) -> Result[sqlite3.Connection]:
    try:
        path.parent.mkdir(mode=STORE_DIR_MODE, parents=True, exist_ok=True)
        # mkdir(mode=...) leaves an existing directory alone. Tighten it
        # before SQLite creates any file inside, so none is ever exposed.
        path.parent.chmod(STORE_DIR_MODE)
        conn = sqlite3.connect(path, timeout=BUSY_TIMEOUT_SECONDS, isolation_level=None)
    except (OSError, sqlite3.Error) as exc:
        log.error("Cannot open the Chat bus store at %s: %s", path, exc)
        return err(f"Cannot open the Chat bus store at {path}: {exc}")
    steps: tuple[Callable[[], Result[object]], ...] = (
        lambda: configure(conn=conn, path=path),
        lambda: _restrict_file(path=path),
        lambda: migrate(conn=conn),
    )
    for step in steps:
        outcome = step()
        if isinstance(outcome, ErrorResult):
            conn.close()
            return outcome
    return ok(conn)
