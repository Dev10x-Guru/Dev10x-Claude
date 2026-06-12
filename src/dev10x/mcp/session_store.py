"""Per-session state management for StreamableHTTP MCP servers (GH-337).

Maintains per-client state across HTTP requests when the MCP server
runs in ``streamable-http`` transport mode.  Each HTTP client is
identified by a session ID that the SDK assigns on first contact and
passes in the ``Mcp-Session-Id`` request header on subsequent requests.

Architecture
------------
``SessionStore`` is a thread-safe in-memory mapping from session ID
(``str``) to an arbitrary ``dict[str, object]`` payload.  It is
designed to be owned by :class:`~dev10x.mcp.daemon.DaemonLifecycle`
so all session data is cleared on daemon stop.

The module exposes a *process-level singleton* (``_store``) that
tool handlers can access via :func:`get_store`.  This pattern avoids
threading the store through every call chain while keeping the
store injectable for tests.

Forward-compatibility note
--------------------------
This module is Increment 2 of the M1 chain (#336 daemon → #337
session/state → #338 Claude Code wiring).  Increment 3 will wire the
session store into Claude Code configuration so tool handlers can
persist session-scoped preferences; that integration must not require
API changes to this module.

Session lifecycle
-----------------
* **Created** — on first :meth:`SessionStore.get_or_create` call for
  an unknown session ID.  The entry is populated with a ``created_at``
  timestamp.
* **Updated** — via :meth:`SessionStore.update`.  Each update refreshes
  the ``last_active`` timestamp, which the TTL eviction uses.
* **Evicted** — by :meth:`SessionStore.evict_expired` (call
  periodically or on every request).  Sessions idle for longer than the
  configured TTL are removed automatically.
* **Removed** — explicitly via :meth:`SessionStore.remove`, or in bulk
  via :meth:`SessionStore.clear` (called by ``DaemonLifecycle.stop``).

Environment variables
---------------------
DEV10X_MCP_SESSION_TTL
    Session idle timeout in seconds.  Sessions not accessed within this
    window are eligible for eviction.  Defaults to 3600 (1 hour).

DEV10X_MCP_SESSION_MAX
    Maximum number of concurrent sessions the store will hold.  When
    the limit is reached, the oldest (least-recently-active) session is
    evicted to make room.  Defaults to 1000.
"""

# FIXME(GH-501): forward-compat scaffolding. SessionStore is defined and
# unit-tested but not yet owned by a running daemon — Increment 3 (#338
# Claude Code wiring) is incomplete; only the client-side connect landed
# in #417. Kept intentionally per the GH-501 keep decision; wire into the
# daemon run loop or remove this module.

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------


def _session_ttl() -> float:
    """Return the session idle TTL in seconds (default 3600)."""
    raw = os.environ.get("DEV10X_MCP_SESSION_TTL", "").strip()
    try:
        return float(raw) if raw else 3600.0
    except ValueError:
        log.warning("Invalid DEV10X_MCP_SESSION_TTL=%r, using default 3600.0", raw)
        return 3600.0


def _session_max() -> int:
    """Return the maximum number of concurrent sessions (default 1000)."""
    raw = os.environ.get("DEV10X_MCP_SESSION_MAX", "").strip()
    try:
        return int(raw) if raw else 1000
    except ValueError:
        log.warning("Invalid DEV10X_MCP_SESSION_MAX=%r, using default 1000", raw)
        return 1000


# ---------------------------------------------------------------------------
# Session entry
# ---------------------------------------------------------------------------


class SessionEntry:
    """Single session record: data payload plus lifecycle timestamps.

    Attributes:
        session_id: The unique string identifier assigned by the SDK.
        data: Mutable dict of session-scoped state.  Tool handlers
            read and write arbitrary keys here.
        created_at: ``time.monotonic()`` value at creation time.
        last_active: ``time.monotonic()`` value at last access/update.
    """

    __slots__ = ("session_id", "data", "created_at", "last_active")

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.data: dict[str, Any] = {}
        now = time.monotonic()
        self.created_at = now
        self.last_active = now

    def touch(self) -> None:
        """Refresh the last-active timestamp to now."""
        self.last_active = time.monotonic()

    def is_expired(self, ttl: float) -> bool:
        """Return True when the session has been idle for longer than *ttl*."""
        return (time.monotonic() - self.last_active) > ttl


# ---------------------------------------------------------------------------
# SessionStore
# ---------------------------------------------------------------------------


