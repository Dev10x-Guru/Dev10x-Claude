"""Daemon lifecycle management for the Dev10x MCP server (GH-336).

Provides health checking, graceful shutdown, PID/socket file management,
and restart-safety primitives for running the MCP server as a long-lived
daemon process.

Forward-compatibility note
--------------------------
This module is Increment 1 of the M1 chain (#336 → #337 session/state
→ #338 Claude Code wiring).  The public surface is intentionally
minimal — just enough to support health, shutdown, and PID/socket
coordination.  Session-state persistence (#337) and Claude Code
configuration wiring (#338) will extend *this* module's primitives;
they must not require API changes to what is already here.

Environment variables
---------------------
DEV10X_MCP_PID_DIR
    Directory where the ``.pid`` and ``.sock`` files are created.
    Defaults to ``~/.local/share/dev10x/mcp`` (XDG-style).

DEV10X_MCP_HEALTH_TIMEOUT
    Seconds to wait for a single health-check ping to the daemon
    socket before declaring it unresponsive.  Defaults to 3.

DEV10X_MCP_SHUTDOWN_TIMEOUT
    Seconds to wait for the daemon to exit after SIGTERM before
    escalating to SIGKILL.  Defaults to 10.
"""

from __future__ import annotations

import logging
import os
import signal
import socket
import time
from pathlib import Path

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------

_DEFAULT_PID_DIR = Path.home() / ".local" / "share" / "dev10x" / "mcp"
_HEALTH_MAGIC = b"PING"
_HEALTH_REPLY = b"PONG"
_SOCKET_NAME = "dev10x-mcp.sock"
_PID_NAME = "dev10x-mcp.pid"


def _pid_dir() -> Path:
    """Return the directory used for PID and socket files.

    Reads ``DEV10X_MCP_PID_DIR``; falls back to
    ``~/.local/share/dev10x/mcp``.
    """
    raw = os.environ.get("DEV10X_MCP_PID_DIR", "").strip()
    return Path(raw) if raw else _DEFAULT_PID_DIR


def _health_timeout() -> float:
    """Return the health-check socket timeout in seconds."""
    raw = os.environ.get("DEV10X_MCP_HEALTH_TIMEOUT", "").strip()
    try:
        return float(raw) if raw else 3.0
    except ValueError:
        log.warning("Invalid DEV10X_MCP_HEALTH_TIMEOUT=%r, using default 3.0", raw)
        return 3.0


def _shutdown_timeout() -> float:
    """Return the graceful-shutdown wait timeout in seconds."""
    raw = os.environ.get("DEV10X_MCP_SHUTDOWN_TIMEOUT", "").strip()
    try:
        return float(raw) if raw else 10.0
    except ValueError:
        log.warning("Invalid DEV10X_MCP_SHUTDOWN_TIMEOUT=%r, using default 10.0", raw)
        return 10.0


# ---------------------------------------------------------------------------
# PID file helpers
# ---------------------------------------------------------------------------


def pid_file_path(pid_dir: Path | None = None) -> Path:
    """Return the canonical path for the daemon PID file."""
    return (pid_dir or _pid_dir()) / _PID_NAME


def socket_file_path(pid_dir: Path | None = None) -> Path:
    """Return the canonical path for the daemon health-check socket."""
    return (pid_dir or _pid_dir()) / _SOCKET_NAME


