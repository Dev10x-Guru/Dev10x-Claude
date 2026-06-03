"""Shared FastMCP application instance for the Dev10x CLI server.

Split out of server_cli.py (GH-243/A6) so per-domain tool modules
register against one server without a circular import.

GH-341: A lifespan context manager starts the knowledge-resource file
watcher and wires it to the active MCP session so that
``notifications/resources/list_changed`` and
``notifications/resources/updated`` are emitted to clients whenever the
underlying files change.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP

from dev10x.mcp.resource_watcher import KnowledgeResourceWatcher, wire_watcher_to_server
from dev10x.subprocess_utils import get_plugin_root

log = logging.getLogger(__name__)


@asynccontextmanager
async def _knowledge_watcher_lifespan(app: FastMCP) -> AsyncIterator[None]:
    """Lifespan that runs the knowledge-resource file watcher (GH-341).

    On server start:
    1. Creates a :class:`~dev10x.mcp.resource_watcher.KnowledgeResourceWatcher`
       rooted at the plugin install directory.
    2. Registers an ``InitializedNotification`` handler on the low-level
       server so the watcher receives the active session as soon as the
       MCP client completes its handshake.
    3. Starts the poll loop as a background asyncio task.

    On server shutdown (lifespan exit) the background task is cancelled.
    """
    plugin_root = get_plugin_root()
    watcher = KnowledgeResourceWatcher(plugin_root=plugin_root)

    wire_watcher_to_server(server=app._mcp_server, watcher=watcher)

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


server = FastMCP(name="Dev10x-cli", lifespan=_knowledge_watcher_lifespan)
