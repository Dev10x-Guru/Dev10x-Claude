"""MCP resource update notifications for Dev10x knowledge resources (GH-341).

Watches the on-disk files that back the knowledge resources registered in
``knowledge_resources.py`` and emits ``notifications/resources/list_changed``
(when a file is added or removed) or ``notifications/resources/updated``
(when an existing file's content changes) to connected MCP clients.

Architecture
------------
``KnowledgeResourceWatcher`` polls file modification-times on a configurable
interval (default 5 s).  Polling avoids the need for ``watchfiles`` or OS
inotify libraries — no extra dependencies are required.

Session wiring
--------------
MCP resource notifications must be sent through an active ``ServerSession``.
The watcher receives a session reference via :meth:`set_session`, which is
called by the ``InitializedNotification`` handler registered on the low-level
server in :func:`wire_watcher_to_server`.

Calling :meth:`set_session` with ``None`` (the default) disables notification
dispatch so that the same watcher instance can be used in unit tests without
needing a live server connection.

Watched paths
-------------
The watcher tracks four roots that correspond to the five resource handlers
in ``knowledge_resources.py``:

* ``skills/*/references/playbook.yaml``  →  ``dev10x://skills/{name}/playbook``
* ``.claude/rules/*.md``                 →  ``dev10x://rules/{name}``
* ``references/*.md``                    →  ``dev10x://references/{name}``
* ``SKILLS.md``                          →  ``dev10x://skills/index``

Changes to these files trigger ``resources/updated``; a file appearing or
disappearing triggers ``resources/list_changed`` (because the set of
enumerable template results changes).

Environment variables
---------------------
DEV10X_RESOURCE_WATCH_INTERVAL
    Poll interval in seconds.  Defaults to 5.  Set to 0 to disable polling
    entirely (e.g. in integration tests).
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from dev10x.domain.common.singleton_holder import SingletonHolder

if TYPE_CHECKING:  # pragma: no cover
    from mcp.server.session import ServerSession

log = logging.getLogger(__name__)


def _poll_interval() -> float:
    """Return the file-watch poll interval in seconds.

    Reads ``DEV10X_RESOURCE_WATCH_INTERVAL``; defaults to 5.0.
    A value of 0 disables polling entirely.
    """
    raw = os.environ.get("DEV10X_RESOURCE_WATCH_INTERVAL", "").strip()
    try:
        return float(raw) if raw else 5.0
    except ValueError:
        log.warning(
            "Invalid DEV10X_RESOURCE_WATCH_INTERVAL=%r, using default 5.0",
            raw,
        )
        return 5.0


# ── per-file snapshot ──────────────────────────────────────────────


@dataclass
class _FileState:
    """Last-seen mtime and existence state for one watched path."""

    exists: bool
    mtime: float


# ── change events ──────────────────────────────────────────────────


@dataclass
class ResourceChanged:
    """A single resource change event.

    Attributes:
        uri: The ``dev10x://`` URI of the changed resource.
        list_changed: True when the *list* of resources changed (file added
            or removed).  False when only the content of an existing file
            changed.
    """

    uri: str
    list_changed: bool = False


# ── watcher ───────────────────────────────────────────────────────


class KnowledgeResourceWatcher:
    """Poll Dev10x knowledge files and emit MCP resource notifications.

    Typical lifecycle::

        watcher = KnowledgeResourceWatcher(plugin_root=get_plugin_root())
        # (wire_watcher_to_server will call watcher.set_session(...) when the
        # MCP client sends its InitializedNotification)
        await watcher.run()  # blocks until cancelled

    The watcher is safe to create before the MCP session is established;
    file scanning still runs and changes are accumulated, but notifications
    are only sent after :meth:`set_session` is called.

    Args:
        plugin_root: Root of the Dev10x plugin tree.  All watched paths are
            relative to this directory.
        poll_interval: Seconds between scans.  ``None`` uses the value of
            ``DEV10X_RESOURCE_WATCH_INTERVAL``.
    """

    def __init__(
        self,
        plugin_root: Path,
        poll_interval: float | None = None,
    ) -> None:
        self._root = plugin_root
        self._interval: float = poll_interval if poll_interval is not None else _poll_interval()
        self._session: ServerSession | None = None
        self._snapshot: dict[Path, _FileState] = {}

    # ── session wiring ────────────────────────────────────────────

    def set_session(self, session: ServerSession | None) -> None:
        """Attach (or detach) the active MCP session.

        Called by the ``InitializedNotification`` handler to give the watcher
        a live session through which it can send notifications.  Pass ``None``
        to detach (e.g. on disconnect).

        Args:
            session: The active :class:`~mcp.server.session.ServerSession`,
                or ``None`` to disable notification dispatch.
        """
        self._session = session
        if session is not None:
            log.debug("Resource watcher: session attached")
        else:
            log.debug("Resource watcher: session detached")

    # ── path helpers ──────────────────────────────────────────────

    def _watched_files(self) -> dict[Path, str]:
        """Return a mapping of absolute path → resource URI for all watchable files.

        The map is rebuilt on every scan so that newly-created skill directories
        are picked up automatically.
        """
        mapping: dict[Path, str] = {}
        root = self._root

        # SKILLS.md → dev10x://skills/index
        skills_index = root / "SKILLS.md"
        mapping[skills_index] = "dev10x://skills/index"

        # .claude/rules/INDEX.md → dev10x://rules/index
        rules_index = root / ".claude" / "rules" / "INDEX.md"
        mapping[rules_index] = "dev10x://rules/index"

        # .claude/rules/*.md → dev10x://rules/{stem}
        rules_dir = root / ".claude" / "rules"
        if rules_dir.is_dir():
            for md in rules_dir.glob("*.md"):
                if md.name != "INDEX.md":
                    mapping[md] = f"dev10x://rules/{md.stem}"

        # references/*.md → dev10x://references/{stem}
        references_dir = root / "references"
        if references_dir.is_dir():
            for md in references_dir.glob("*.md"):
                mapping[md] = f"dev10x://references/{md.stem}"

        # skills/*/references/playbook.yaml → dev10x://skills/{name}/playbook
        skills_dir = root / "skills"
        if skills_dir.is_dir():
            for playbook in skills_dir.glob("*/references/playbook.yaml"):
                skill_name = playbook.parent.parent.name
                mapping[playbook] = f"dev10x://skills/{skill_name}/playbook"

        return mapping

    # ── scan logic ────────────────────────────────────────────────

    def _take_snapshot(
        self,
        watched: dict[Path, str],
    ) -> dict[Path, _FileState]:
        """Return a fresh snapshot of file states for *watched*."""
        snapshot: dict[Path, _FileState] = {}
        for path in watched:
            exists = path.exists()
            mtime = path.stat().st_mtime if exists else 0.0
            snapshot[path] = _FileState(exists=exists, mtime=mtime)
        return snapshot

    def scan_changes(self) -> list[ResourceChanged]:
        """Scan watched files and return a list of change events.

        Compares the current on-disk state against the stored snapshot and
        updates the snapshot in-place.  Returns an empty list when nothing
        has changed.

        This method is synchronous and safe to call from tests without an
        event loop.  The :meth:`run` async loop calls it on every tick.

        Returns:
            List of :class:`ResourceChanged` events, one per changed URI.
            URIs are deduplicated — only the first event per URI per scan
            is returned.
        """
        watched = self._watched_files()
        current = self._take_snapshot(watched=watched)

        events: dict[str, ResourceChanged] = {}

        # Check every currently-watched path.
        for path, uri in watched.items():
            prev = self._snapshot.get(path)
            cur = current[path]

            if prev is None:
                # Previously unknown path — treat as potential addition.
                if cur.exists:
                    log.debug("Resource watcher: new file %s → %s", path, uri)
                    events[uri] = ResourceChanged(uri=uri, list_changed=True)
            elif not prev.exists and cur.exists:
                # File appeared.
                log.debug("Resource watcher: appeared %s → %s", path, uri)
                events[uri] = ResourceChanged(uri=uri, list_changed=True)
            elif prev.exists and not cur.exists:
                # File disappeared.
                log.debug("Resource watcher: disappeared %s → %s", path, uri)
                events[uri] = ResourceChanged(uri=uri, list_changed=True)
            elif prev.exists and cur.exists and prev.mtime != cur.mtime:
                # Content changed.
                log.debug("Resource watcher: modified %s → %s", path, uri)
                if uri not in events:
                    events[uri] = ResourceChanged(uri=uri, list_changed=False)

        # Check previously-watched paths no longer in watched (directory removed).
        for path, state in self._snapshot.items():
            if path not in watched and state.exists:
                removed_uri = self._snapshot_uri(path=path)
                if removed_uri and removed_uri not in events:
                    log.debug("Resource watcher: removed from watch %s → %s", path, removed_uri)
                    events[removed_uri] = ResourceChanged(uri=removed_uri, list_changed=True)

        self._snapshot = current
        return list(events.values())

    def _snapshot_uri(self, path: Path) -> str | None:
        """Return the URI for *path* from the previous snapshot's watch map, if known."""
        # Re-derive from the path's relationship to the root.
        root = self._root
        try:
            rel = path.relative_to(root)
        except ValueError:
            return None
        parts = rel.parts
        if len(parts) == 1 and parts[0] == "SKILLS.md":
            return "dev10x://skills/index"
        if len(parts) >= 3 and parts[0] == ".claude" and parts[1] == "rules":
            stem = Path(parts[2]).stem
            return "dev10x://rules/index" if parts[2] == "INDEX.md" else f"dev10x://rules/{stem}"
        if len(parts) == 2 and parts[0] == "references":
            return f"dev10x://references/{Path(parts[1]).stem}"
        if (
            len(parts) == 4
            and parts[0] == "skills"
            and parts[2] == "references"
            and parts[3] == "playbook.yaml"
        ):
            return f"dev10x://skills/{parts[1]}/playbook"
        return None

    # ── notification dispatch ─────────────────────────────────────

    async def _notify(self, events: list[ResourceChanged]) -> None:
        """Send MCP notifications for *events*.

        Skips silently when no session is attached.

        Args:
            events: Change events returned by :meth:`scan_changes`.
        """
        session = self._session
        if session is None or not events:
            return

        any_list_changed = any(e.list_changed for e in events)

        try:
            if any_list_changed:
                await session.send_resource_list_changed()
                log.debug("Resource watcher: sent resources/list_changed")

            for event in events:
                if not event.list_changed:
                    from pydantic import AnyUrl

                    await session.send_resource_updated(AnyUrl(event.uri))
                    log.debug("Resource watcher: sent resources/updated for %s", event.uri)
        except Exception:
            log.debug(
                "Resource watcher: notification send failed (session may have closed)",
                exc_info=True,
            )
            self._session = None

    # ── main loop ─────────────────────────────────────────────────

    async def run(self) -> None:
        """Poll for file changes and emit MCP notifications in a loop.

        Runs until cancelled (e.g. via task group cancellation at server
        shutdown).  When ``poll_interval`` is 0, this coroutine returns
        immediately (useful in tests to disable background polling).
        """
        if self._interval <= 0:
            log.debug("Resource watcher: disabled (interval=0)")
            return

        log.info("Resource watcher: starting, interval=%.1fs", self._interval)

        # Seed the snapshot on first run so we do not emit spurious changes
        # for files that already existed before the server started.
        watched = self._watched_files()
        self._snapshot = self._take_snapshot(watched=watched)

        while True:
            await asyncio.sleep(self._interval)
            try:
                changes = self.scan_changes()
                if changes:
                    await self._notify(events=changes)
            except Exception:
                log.debug("Resource watcher: scan error", exc_info=True)