def write_pid_file(pid: int | None = None, pid_dir: Path | None = None) -> Path:
    """Write *pid* (default: ``os.getpid()``) to the PID file.

    Creates the directory if it does not exist.  Returns the path written.

    Raises:
        OSError: If the file cannot be written.
    """
    target = pid_file_path(pid_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(str(pid if pid is not None else os.getpid()))
    log.debug("Wrote PID file: %s", target)
    return target


def read_pid_file(pid_dir: Path | None = None) -> int | None:
    """Read the daemon PID from the PID file.

    Returns the PID as an integer, or ``None`` if the file does not
    exist or contains invalid content.
    """
    path = pid_file_path(pid_dir)
    try:
        text = path.read_text().strip()
        return int(text)
    except FileNotFoundError:
        return None
    except (ValueError, OSError) as exc:
        log.warning("Cannot read PID file %s: %s", path, exc)
        return None


def remove_pid_file(pid_dir: Path | None = None) -> None:
    """Delete the PID file, ignoring errors if already absent."""
    path = pid_file_path(pid_dir)
    try:
        path.unlink()
        log.debug("Removed PID file: %s", path)
    except FileNotFoundError:
        pass


def remove_socket_file(pid_dir: Path | None = None) -> None:
    """Delete the health-check socket file, ignoring errors if already absent."""
    path = socket_file_path(pid_dir)
    try:
        path.unlink()
        log.debug("Removed socket file: %s", path)
    except FileNotFoundError:
        pass


# ---------------------------------------------------------------------------
# Stale-lock detection
# ---------------------------------------------------------------------------


def is_pid_alive(pid: int) -> bool:
    """Return True if *pid* refers to a running process on this host.

    Uses ``os.kill(pid, 0)`` which sends no signal but raises
    ``ProcessLookupError`` when the process does not exist and
    ``PermissionError`` when it exists but is owned by another user.
    Both positive cases (own process or other user's process) mean the
    PID is alive.
    """
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we do not own it — still alive.
        return True


def is_stale_pid_file(pid_dir: Path | None = None) -> bool:
    """Return True when a PID file exists but the process is no longer running.

    A missing PID file is *not* stale — it simply means no daemon has
    ever written one, or it was cleanly removed.
    """
    pid = read_pid_file(pid_dir)
    if pid is None:
        return False
    return not is_pid_alive(pid)


def clear_stale_lock_files(pid_dir: Path | None = None) -> bool:
    """Remove stale PID and socket files when the owning process is dead.

    Returns True if stale files were removed, False if the daemon is
    still running or no lock files were present.

    This is the **restart-safety** primitive: call it before attempting
    to start a new daemon instance to avoid false "already running"
    errors.
    """
    if is_stale_pid_file(pid_dir):
        log.info("Removing stale lock files from previous daemon run.")
        remove_pid_file(pid_dir)
        remove_socket_file(pid_dir)
        return True
    return False


# ---------------------------------------------------------------------------
# Health-check socket server (runs inside the daemon)
# ---------------------------------------------------------------------------


class HealthServer:
    """Minimal UNIX-domain socket server that answers PING → PONG.

    Intended to run in a background thread inside the daemon process.
    The socket is bound at :func:`socket_file_path` and removed on
    :meth:`close`.

    Usage::

        server = HealthServer()
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        # … daemon runs …
        server.close()
    """

    def __init__(self, pid_dir: Path | None = None) -> None:
        self._path = socket_file_path(pid_dir)
        self._running = False
        self._sock: socket.socket | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Bind the UNIX socket and mark the server ready to serve."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # Remove any leftover socket file from a previous crash.
        try:
            self._path.unlink()
        except FileNotFoundError:
            pass
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(1.0)  # short accept() timeout for clean shutdown
        sock.bind(str(self._path))
        sock.listen(5)
        self._sock = sock
        self._running = True
        log.debug("HealthServer listening on %s", self._path)

    def serve_forever(self) -> None:
        """Accept connections and respond to PING with PONG.

        Returns when :meth:`close` is called.  Intended to run in a
        daemon thread so it does not block process exit.
        """
        if self._sock is None:
            self.start()
        assert self._sock is not None
        while self._running:
            try:
                conn, _ = self._sock.accept()
            except TimeoutError:
                continue
            except OSError:
                if self._running:
                    log.warning("HealthServer accept() failed", exc_info=True)
                break
            try:
                data = conn.recv(len(_HEALTH_MAGIC))
                if data == _HEALTH_MAGIC:
                    conn.sendall(_HEALTH_REPLY)
            except OSError:
                log.debug("HealthServer: error on connection", exc_info=True)
            finally:
                conn.close()

    def close(self) -> None:
        """Stop the server and remove the socket file."""
        self._running = False
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        remove_socket_file(Path(self._path).parent)
        log.debug("HealthServer stopped")


# ---------------------------------------------------------------------------
# Health-check client (runs in the caller / watcher process)
# ---------------------------------------------------------------------------


def ping_daemon(pid_dir: Path | None = None, timeout: float | None = None) -> bool:
    """Return True if the daemon's health-check socket responds to PING.

    Connects to the UNIX socket at :func:`socket_file_path`, sends
    ``PING``, and checks for ``PONG``.  Returns False on any error or
    timeout.

    Args:
        pid_dir: Override the directory containing the socket file.
        timeout: Override :envvar:`DEV10X_MCP_HEALTH_TIMEOUT`.
    """
    path = socket_file_path(pid_dir)
    t = timeout if timeout is not None else _health_timeout()
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(t)
            s.connect(str(path))
            s.sendall(_HEALTH_MAGIC)
            reply = s.recv(len(_HEALTH_REPLY))
            return reply == _HEALTH_REPLY
    except OSError:
        return False


def is_daemon_healthy(pid_dir: Path | None = None) -> bool:
    """High-level health check: PID alive *and* socket responds.

    Returns True only when both conditions hold — the process listed
    in the PID file is running **and** its health socket answers PING.
    Either condition failing (process dead, socket timeout, missing
    files) returns False.
    """
    pid = read_pid_file(pid_dir)
    if pid is None:
        return False
    if not is_pid_alive(pid):
        return False
    return ping_daemon(pid_dir)


# ---------------------------------------------------------------------------
# Graceful shutdown
# ---------------------------------------------------------------------------


def request_shutdown(
    pid: int | None = None,
    pid_dir: Path | None = None,
) -> bool:
    """Send SIGTERM to the daemon and return True if the signal was delivered.

    Args:
        pid: Explicit PID to signal.  Reads the PID file when ``None``.
        pid_dir: Override the PID-file directory.

    Returns:
        True when the signal was sent successfully; False when the PID
        could not be determined or the process no longer exists.
    """
    target_pid = pid if pid is not None else read_pid_file(pid_dir)
    if target_pid is None:
        log.warning("request_shutdown: no PID file found")
        return False
    try:
        os.kill(target_pid, signal.SIGTERM)
        log.info("Sent SIGTERM to daemon PID %d", target_pid)
        return True
    except ProcessLookupError:
        log.warning("request_shutdown: PID %d not found (already exited?)", target_pid)
        return False


def wait_for_shutdown(
    pid: int,
    timeout: float | None = None,
    poll_interval: float = 0.25,
) -> bool:
    """Wait for *pid* to exit within *timeout* seconds.

    Polls :func:`is_pid_alive` every *poll_interval* seconds.  Returns
    True when the process exits before the timeout, False otherwise.

    Args:
        pid: The PID to watch.
        timeout: Maximum seconds to wait.  Reads
            :envvar:`DEV10X_MCP_SHUTDOWN_TIMEOUT` when ``None``.
        poll_interval: Seconds between liveness checks.
    """
    deadline = time.monotonic() + (timeout if timeout is not None else _shutdown_timeout())
    while time.monotonic() < deadline:
        if not is_pid_alive(pid):
            log.info("Daemon PID %d exited", pid)
            return True
        time.sleep(poll_interval)
    return False


def shutdown_daemon(
    pid_dir: Path | None = None,
    *,
    timeout: float | None = None,
    force: bool = True,
) -> bool:
    """Gracefully stop the daemon, escalating to SIGKILL if needed.

    Steps:

    1. Read the PID from the PID file.
    2. Send SIGTERM.
    3. Wait up to *timeout* seconds for the process to exit.
    4. If still alive and *force* is True, send SIGKILL.

    Returns True when the daemon exited cleanly (SIGTERM was enough);
    False when SIGKILL was required or the daemon was not running.

    Raises:
        RuntimeError: If *force* is False and the daemon does not exit
            in time.
    """
    pid = read_pid_file(pid_dir)
    if pid is None:
        log.info("shutdown_daemon: no PID file — nothing to stop")
        return False

    if not is_pid_alive(pid):
        log.info("shutdown_daemon: PID %d already exited", pid)
        remove_pid_file(pid_dir)
        remove_socket_file(pid_dir)
        return True

    request_shutdown(pid=pid)
    if wait_for_shutdown(pid, timeout=timeout):
        remove_pid_file(pid_dir)
        remove_socket_file(pid_dir)
        return True

    if not force:
        raise RuntimeError(
            f"Daemon PID {pid} did not exit within the timeout. Use force=True to send SIGKILL."
        )

    log.warning("Daemon PID %d did not exit in time; sending SIGKILL", pid)
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass  # Raced with clean exit — that is fine.

    remove_pid_file(pid_dir)
    remove_socket_file(pid_dir)
    return False


# ---------------------------------------------------------------------------
# Daemon-side lifecycle context
# ---------------------------------------------------------------------------


class DaemonLifecycle:
    """Convenience wrapper that ties PID, socket, and shutdown together.

    Typical usage inside the daemon process::

        lifecycle = DaemonLifecycle()
        lifecycle.start()

        # Run the MCP server (blocking call).
        try:
            server.run(transport="streamable-http")
        finally:
            lifecycle.stop()

    The :meth:`start` method:

    * Clears any stale lock files.
    * Writes the current PID to the PID file.
    * Starts the :class:`HealthServer` in a daemon background thread.

    The :meth:`stop` method:

    * Closes the health server.
    * Removes the PID and socket files.
    """

    def __init__(self, pid_dir: Path | None = None) -> None:
        self._pid_dir = pid_dir
        self._health_server: HealthServer | None = None
        self._health_thread: object | None = None  # threading.Thread

    def start(self) -> None:
        """Initialise daemon lifecycle state and start the health server."""
        import threading

        clear_stale_lock_files(self._pid_dir)
        write_pid_file(pid_dir=self._pid_dir)

        server = HealthServer(self._pid_dir)
        server.start()
        self._health_server = server

        thread = threading.Thread(
            target=server.serve_forever,
            daemon=True,
            name="dev10x-health",
        )
        thread.start()
        self._health_thread = thread
        log.info("DaemonLifecycle started (PID=%d)", os.getpid())

    def stop(self) -> None:
        """Tear down health server and remove lock files."""
        if self._health_server is not None:
            self._health_server.close()
            self._health_server = None
        remove_pid_file(self._pid_dir)
        log.info("DaemonLifecycle stopped")

    def __enter__(self) -> DaemonLifecycle:
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop()
