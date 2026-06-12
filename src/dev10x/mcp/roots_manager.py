"""MCP client-roots awareness for Dev10x (GH-344).

Fetches the client-declared directory roots via ``roots/list`` and
listens for ``notifications/roots/list_changed`` so the cached set
stays fresh.  The roots scope CWD/worktree operations: when the client
declares roots, callers can validate that an effective CWD is under one
of those roots, complementing the existing GH-979 effective-CWD
discipline and permission hooks.

Architecture
------------
``ClientRootsManager`` is a lightweight stateful object that holds the
current root set.  It is created once per server lifespan in ``_app.py``
and wired to the low-level MCP server the same way
``KnowledgeResourceWatcher`` is: an ``InitializedNotification`` handler
calls :meth:`set_session` so the manager can issue its first
``roots/list`` request as soon as the handshake completes.

Subsequent ``RootsListChangedNotification`` events trigger a refresh call
automatically.

``ClientRootsManager`` exposes a synchronous :attr:`roots` property that
callers can read at any time.  The value is ``None`` before the first
successful fetch and an empty list ``[]`` when the client declares no
roots.

Environment variables
---------------------
DEV10X_ROOTS_ENABLED
    Set to ``0`` to disable roots integration entirely.  Defaults to
    ``1`` (enabled).  Useful in tests or environments where the client
    does not implement the roots capability.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dev10x.domain.common.result import Result, ok

if TYPE_CHECKING:  # pragma: no cover
    from mcp.server.session import ServerSession

log = logging.getLogger(__name__)


def _roots_enabled() -> bool:
    """Return True when roots integration is enabled.

    Reads ``DEV10X_ROOTS_ENABLED``; defaults to ``True``.
    Set to ``0`` to disable.
    """
    raw = os.environ.get("DEV10X_ROOTS_ENABLED", "").strip()
    return raw not in ("0", "false", "no")


# ── Root value object ──────────────────────────────────────────────


class ClientRoot:
    """A single client-declared root directory.

    Args:
        uri: The ``file://`` URI declared by the client.
        name: Human-readable label (may be ``None``).
    """

    def __init__(self, uri: str, name: str | None = None) -> None:
        self.uri = uri
        self.name = name
        if uri.startswith("file://"):
            self._path: Path | None = Path(uri[7:]).resolve()
        else:
            self._path = None

    @property
    def path(self) -> Path | None:
        """Resolved filesystem path, or ``None`` for non-file URIs."""
        return self._path

    def contains(self, candidate: str | Path) -> bool:
        """Return ``True`` when *candidate* is inside this root.

        Args:
            candidate: Filesystem path to test.
        """
        if self._path is None:
            return False
        try:
            Path(candidate).resolve().relative_to(self._path)
            return True
        except ValueError:
            return False

    def to_dict(self) -> dict[str, str | None]:
        return {"uri": self.uri, "name": self.name}

    def __repr__(self) -> str:
        return f"ClientRoot(uri={self.uri!r}, name={self.name!r})"


# ── Manager ────────────────────────────────────────────────────────


class ClientRootsManager:
    """Fetch and cache the set of client-declared MCP roots (GH-344).

    Lifecycle::

        manager = ClientRootsManager()
        wire_roots_to_server(server=app._mcp_server, manager=manager)
        # (set_session called automatically on InitializedNotification)
        # tools may read manager.roots at any time

    Args:
        enabled: When ``False``, skip all network calls (useful in tests).
            ``None`` (default) reads ``DEV10X_ROOTS_ENABLED``.
    """

    def __init__(self, enabled: bool | None = None) -> None:
        self._enabled: bool = enabled if enabled is not None else _roots_enabled()
        self._session: ServerSession | None = None
        self._roots: list[ClientRoot] | None = None

    @property
    def roots(self) -> list[ClientRoot] | None:
        """Current root set, or ``None`` if not yet fetched.

        An empty list means the client declared roots capability but no
        roots.  ``None`` means no successful fetch has completed yet.
        """
        return self._roots

    @property
    def enabled(self) -> bool:
        """Return whether roots integration is enabled."""
        return self._enabled

    def is_within_roots(self, cwd: str | Path) -> bool:
        """Return ``True`` when *cwd* is inside at least one declared root.

        When no roots are declared (``self.roots`` is ``None`` or empty),
        every CWD is considered valid (no restriction applies).

        Args:
            cwd: Filesystem path to validate.
        """
        roots = self._roots
        if not roots:
            return True
        return any(r.contains(candidate=cwd) for r in roots)

    def set_session(self, session: ServerSession | None) -> None:
        """Attach (or detach) the active MCP session.

        Called by the ``InitializedNotification`` handler.  When *session*
        is ``None`` the cached roots are cleared.

        Args:
            session: Active ``ServerSession``, or ``None`` to detach.
        """
        self._session = session
        if session is not None:
            log.debug("ClientRootsManager: session attached")
        else:
            log.debug("ClientRootsManager: session detached")
            self._roots = None

    async def refresh(self) -> None:
        """Fetch the current roots from the client via ``roots/list``.

        No-op when disabled or when no session is attached.  Logs and
        suppresses all exceptions so that a non-roots-capable client does
        not break server startup.
        """
        if not self._enabled:
            log.debug("ClientRootsManager: disabled — skipping roots/list")
            return
        session = self._session
        if session is None:
            log.debug("ClientRootsManager: no session — skipping roots/list")
            return
        try:
            result = await session.list_roots()
            if self._session is not session:
                # GH-562: a concurrent set_session() detached or swapped
                # the session at the await yield point. The roots we just
                # fetched belong to a session that is no longer active —
                # discard them rather than overwrite _roots with a ghost set.
                log.debug(
                    "ClientRootsManager: session changed during roots/list — discarding result"
                )
                return
            self._roots = [
                ClientRoot(uri=str(r.uri), name=getattr(r, "name", None)) for r in result.roots
            ]
            log.debug(
                "ClientRootsManager: fetched %d root(s): %s",
                len(self._roots),
                [r.uri for r in self._roots],
            )
        except Exception:
            log.debug(
                "ClientRootsManager: roots/list failed (client may not support roots capability)",
                exc_info=True,
            )


# ── module-level registry ──────────────────────────────────────────

_manager: ClientRootsManager | None = None

# GH-498: the event loop holds only weak references to bare
# ``create_task`` results, so a fire-and-forget refresh can be garbage
# collected mid-flight and silently leave the roots cache stale. Retain
# a strong reference until the task finishes (mirrors the lifespan-local
# retention in ``_app.py``).
_background_tasks: set[asyncio.Task[None]] = set()


def get_manager() -> ClientRootsManager | None:
    """Return the currently registered :class:`ClientRootsManager`, or ``None``."""
    return _manager


def list_roots() -> Result[dict[str, Any]]:
    """Return the client-declared roots payload (GH-344, GH-502).

    Backing domain function for the ``list_client_roots`` MCP tool. Returns
    a :class:`~dev10x.domain.common.result.Result` so the handler can unwrap
    it via ``.to_dict()`` like every other tool at the MCP boundary
    (ADR-0009). There is no error path today — the payload is always a
    success — but the two-layer shape keeps the tool consistent and leaves
    room for a future failure mode without changing the wire contract.

    The ``roots`` value is ``None`` when no session has been established
    yet, an empty list when the client declares no roots, and a list of
    ``{"uri", "name"}`` dicts otherwise. ``enabled`` reflects
    ``DEV10X_ROOTS_ENABLED``.
    """
    manager = get_manager()
    if manager is None:
        return ok({"roots": None, "enabled": False})
    roots = manager.roots
    return ok(
        {
            "roots": [r.to_dict() for r in roots] if roots is not None else None,
            "enabled": manager.enabled,
        }
    )


def wire_roots_to_server(
    server: object,
    manager: ClientRootsManager,
) -> None:
    """Register *manager* with the MCP low-level *server*'s handlers.

    Installs:

    * An ``InitializedNotification`` handler — wires the session and
      triggers the first ``roots/list`` fetch.  When the resource watcher
      already registered an ``InitializedNotification`` handler, the two
      are chained so both fire in sequence.
    * A ``RootsListChangedNotification`` handler — refreshes the cached
      roots whenever the client signals a change.

    Args:
        server: The low-level MCP ``Server`` instance
            (e.g. ``fastmcp_instance._mcp_server``).
        manager: The roots manager to attach.
    """

    import mcp.types as mcp_types

    global _manager
    _manager = manager

    async def _on_initialized(notification: mcp_types.InitializedNotification) -> None:
        try:
            session = server.request_context.session  # type: ignore[attr-defined]
            manager.set_session(session=session)
            await manager.refresh()
        except Exception:
            log.debug(
                "ClientRootsManager: could not wire session on initialized",
                exc_info=True,
            )

    async def _on_roots_changed(
        notification: mcp_types.RootsListChangedNotification,
    ) -> None:
        log.debug("ClientRootsManager: roots/list_changed received — refreshing")
        task = asyncio.create_task(manager.refresh(), name="dev10x-roots-refresh")
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)

    # Chain with the existing InitializedNotification handler (GH-341 resource
    # watcher registers one first).
    existing_init = server.notification_handlers.get(  # type: ignore[attr-defined]
        mcp_types.InitializedNotification
    )

    if existing_init is not None:

        async def _chained_init(notification: mcp_types.InitializedNotification) -> None:
            await existing_init(notification)
            await _on_initialized(notification)

        server.notification_handlers[mcp_types.InitializedNotification] = _chained_init  # type: ignore[attr-defined]
    else:
        server.notification_handlers[mcp_types.InitializedNotification] = _on_initialized  # type: ignore[attr-defined]

    server.notification_handlers[mcp_types.RootsListChangedNotification] = _on_roots_changed  # type: ignore[attr-defined]

    log.debug(
        "ClientRootsManager: handlers registered "
        "(InitializedNotification chained=%s, RootsListChangedNotification)",
        existing_init is not None,
    )
