"""Shared FastMCP application instance for the Dev10x CLI server.

Split out of server_cli.py (GH-243/A6) so per-domain tool modules
register against one server without a circular import.

GH-341: A lifespan context manager starts the knowledge-resource file
watcher and wires it to the active MCP session so that
``notifications/resources/list_changed`` and
``notifications/resources/updated`` are emitted to clients whenever the
underlying files change.

GH-344: The same lifespan also creates a :class:`ClientRootsManager`
that fetches and caches the client-declared directory roots via
``roots/list`` on session initialisation and refreshes the cache on
``notifications/roots/list_changed``.  The roots are used to scope
CWD/worktree operations, complementing the GH-979 effective-CWD
discipline.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP

from dev10x.mcp.resource_watcher import KnowledgeResourceWatcher, wire_watcher_to_server
from dev10x.mcp.roots_manager import ClientRootsManager, wire_roots_to_server
from dev10x.subprocess_utils import get_plugin_root

log = logging.getLogger(__name__)


@asynccontextmanager
async def _server_lifespan(app: FastMCP) -> AsyncIterator[None]:
    """Lifespan that wires the knowledge-resource watcher and roots manager.

    On server start:

    1. Creates a :class:`~dev10x.mcp.resource_watcher.KnowledgeResourceWatcher`
       rooted at the plugin install directory and registers its
       ``InitializedNotification`` handler (GH-341).
    2. Creates a :class:`~dev10x.mcp.roots_manager.ClientRootsManager` and
       registers its ``InitializedNotification`` handler (chained after the
       watcher's) plus a ``RootsListChangedNotification`` handler (GH-344).
    3. Starts the resource-watcher poll loop as a background asyncio task.

    On server shutdown (lifespan exit) the background task is cancelled.
    """
    plugin_root = get_plugin_root()
    watcher = KnowledgeResourceWatcher(plugin_root=plugin_root)

    # GH-341: resource watcher registers the first InitializedNotification handler.
    wire_watcher_to_server(server=app._mcp_server, watcher=watcher)

    # GH-344: roots manager chains its handler after the watcher's.
    roots_manager = ClientRootsManager()
    wire_roots_to_server(server=app._mcp_server, manager=roots_manager)

    task = asyncio.create_task(watcher.run(), name="dev10x-resource-watcher")
    log.debug("Resource watcher task started for root: %s", plugin_root)

    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        log.debug("Resource watcher task stopped")


server = FastMCP(name="Dev10x-cli", lifespan=_server_lifespan)
