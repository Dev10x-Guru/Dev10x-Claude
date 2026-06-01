"""Tests for daemon lifecycle management (GH-336).

Covers:
- PID file write / read / remove
- Socket file path helpers
- Stale-lock detection (is_stale_pid_file, clear_stale_lock_files)
- is_pid_alive with real / fake PIDs
- HealthServer: starts, answers PING with PONG, stops cleanly
- ping_daemon: returns True when server up, False when down
- is_daemon_healthy: requires both PID alive and socket PONG
- request_shutdown: sends SIGTERM to real process, handles missing PID
- wait_for_shutdown: returns True when process exits, False on timeout
- shutdown_daemon: full graceful-shutdown flow (SIGTERM → wait → SIGKILL)
- DaemonLifecycle context manager: start/stop, PID written, health OK
- Environment variable overrides: DEV10X_MCP_PID_DIR,
  DEV10X_MCP_HEALTH_TIMEOUT, DEV10X_MCP_SHUTDOWN_TIMEOUT
"""

from __future__ import annotations

import os
import signal
import threading
import time
from collections.abc import Generator
from pathlib import Path
from unittest.mock import patch

import pytest

from dev10x.mcp.daemon import (
    DaemonLifecycle,
    HealthServer,
    _health_timeout,
    _pid_dir,
    _shutdown_timeout,
    clear_stale_lock_files,
    is_daemon_healthy,
    is_pid_alive,
    is_stale_pid_file,
    pid_file_path,
    ping_daemon,
    read_pid_file,
    remove_pid_file,
    remove_socket_file,
    request_shutdown,
    shutdown_daemon,
    socket_file_path,
    wait_for_shutdown,
    write_pid_file,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_pid_dir(tmp_path: Path) -> Path:
    """Return a temporary directory for PID and socket files."""
    d = tmp_path / "mcp"
    d.mkdir()
    return d


@pytest.fixture()
def running_health_server(tmp_pid_dir: Path) -> Generator[HealthServer, None, None]:
    """Start a HealthServer in a background thread; stop it after the test."""
    server = HealthServer(tmp_pid_dir)
    server.start()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.close()
    thread.join(timeout=2.0)


# ---------------------------------------------------------------------------
# Environment variable helpers
# ---------------------------------------------------------------------------


class TestPidDir:
    def test_default_when_env_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DEV10X_MCP_PID_DIR", raising=False)
        result = _pid_dir()
        assert result == Path.home() / ".local" / "share" / "dev10x" / "mcp"

    def test_reads_env_var(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("DEV10X_MCP_PID_DIR", str(tmp_path))
        assert _pid_dir() == tmp_path

    def test_ignores_empty_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEV10X_MCP_PID_DIR", "")
        result = _pid_dir()
        assert result == Path.home() / ".local" / "share" / "dev10x" / "mcp"


class TestHealthTimeout:
    def test_default_is_three(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DEV10X_MCP_HEALTH_TIMEOUT", raising=False)
        assert _health_timeout() == 3.0

    def test_reads_float(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEV10X_MCP_HEALTH_TIMEOUT", "1.5")
        assert _health_timeout() == 1.5

    def test_invalid_falls_back_to_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEV10X_MCP_HEALTH_TIMEOUT", "not-a-number")
        assert _health_timeout() == 3.0


class TestShutdownTimeout:
    def test_default_is_ten(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DEV10X_MCP_SHUTDOWN_TIMEOUT", raising=False)
        assert _shutdown_timeout() == 10.0

    def test_reads_float(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEV10X_MCP_SHUTDOWN_TIMEOUT", "5.0")
        assert _shutdown_timeout() == 5.0

    def test_invalid_falls_back_to_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEV10X_MCP_SHUTDOWN_TIMEOUT", "bad")
        assert _shutdown_timeout() == 10.0


# ---------------------------------------------------------------------------
# PID file helpers
# ---------------------------------------------------------------------------


class TestPidFilePath:
    def test_returns_path_in_pid_dir(self, tmp_pid_dir: Path) -> None:
        path = pid_file_path(tmp_pid_dir)
        assert path.parent == tmp_pid_dir
        assert path.suffix == ".pid"

    def test_socket_file_in_same_dir(self, tmp_pid_dir: Path) -> None:
        assert socket_file_path(tmp_pid_dir).parent == tmp_pid_dir


class TestWriteReadRemovePidFile:
    def test_write_creates_file(self, tmp_pid_dir: Path) -> None:
        write_pid_file(pid=12345, pid_dir=tmp_pid_dir)
        assert pid_file_path(tmp_pid_dir).exists()

    def test_write_stores_pid(self, tmp_pid_dir: Path) -> None:
        write_pid_file(pid=42, pid_dir=tmp_pid_dir)
        assert read_pid_file(tmp_pid_dir) == 42

    def test_write_defaults_to_own_pid(self, tmp_pid_dir: Path) -> None:
        write_pid_file(pid_dir=tmp_pid_dir)
        assert read_pid_file(tmp_pid_dir) == os.getpid()

    def test_write_creates_parent_dir(self, tmp_path: Path) -> None:
        nested = tmp_path / "a" / "b" / "c"
        write_pid_file(pid=1, pid_dir=nested)
        assert pid_file_path(nested).exists()

    def test_read_returns_none_when_missing(self, tmp_pid_dir: Path) -> None:
        assert read_pid_file(tmp_pid_dir) is None

    def test_read_returns_none_on_invalid_content(self, tmp_pid_dir: Path) -> None:
        pid_file_path(tmp_pid_dir).write_text("not-an-int")
        assert read_pid_file(tmp_pid_dir) is None

    def test_remove_deletes_file(self, tmp_pid_dir: Path) -> None:
        write_pid_file(pid=99, pid_dir=tmp_pid_dir)
        remove_pid_file(tmp_pid_dir)
        assert not pid_file_path(tmp_pid_dir).exists()

    def test_remove_ignores_missing(self, tmp_pid_dir: Path) -> None:
        remove_pid_file(tmp_pid_dir)  # Must not raise.

    def test_remove_socket_ignores_missing(self, tmp_pid_dir: Path) -> None:
        remove_socket_file(tmp_pid_dir)  # Must not raise.


# ---------------------------------------------------------------------------
# Stale-lock detection
# ---------------------------------------------------------------------------


class TestIsPidAlive:
    def test_own_pid_is_alive(self) -> None:
        assert is_pid_alive(os.getpid()) is True

    def test_nonexistent_pid_is_not_alive(self) -> None:
        # PID 0 is never a valid user-space process on Linux/macOS.
        # Use a very large PID unlikely to be running.
        assert is_pid_alive(999_999_999) is False


class TestIsStalePidFile:
    def test_no_pid_file_is_not_stale(self, tmp_pid_dir: Path) -> None:
        assert is_stale_pid_file(tmp_pid_dir) is False

    def test_live_pid_is_not_stale(self, tmp_pid_dir: Path) -> None:
        write_pid_file(pid=os.getpid(), pid_dir=tmp_pid_dir)
        assert is_stale_pid_file(tmp_pid_dir) is False

    def test_dead_pid_is_stale(self, tmp_pid_dir: Path) -> None:
        write_pid_file(pid=999_999_999, pid_dir=tmp_pid_dir)
        assert is_stale_pid_file(tmp_pid_dir) is True


class TestClearStaleLockFiles:
    def test_clears_stale_pid_and_socket(self, tmp_pid_dir: Path) -> None:
        write_pid_file(pid=999_999_999, pid_dir=tmp_pid_dir)
        # Create a fake socket file to check it is also removed.
        socket_file_path(tmp_pid_dir).touch()
        result = clear_stale_lock_files(tmp_pid_dir)
        assert result is True
        assert not pid_file_path(tmp_pid_dir).exists()
        assert not socket_file_path(tmp_pid_dir).exists()

    def test_no_action_when_daemon_running(self, tmp_pid_dir: Path) -> None:
        write_pid_file(pid=os.getpid(), pid_dir=tmp_pid_dir)
        result = clear_stale_lock_files(tmp_pid_dir)
        assert result is False
        assert pid_file_path(tmp_pid_dir).exists()

    def test_no_action_when_no_pid_file(self, tmp_pid_dir: Path) -> None:
        result = clear_stale_lock_files(tmp_pid_dir)
        assert result is False


# ---------------------------------------------------------------------------
# HealthServer and ping_daemon
# ---------------------------------------------------------------------------


class TestHealthServer:
    def test_ping_returns_pong(
        self,
        running_health_server: HealthServer,
        tmp_pid_dir: Path,
    ) -> None:
        assert ping_daemon(tmp_pid_dir, timeout=1.0) is True

    def test_ping_fails_when_server_stopped(self, tmp_pid_dir: Path) -> None:
        # Nothing is listening — ping must return False, not raise.
        assert ping_daemon(tmp_pid_dir, timeout=0.5) is False

    def test_server_stops_cleanly(self, tmp_pid_dir: Path) -> None:
        server = HealthServer(tmp_pid_dir)
        server.start()
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        assert ping_daemon(tmp_pid_dir, timeout=1.0) is True
        server.close()
        thread.join(timeout=2.0)
        # After close() the socket file should be gone.
        assert not socket_file_path(tmp_pid_dir).exists()

    def test_start_removes_leftover_socket(self, tmp_pid_dir: Path) -> None:
        # Pre-create a socket file to simulate a previous crash.
        socket_file_path(tmp_pid_dir).touch()
        server = HealthServer(tmp_pid_dir)
        server.start()
        server.close()

    def test_context_manager(self, tmp_pid_dir: Path) -> None:
        """HealthServer used as a plain object; close() is idempotent."""
        server = HealthServer(tmp_pid_dir)
        server.start()
        server.close()
        server.close()  # Second close must not raise.


# ---------------------------------------------------------------------------
# is_daemon_healthy
# ---------------------------------------------------------------------------


class TestIsDaemonHealthy:
    def test_healthy_when_pid_alive_and_socket_responds(
        self,
        running_health_server: HealthServer,
        tmp_pid_dir: Path,
    ) -> None:
        write_pid_file(pid=os.getpid(), pid_dir=tmp_pid_dir)
        assert is_daemon_healthy(tmp_pid_dir) is True

    def test_unhealthy_when_no_pid_file(self, tmp_pid_dir: Path) -> None:
        assert is_daemon_healthy(tmp_pid_dir) is False

    def test_unhealthy_when_pid_dead(
        self,
        running_health_server: HealthServer,
        tmp_pid_dir: Path,
    ) -> None:
        write_pid_file(pid=999_999_999, pid_dir=tmp_pid_dir)
        assert is_daemon_healthy(tmp_pid_dir) is False

    def test_unhealthy_when_socket_not_responding(self, tmp_pid_dir: Path) -> None:
        write_pid_file(pid=os.getpid(), pid_dir=tmp_pid_dir)
        # No HealthServer started — socket does not exist.
        assert is_daemon_healthy(tmp_pid_dir) is False


# ---------------------------------------------------------------------------
# Shutdown helpers
# ---------------------------------------------------------------------------


class TestRequestShutdown:
    def test_returns_false_when_no_pid_file(self, tmp_pid_dir: Path) -> None:
        assert request_shutdown(pid_dir=tmp_pid_dir) is False

    def test_returns_false_for_nonexistent_pid(self, tmp_pid_dir: Path) -> None:
        assert request_shutdown(pid=999_999_999, pid_dir=tmp_pid_dir) is False

    def test_sends_sigterm_to_explicit_pid(self, tmp_pid_dir: Path) -> None:
        received: list[int] = []

        original = signal.getsignal(signal.SIGTERM)
        signal.signal(signal.SIGTERM, lambda signum, _frame: received.append(signum))
        try:
            result = request_shutdown(pid=os.getpid(), pid_dir=tmp_pid_dir)
        finally:
            signal.signal(signal.SIGTERM, original)

        assert result is True
        assert signal.SIGTERM in received


class TestWaitForShutdown:
    def test_returns_true_when_process_already_dead(self) -> None:
        # pid 999_999_999 does not exist → immediately True
        assert wait_for_shutdown(pid=999_999_999, timeout=1.0) is True

    def test_returns_false_on_timeout(self) -> None:
        # Our own PID is alive and will not die during the test.
        result = wait_for_shutdown(pid=os.getpid(), timeout=0.3, poll_interval=0.1)
        assert result is False


class TestShutdownDaemon:
    def test_returns_false_when_no_pid_file(self, tmp_pid_dir: Path) -> None:
        assert shutdown_daemon(tmp_pid_dir) is False

    def test_cleans_up_when_pid_already_dead(self, tmp_pid_dir: Path) -> None:
        write_pid_file(pid=999_999_999, pid_dir=tmp_pid_dir)
        result = shutdown_daemon(tmp_pid_dir)
        assert result is True
        assert not pid_file_path(tmp_pid_dir).exists()

    def test_raises_when_force_false_and_timeout(self, tmp_pid_dir: Path) -> None:
        write_pid_file(pid=12345, pid_dir=tmp_pid_dir)
        with (
            patch("dev10x.mcp.daemon.is_pid_alive", return_value=True),
            patch("dev10x.mcp.daemon.request_shutdown", return_value=True),
            patch("dev10x.mcp.daemon.wait_for_shutdown", return_value=False),
            pytest.raises(RuntimeError, match="did not exit"),
        ):
            shutdown_daemon(tmp_pid_dir, timeout=0.2, force=False)

    def test_force_kills_and_removes_files(self, tmp_pid_dir: Path) -> None:
        """Mock the process-level calls to verify the SIGKILL escalation path."""
        write_pid_file(pid=12345, pid_dir=tmp_pid_dir)

        with (
            patch("dev10x.mcp.daemon.is_pid_alive", return_value=True),
            patch("dev10x.mcp.daemon.request_shutdown", return_value=True),
            patch("dev10x.mcp.daemon.wait_for_shutdown", return_value=False),
            patch("os.kill") as mock_kill,
        ):
            result = shutdown_daemon(tmp_pid_dir, timeout=0.1, force=True)

        mock_kill.assert_called_once_with(12345, signal.SIGKILL)
        assert result is False  # SIGKILL path returns False (not clean)
        assert not pid_file_path(tmp_pid_dir).exists()


# ---------------------------------------------------------------------------
# DaemonLifecycle context manager
# ---------------------------------------------------------------------------


class TestDaemonLifecycle:
    def test_start_writes_pid_and_health_responds(self, tmp_pid_dir: Path) -> None:
        lifecycle = DaemonLifecycle(tmp_pid_dir)
        lifecycle.start()
        try:
            assert read_pid_file(tmp_pid_dir) == os.getpid()
            assert ping_daemon(tmp_pid_dir, timeout=1.0) is True
        finally:
            lifecycle.stop()

    def test_stop_removes_pid_file(self, tmp_pid_dir: Path) -> None:
        lifecycle = DaemonLifecycle(tmp_pid_dir)
        lifecycle.start()
        lifecycle.stop()
        assert not pid_file_path(tmp_pid_dir).exists()

    def test_context_manager_protocol(self, tmp_pid_dir: Path) -> None:
        with DaemonLifecycle(tmp_pid_dir) as lc:
            assert read_pid_file(tmp_pid_dir) == os.getpid()
            assert ping_daemon(tmp_pid_dir, timeout=1.0) is True
            assert lc is not None
        # After __exit__ the PID file must be gone.
        assert not pid_file_path(tmp_pid_dir).exists()

    def test_start_clears_stale_files(self, tmp_pid_dir: Path) -> None:
        # Pre-populate stale files.
        write_pid_file(pid=999_999_999, pid_dir=tmp_pid_dir)
        socket_file_path(tmp_pid_dir).touch()

        lifecycle = DaemonLifecycle(tmp_pid_dir)
        lifecycle.start()
        try:
            # Stale PID was overwritten with our own PID.
            assert read_pid_file(tmp_pid_dir) == os.getpid()
        finally:
            lifecycle.stop()

    def test_stop_is_idempotent(self, tmp_pid_dir: Path) -> None:
        lifecycle = DaemonLifecycle(tmp_pid_dir)
        lifecycle.start()
        lifecycle.stop()
        lifecycle.stop()  # Second stop must not raise.

    def test_is_daemon_healthy_inside_context(self, tmp_pid_dir: Path) -> None:
        with DaemonLifecycle(tmp_pid_dir):
            # Give the health thread a moment to bind.
            time.sleep(0.05)
            assert is_daemon_healthy(tmp_pid_dir) is True