class SessionStore:
    """Thread-safe per-session state container for StreamableHTTP servers.

    Create one instance and bind it to :class:`~dev10x.mcp.daemon.DaemonLifecycle`
    so it is cleared on daemon shutdown::

        from dev10x.mcp.daemon import DaemonLifecycle
        from dev10x.mcp.session_store import SessionStore

        store = SessionStore()

        lifecycle = DaemonLifecycle()
        lifecycle.start()
        try:
            server.run(transport="streamable-http")
        finally:
            store.clear()   # drop all session state
            lifecycle.stop()

    Alternatively, use :func:`bind_to_lifecycle` to wire the clear
    callback automatically:

        store = SessionStore()
        lifecycle = DaemonLifecycle()
        bind_to_lifecycle(store, lifecycle)

    Tool handlers retrieve per-session data via the process-level
    singleton::

        from dev10x.mcp.session_store import get_store

        @server.tool()
        async def my_tool(session_id: str | None = None) -> dict:
            store = get_store()
            if session_id:
                entry = store.get_or_create(session_id)
                entry.data["last_called"] = time.time()
            return {"ok": True}
    """

    def __init__(
        self,
        ttl: float | None = None,
        max_sessions: int | None = None,
    ) -> None:
        """Create a new store.

        Args:
            ttl: Session idle timeout in seconds.  Reads
                :envvar:`DEV10X_MCP_SESSION_TTL` when ``None``.
            max_sessions: Maximum concurrent sessions.  Reads
                :envvar:`DEV10X_MCP_SESSION_MAX` when ``None``.
        """
        self._ttl: float = ttl if ttl is not None else _session_ttl()
        self._max: int = max_sessions if max_sessions is not None else _session_max()
        self._lock = threading.Lock()
        self._sessions: dict[str, SessionEntry] = {}

    # ------------------------------------------------------------------
    # Core access
    # ------------------------------------------------------------------

    def get_or_create(self, session_id: str) -> SessionEntry:
        """Return the existing session or create a fresh one.

        Evicts expired sessions before checking capacity, then enforces
        the ``max_sessions`` limit by dropping the least-recently-active
        entry when the store is full.

        Args:
            session_id: The unique session identifier from the SDK.

        Returns:
            The :class:`SessionEntry` for this session ID.
        """
        with self._lock:
            return self._get_or_create_locked(session_id)

    def get(self, session_id: str) -> SessionEntry | None:
        """Return the session entry or ``None`` if it does not exist.

        Touches the entry's ``last_active`` timestamp on a hit.
        Does *not* create a new session.

        Args:
            session_id: The unique session identifier.
        """
        with self._lock:
            entry = self._sessions.get(session_id)
            if entry is not None:
                entry.touch()
            return entry

    def update(self, session_id: str, **kwargs: Any) -> SessionEntry:
        """Merge *kwargs* into the session's data dict.

        Creates the session when it does not yet exist.

        Args:
            session_id: The unique session identifier.
            **kwargs: Key-value pairs to merge into ``entry.data``.

        Returns:
            The updated :class:`SessionEntry`.
        """
        with self._lock:
            entry = self._get_or_create_locked(session_id)
            entry.data.update(kwargs)
            entry.touch()
            return entry

    def remove(self, session_id: str) -> bool:
        """Delete the session, returning True when it existed.

        Args:
            session_id: The unique session identifier.
        """
        with self._lock:
            existed = session_id in self._sessions
            self._sessions.pop(session_id, None)
            if existed:
                log.debug("SessionStore: removed session %r", session_id)
            return existed

    # ------------------------------------------------------------------
    # Bulk / lifecycle operations
    # ------------------------------------------------------------------

    def clear(self) -> int:
        """Remove all sessions.  Returns the number of sessions cleared.

        Called by :func:`bind_to_lifecycle` on daemon stop.
        """
        with self._lock:
            count = len(self._sessions)
            self._sessions.clear()
            log.info("SessionStore: cleared %d session(s)", count)
            return count

    def evict_expired(self) -> int:
        """Remove sessions idle longer than the TTL.

        Returns the number of sessions evicted.  Call periodically
        (e.g., on every MCP request) to prevent unbounded memory growth.
        """
        with self._lock:
            return self._evict_expired_locked()

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def session_count(self) -> int:
        """Return the current number of active sessions."""
        with self._lock:
            return len(self._sessions)

    def session_ids(self) -> list[str]:
        """Return a snapshot of all current session IDs."""
        with self._lock:
            return list(self._sessions.keys())

    def snapshot(self, session_id: str) -> dict[str, Any] | None:
        """Return a shallow copy of the session data, or ``None`` if absent.

        Suitable for serialisation and logging without exposing the live
        entry to external mutation.

        Args:
            session_id: The unique session identifier.
        """
        with self._lock:
            entry = self._sessions.get(session_id)
            if entry is None:
                return None
            return dict(entry.data)

    # ------------------------------------------------------------------
    # Private helpers (caller must hold _lock)
    # ------------------------------------------------------------------

    def _get_or_create_locked(self, session_id: str) -> SessionEntry:
        """Return or create the entry. Caller MUST hold ``_lock``.

        Extracted so :meth:`update` can run get-or-create and the data
        mutation inside a single critical section (GH-558). Splitting
        them across two lock acquisitions left a TOCTOU window where a
        concurrent ``remove`` or capacity eviction could drop the entry
        between the read and the write, silently losing the update.
        """
        self._evict_expired_locked()
        if session_id in self._sessions:
            entry = self._sessions[session_id]
            entry.touch()
            return entry

        # Enforce capacity limit: evict the oldest entry.
        if len(self._sessions) >= self._max:
            self._evict_oldest_locked()

        entry = SessionEntry(session_id=session_id)
        self._sessions[session_id] = entry
        log.debug("SessionStore: created session %r", session_id)
        return entry

    def _evict_expired_locked(self) -> int:
        expired = [sid for sid, e in self._sessions.items() if e.is_expired(self._ttl)]
        for sid in expired:
            del self._sessions[sid]
            log.debug("SessionStore: evicted expired session %r", sid)
        return len(expired)

    def _evict_oldest_locked(self) -> None:
        if not self._sessions:
            return
        oldest_id = min(self._sessions, key=lambda sid: self._sessions[sid].last_active)
        del self._sessions[oldest_id]
        log.warning(
            "SessionStore: evicted oldest session %r (capacity limit %d reached)",
            oldest_id,
            self._max,
        )


