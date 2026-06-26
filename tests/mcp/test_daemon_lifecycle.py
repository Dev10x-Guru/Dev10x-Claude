"""Integration tests for MCP daemon lifecycle (GH-563).

Covers gaps identified in the audit that were NOT already present in
test_daemon.py (PID/socket primitives) or test_wiring.py (static selection):

- Restart cycle: stop → start again using the same pid_dir
- Restart-safety: second start blocked while first is alive
- STDIO fallback integration: server.run() receives "stdio" when daemon absent
- Deleted-CWD recovery in MCP context (subprocess_utils._recover_process_cwd)
- StreamableHTTP concurrent tool call simulation via SessionStore backpressure
- Parametrized session TTL exhaustion across multiple TTL values
- Version-drift detection — DEFERRED (no production implementation yet)

All tests are deterministic and fast:
- No real daemon processes are spawned (mocked or in-process).
- No real network ports are bound.
- Real UNIX sockets are used only for HealthServer tests (localhost only,
  no network exposure).
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from dev10x.mcp.daemon import (
    DaemonLifecycle,
    is_daemon_healthy,
    pid_file_path,
    ping_daemon,
    read_pid_file,
    socket_file_path,
    write_pid_file,
)
from dev10x.mcp.session_store import SessionStore
from dev10x.mcp.wiring import select_transport_with_daemon_fallback

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_pid_dir(tmp_path: Path) -> Path:
    """Isolated PID/socket directory for each test."""
    d = tmp_path / "mcp"
    d.mkdir()
    return d


# ---------------------------------------------------------------------------
# Gap 1: Daemon restart lifecycle
# ---------------------------------------------------------------------------


class TestDaemonRestartLifecycle:
    """Verify that a daemon can be stopped and restarted cleanly."""

    def test_restart_after_clean_stop(self, tmp_pid_dir: Path) -> None:
        """Stop → start again: PID file is refreshed, health socket responds."""
        lifecycle = DaemonLifecycle(pid_dir=tmp_pid_dir)
        lifecycle.start()
        lifecycle.stop()

        # After stop, PID file must be gone.
        assert not pid_file_path(tmp_pid_dir).exists()

        # Start again: should succeed with a fresh PID and health socket.
        lifecycle2 = DaemonLifecycle(pid_dir=tmp_pid_dir)
        lifecycle2.start()
        try:
            assert read_pid_file(tmp_pid_dir) == os.getpid()
            assert ping_daemon(pid_dir=tmp_pid_dir, timeout=1.0) is True
        finally:
            lifecycle2.stop()

    def test_restart_clears_stale_files_from_previous_instance(
        self,
        tmp_pid_dir: Path,
    ) -> None:
        """Simulate a crashed daemon: stale PID + socket files remain.
        A fresh DaemonLifecycle.start() must clear them and succeed.
        """
        # Leave behind stale files as if the previous daemon crashed.
        write_pid_file(pid=999_999_999, pid_dir=tmp_pid_dir)
        socket_file_path(tmp_pid_dir).touch()

        lifecycle = DaemonLifecycle(pid_dir=tmp_pid_dir)
        lifecycle.start()
        try:
            # Stale PID overwritten with our own.
            assert read_pid_file(tmp_pid_dir) == os.getpid()
            assert ping_daemon(pid_dir=tmp_pid_dir, timeout=1.0) is True
        finally:
            lifecycle.stop()

    def test_context_manager_restart(self, tmp_pid_dir: Path) -> None:
        """Two sequential context-manager uses of DaemonLifecycle succeed."""
        with DaemonLifecycle(pid_dir=tmp_pid_dir):
            pass  # First run — cleans up on __exit__

        # Second run on the same directory must not raise.
        with DaemonLifecycle(pid_dir=tmp_pid_dir) as lc:
            assert lc is not None
            assert read_pid_file(tmp_pid_dir) == os.getpid()

    def test_second_start_blocked_when_first_still_alive(
        self,
        tmp_pid_dir: Path,
    ) -> None:
        """Start a second DaemonLifecycle while the first is alive: must raise."""
        lifecycle1 = DaemonLifecycle(pid_dir=tmp_pid_dir)
        lifecycle1.start()
        try:
            lifecycle2 = DaemonLifecycle(pid_dir=tmp_pid_dir)
            with pytest.raises(RuntimeError, match="already running or lost the startup race"):
                lifecycle2.start()
            # The incumbent PID is untouched.
            assert read_pid_file(tmp_pid_dir) == os.getpid()
        finally:
            lifecycle1.stop()

    def test_health_server_reachable_after_restart(self, tmp_pid_dir: Path) -> None:
        """After a full stop/start cycle the health socket accepts new connections."""
        for _ in range(2):
            lifecycle = DaemonLifecycle(pid_dir=tmp_pid_dir)
            lifecycle.start()
            try:
                time.sleep(0.02)  # let health thread bind
                assert is_daemon_healthy(pid_dir=tmp_pid_dir) is True
            finally:
                lifecycle.stop()
            # Socket must be cleaned up between runs.
            assert not socket_file_path(tmp_pid_dir).exists()


# ---------------------------------------------------------------------------
# Gap 2: STDIO fallback integration
# ---------------------------------------------------------------------------


class TestStdioFallbackIntegration:
    """server_cli.main() must use STDIO when the daemon health check fails.

    These tests sit above the unit tests in test_wiring.py: they exercise
    the path from server_cli.main() → wiring → transport, verifying that
    the server.run() call receives the correct transport string when the
    daemon is absent or unhealthy.
    """

    def test_server_run_receives_stdio_when_no_daemon(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Absent daemon health check → server.run(transport="stdio")."""
        monkeypatch.delenv("DEV10X_MCP_TRANSPORT", raising=False)
        import dev10x.mcp.server_cli as cli_mod

        with (
            patch("dev10x.mcp.wiring.is_daemon_healthy", return_value=False),
            patch.object(cli_mod.server, "run") as mock_run,
        ):
            cli_mod.main()

        mock_run.assert_called_once_with(transport="stdio")

    def test_server_run_receives_stdio_when_daemon_unhealthy(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Daemon health check returns False → STDIO fallback."""
        monkeypatch.setenv("DEV10X_MCP_TRANSPORT", "auto")
        import dev10x.mcp.server_cli as cli_mod

        with (
            patch("dev10x.mcp.wiring.is_daemon_healthy", return_value=False),
            patch.object(cli_mod.server, "run") as mock_run,
        ):
            cli_mod.main()

        mock_run.assert_called_once_with(transport="stdio")

    def test_server_run_receives_streamable_http_when_daemon_healthy(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Healthy daemon → server.run(transport="streamable-http")."""
        monkeypatch.delenv("DEV10X_MCP_TRANSPORT", raising=False)
        import dev10x.mcp.server_cli as cli_mod

        with (
            patch("dev10x.mcp.wiring.is_daemon_healthy", return_value=True),
            patch.object(cli_mod.server, "run") as mock_run,
        ):
            cli_mod.main()

        mock_run.assert_called_once_with(transport="streamable-http")

    @pytest.mark.parametrize(
        "transport",
        ["stdio", "streamable-http", "sse"],
    )
    def test_explicit_transport_bypasses_health_check(
        self,
        monkeypatch: pytest.MonkeyPatch,
        transport: str,
    ) -> None:
        """Explicit DEV10X_MCP_TRANSPORT skips daemon health check entirely."""
        monkeypatch.setenv("DEV10X_MCP_TRANSPORT", transport)

        with patch("dev10x.mcp.daemon.is_daemon_healthy") as mock_health:
            result = select_transport_with_daemon_fallback()

        assert result == transport
        mock_health.assert_not_called()

    def test_fallback_is_called_only_once_per_invocation(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Health check is invoked exactly once per transport selection."""
        monkeypatch.delenv("DEV10X_MCP_TRANSPORT", raising=False)

        with patch("dev10x.mcp.wiring.is_daemon_healthy", return_value=False) as mock:
            select_transport_with_daemon_fallback()

        mock.assert_called_once_with()


# ---------------------------------------------------------------------------
# Gap 3: Deleted-CWD recovery in MCP context
# ---------------------------------------------------------------------------


class TestDeletedCwdRecoveryInMcpContext:
    """MCP tools must not hard-fail when the process CWD is a deleted directory.

    The recovery logic lives in subprocess_utils._recover_process_cwd() (GH-418).
    These tests verify the behaviour from the MCP perspective: that calling
    safe_effective_cwd() when os.getcwd() raises FileNotFoundError results in
    os.chdir() being called with the plugin root rather than propagating ENOENT.
    """

    def test_recover_process_cwd_calls_chdir_on_deleted_cwd(self) -> None:
        """When os.getcwd() raises FileNotFoundError, os.chdir(plugin_root) is called."""
        from dev10x.subprocess_utils import _recover_process_cwd, get_plugin_root

        with (
            patch("os.getcwd", side_effect=FileNotFoundError("No such file or directory")),
            patch("os.chdir") as mock_chdir,
        ):
            _recover_process_cwd()

        mock_chdir.assert_called_once_with(get_plugin_root())

    def test_recover_process_cwd_noop_when_cwd_exists(self) -> None:
        """_recover_process_cwd() does nothing when the process CWD is healthy."""
        from dev10x.subprocess_utils import _recover_process_cwd

        with (
            patch("os.getcwd", return_value="/some/valid/path"),
            patch("os.chdir") as mock_chdir,
        ):
            _recover_process_cwd()

        mock_chdir.assert_not_called()

    def test_safe_effective_cwd_triggers_recovery_when_cwd_deleted(self) -> None:
        """safe_effective_cwd() calls _recover_process_cwd() when process CWD is gone."""
        from dev10x.subprocess_utils import safe_effective_cwd

        with (
            patch("dev10x.subprocess_utils._recover_process_cwd") as mock_recover,
            patch("dev10x.subprocess_utils._effective_cwd") as mock_var,
        ):
            mock_var.get.return_value = None  # no bound worktree
            safe_effective_cwd()

        mock_recover.assert_called_once()

    def test_safe_effective_cwd_returns_none_on_deleted_bound_dir(
        self,
        tmp_path: Path,
    ) -> None:
        """Bound directory deleted → safe_effective_cwd() returns None, not raises."""
        from dev10x.subprocess_utils import safe_effective_cwd, use_cwd

        deleted = tmp_path / "deleted-worktree"
        deleted.mkdir()

        with use_cwd(str(deleted)):
            deleted.rmdir()  # delete while bound
            result = safe_effective_cwd()

        # Must return None (fall back to process CWD), not raise.
        assert result is None

    def test_mcp_daemon_lifecycle_unaffected_by_deleted_cwd(
        self,
        tmp_pid_dir: Path,
    ) -> None:
        """DaemonLifecycle.start() and stop() work even if process CWD is mocked deleted.

        DaemonLifecycle writes PID/socket files and starts the health thread;
        it does not call os.getcwd() directly, so it must be unaffected.
        """
        with patch("os.getcwd", side_effect=FileNotFoundError("deleted")):
            lifecycle = DaemonLifecycle(pid_dir=tmp_pid_dir)
            lifecycle.start()
            try:
                assert read_pid_file(tmp_pid_dir) == os.getpid()
            finally:
                lifecycle.stop()


# ---------------------------------------------------------------------------
# Gap 4: StreamableHTTP concurrent tool call simulation
# ---------------------------------------------------------------------------


class TestStreamableHttpConcurrentCalls:
    """Simulate concurrent tool calls against a StreamableHTTP session store.

    No real HTTP server is started. The tests verify that the SessionStore
    (the state layer that StreamableHTTP uses between requests) behaves
    correctly under concurrent load — the backpressure concern from the issue.

    The production code acquires a threading.Lock() per operation; these
    tests validate that concurrent get_or_create / update / evict calls
    do not corrupt state, which is the primary failure mode for concurrent
    StreamableHTTP tool calls.
    """

    def test_concurrent_sessions_created_independently(self) -> None:
        """N concurrent clients each create a distinct session without collision."""
        store = SessionStore(ttl=3600.0, max_sessions=100)
        session_ids = [f"client-{i}" for i in range(20)]
        errors: list[Exception] = []

        def create_session(sid: str) -> None:
            try:
                entry = store.get_or_create(session_id=sid)
                store.update(session_id=sid, last_seen=time.monotonic())
                assert entry.session_id == sid
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=create_session, args=(sid,)) for sid in session_ids]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        assert store.session_count() == len(session_ids)

    def test_concurrent_updates_to_same_session_are_lossless(self) -> None:
        """Multiple concurrent tool calls updating the same session do not lose writes."""
        store = SessionStore(ttl=3600.0, max_sessions=100)
        store.get_or_create(session_id="shared")
        errors: list[Exception] = []
        n_writers = 10
        writes_per_writer = 50

        def writer(writer_id: int) -> None:
            try:
                for i in range(writes_per_writer):
                    store.update(session_id="shared", **{f"w{writer_id}": i})
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(n_writers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        snap = store.snapshot(session_id="shared")
        # Each writer's last value is present (no key lost due to race).
        assert snap is not None
        assert len(snap) == n_writers

    def test_capacity_limit_under_concurrent_arrivals(self) -> None:
        """When max_sessions is hit under concurrent load, eviction is safe."""
        store = SessionStore(ttl=3600.0, max_sessions=5)
        errors: list[Exception] = []

        def arrive(sid: str) -> None:
            try:
                store.get_or_create(session_id=sid)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=arrive, args=(f"s{i}",)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        # After eviction the count is at most max_sessions.
        assert store.session_count() <= 5

    def test_evict_expired_safe_during_concurrent_updates(self) -> None:
        """Calling evict_expired() while writers are active does not raise."""
        store = SessionStore(ttl=0.01, max_sessions=100)  # very short TTL
        errors: list[Exception] = []

        def updater() -> None:
            try:
                for i in range(100):
                    store.update(session_id=f"s{i % 10}", value=i)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        def evictor() -> None:
            try:
                for _ in range(20):
                    store.evict_expired()
                    time.sleep(0.002)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=updater) for _ in range(3)]
        threads.append(threading.Thread(target=evictor))
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []


# ---------------------------------------------------------------------------
# Gap 5: Parametrized session TTL exhaustion
# ---------------------------------------------------------------------------


class TestSessionExpiryIntegration:
    """Parametrized TTL exhaustion tests across multiple session configurations.

    Complements the unit tests in test_session_store.py (which test individual
    methods in isolation). These tests verify the full lifecycle: create →
    idle → expire → evict, and that TTL config is respected consistently.
    """

    @pytest.mark.parametrize(
        "ttl_seconds",
        [0.05, 0.1, 0.2],
    )
    def test_session_expires_after_ttl(self, ttl_seconds: float) -> None:
        """Sessions created but not accessed expire after the configured TTL."""
        store = SessionStore(ttl=ttl_seconds, max_sessions=100)
        store.get_or_create(session_id="expiring")

        # Not yet expired — entry present.
        assert store.get(session_id="expiring") is not None

        # Backdate the last_active timestamp to simulate idleness.
        store._sessions["expiring"].last_active = time.monotonic() - (ttl_seconds + 0.5)

        evicted = store.evict_expired()
        assert evicted == 1
        assert store.get(session_id="expiring") is None

    @pytest.mark.parametrize(
        ("n_sessions", "ttl_seconds"),
        [
            (5, 0.05),
            (10, 0.1),
            (3, 0.2),
        ],
    )
    def test_bulk_session_expiry_clears_all_expired(
        self,
        n_sessions: int,
        ttl_seconds: float,
    ) -> None:
        """All idle sessions across multiple TTL configs are evicted in one pass."""
        store = SessionStore(ttl=ttl_seconds, max_sessions=n_sessions + 10)
        for i in range(n_sessions):
            store.get_or_create(session_id=f"s{i}")

        # Mark all as expired.
        for sid in store.session_ids():
            store._sessions[sid].last_active = time.monotonic() - (ttl_seconds + 1.0)

        evicted = store.evict_expired()
        assert evicted == n_sessions
        assert store.session_count() == 0

    @pytest.mark.parametrize(
        "ttl_seconds",
        [0.05, 0.1],
    )
    def test_active_sessions_survive_eviction_pass(self, ttl_seconds: float) -> None:
        """Recently-touched sessions are not evicted during a TTL purge pass."""
        store = SessionStore(ttl=ttl_seconds, max_sessions=100)
        store.get_or_create(session_id="active")
        store.get_or_create(session_id="idle")

        # Expire only "idle".
        store._sessions["idle"].last_active = time.monotonic() - (ttl_seconds + 1.0)

        evicted = store.evict_expired()
        assert evicted == 1
        assert store.get(session_id="active") is not None
        assert store.get(session_id="idle") is None

    def test_session_revived_after_eviction_on_next_access(self) -> None:
        """A re-used session ID after eviction creates a fresh entry."""
        store = SessionStore(ttl=0.05, max_sessions=100)
        first = store.get_or_create(session_id="revived")
        store._sessions["revived"].last_active = time.monotonic() - 10

        store.evict_expired()
        assert store.get(session_id="revived") is None

        # Re-access the same ID — must create a fresh entry (not raise).
        second = store.get_or_create(session_id="revived")
        assert second is not first
        assert store.session_count() == 1

    def test_evict_expired_auto_triggered_on_get_or_create(self) -> None:
        """get_or_create() runs evict_expired() before checking capacity.

        Verifies the internal auto-evict path: add a session, expire it, then
        create a new one — the expired entry is gone without an explicit evict call.
        """
        store = SessionStore(ttl=0.05, max_sessions=100)
        store.get_or_create(session_id="old")
        store._sessions["old"].last_active = time.monotonic() - 10

        # Creating a new session triggers internal eviction.
        store.get_or_create(session_id="new")

        assert "old" not in store.session_ids()
        assert "new" in store.session_ids()

    def test_daemon_lifecycle_stop_clears_all_active_sessions(
        self,
        tmp_pid_dir: Path,
    ) -> None:
        """Stopping the DaemonLifecycle purges sessions regardless of TTL remaining.

        Verifies bind_to_lifecycle() integration: active sessions with many
        seconds of TTL left are still cleared on daemon stop.
        """
        from dev10x.mcp.session_store import bind_to_lifecycle

        store = SessionStore(ttl=3600.0, max_sessions=100)
        for i in range(5):
            store.get_or_create(session_id=f"live-{i}")
        assert store.session_count() == 5

        lifecycle = DaemonLifecycle(pid_dir=tmp_pid_dir)
        bind_to_lifecycle(store=store, lifecycle=lifecycle)

        lifecycle.start()
        lifecycle.stop()

        # All sessions gone even though TTL is 3600 s.
        assert store.session_count() == 0


# ---------------------------------------------------------------------------
# Gap 6: Version-drift detection — DEFERRED
# ---------------------------------------------------------------------------

# NOTE(GH-563): Version-drift detection at SessionStart is listed as a gap in
# the audit but has no production implementation in any of the four MCP modules
# under test (daemon.py, transport.py, session_store.py, wiring.py).  The
# HealthServer only answers PING → PONG; no version payload is exchanged.
# SessionEntry.data is free-form; no version key is written by the server.
#
# Adding tests for behaviour that does not exist would either:
#   (a) test the absence of version checking (trivially true, adds no value), or
#   (b) test a hypothetical future API that would need to be co-designed with
#       the implementation (PR #422 referenced in the issue was not merged).
#
# Recommendation: implement version negotiation in daemon.py (e.g., embed the
# plugin version in the HealthServer PONG reply and add a client-side check in
# wiring.select_transport_with_daemon_fallback), then add tests here.
# Tracked as remaining work in GH-563.