# ── server wiring ─────────────────────────────────────────────────


# Module-level singleton holding the active watcher (GH-522): the shared
# SingletonHolder replaces the bespoke _WatcherRegistry so tests swap the
# watcher via the holder without touching the FastMCP server object.
_holder: SingletonHolder[KnowledgeResourceWatcher] = SingletonHolder()


def get_watcher() -> KnowledgeResourceWatcher | None:
    """Return the currently registered :class:`KnowledgeResourceWatcher`, or ``None``."""
    return _holder.get()


def wire_watcher_to_server(
    server: object,
    watcher: KnowledgeResourceWatcher,
) -> None:
    """Register *watcher* with the MCP low-level *server*'s notification handlers.

    Installs an ``InitializedNotification`` handler on the low-level server
    object so that the watcher receives the active session as soon as the MCP
    client completes its handshake.

    This function is intentionally low-coupling: it accepts any object with a
    ``notification_handlers`` dict and a ``request_context`` property, which
    matches both the real ``mcp.server.lowlevel.server.Server`` and test stubs.

    Args:
        server: The low-level MCP ``Server`` instance (e.g.
            ``fastmcp_instance._mcp_server``).
        watcher: The watcher to attach.
    """
    import mcp.types as mcp_types

    _holder.set(watcher)

    async def _on_initialized(notification: mcp_types.InitializedNotification) -> None:
        try:
            session = server.request_context.session  # type: ignore[attr-defined]
            watcher.set_session(session=session)
            log.debug("Resource watcher: session wired via InitializedNotification")
        except Exception:
            log.debug("Resource watcher: could not acquire session on initialized", exc_info=True)

    server.notification_handlers[mcp_types.InitializedNotification] = _on_initialized  # type: ignore[attr-defined]
    log.debug("Resource watcher: InitializedNotification handler registered")