# ---------------------------------------------------------------------------
# Process-level singleton
# ---------------------------------------------------------------------------

#: Module-level singleton, used by tool handlers when no explicit store is
#: injected.  Tests override it via :func:`set_store`.
_store: SessionStore = SessionStore()


def get_store() -> SessionStore:
    """Return the process-level :class:`SessionStore` singleton.

    Tool handlers call this to access per-session state without needing
    the store passed through the entire call chain::

        from dev10x.mcp.session_store import get_store

        entry = get_store().get_or_create(session_id)
    """
    return _store


def set_store(store: SessionStore) -> None:
    """Replace the process-level singleton.

    Intended for testing — inject a fresh store with custom TTL/max
    settings and restore it on teardown::

        def test_something(monkeypatch):
            fresh = SessionStore(ttl=60, max_sessions=10)
            monkeypatch.setattr("dev10x.mcp.session_store._store", fresh)
            ...
    """
    global _store
    _store = store


# ---------------------------------------------------------------------------
# DaemonLifecycle integration
# ---------------------------------------------------------------------------


def bind_to_lifecycle(
    store: SessionStore,
    lifecycle: object,
) -> None:
    """Register *store*.clear() as a teardown hook on *lifecycle*.

    The ``lifecycle`` object is duck-typed: it must expose a ``stop``
    method.  :class:`~dev10x.mcp.daemon.DaemonLifecycle` satisfies
    this contract.  The original ``stop`` method is wrapped so session
    state is always cleared when the daemon stops, regardless of
    whether the caller remembers to call ``store.clear()`` explicitly.

    Args:
        store: The :class:`SessionStore` to register.
        lifecycle: An object with a callable ``stop`` attribute.

    Raises:
        AttributeError: If *lifecycle* does not have a ``stop`` method.

    Example::

        from dev10x.mcp.daemon import DaemonLifecycle
        from dev10x.mcp.session_store import SessionStore, bind_to_lifecycle

        store = SessionStore()
        lifecycle = DaemonLifecycle()
        bind_to_lifecycle(store, lifecycle)

        with lifecycle:
            server.run(transport="streamable-http")
        # store.clear() was called automatically by lifecycle.stop()
    """
    original_stop = lifecycle.stop  # type: ignore[attr-defined]

    def _stop_with_clear(*args: object, **kwargs: object) -> None:
        store.clear()
        original_stop(*args, **kwargs)

    lifecycle.stop = _stop_with_clear  # type: ignore[attr-defined]
    log.debug("SessionStore bound to lifecycle %r", lifecycle)
