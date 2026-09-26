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

GH-343: The lifespan also creates a :class:`SamplingManager` that captures
the active MCP session so server tools can request LLM completions from the
client via ``sampling/createMessage`` without a bespoke API client.
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP

from dev10x import subprocess_utils
from dev10x.domain.common.result import to_wire
from dev10x.mcp.resource_watcher import KnowledgeResourceWatcher, wire_watcher_to_server
from dev10x.mcp.roots_manager import ClientRootsManager, wire_roots_to_server
from dev10x.mcp.sampling_manager import SamplingManager, wire_sampling_to_server
from dev10x.subprocess_utils import get_plugin_root

log = logging.getLogger(__name__)


@asynccontextmanager
async def _server_lifespan(app: FastMCP) -> AsyncIterator[None]:
    """Lifespan that wires the resource watcher, roots, and sampling managers.

    On server start:

    1. Creates a :class:`~dev10x.mcp.resource_watcher.KnowledgeResourceWatcher`
       rooted at the plugin install directory and registers its
       ``InitializedNotification`` handler (GH-341).
    2. Creates a :class:`~dev10x.mcp.roots_manager.ClientRootsManager` and
       registers its ``InitializedNotification`` handler (chained after the
       watcher's) plus a ``RootsListChangedNotification`` handler (GH-344).
    3. Creates a :class:`~dev10x.mcp.sampling_manager.SamplingManager` and
       registers its ``InitializedNotification`` handler (chained after the
       roots manager's) so tools can request sampling (GH-343).
    4. Starts the resource-watcher poll loop as a background asyncio task.

    On server shutdown (lifespan exit) the background task is cancelled.
    """
    plugin_root = get_plugin_root()
    watcher = KnowledgeResourceWatcher(plugin_root=plugin_root)

    # GH-341: resource watcher registers the first InitializedNotification handler.
    wire_watcher_to_server(server=app._mcp_server, watcher=watcher)

    # GH-344: roots manager chains its handler after the watcher's.
    roots_manager = ClientRootsManager()
    wire_roots_to_server(server=app._mcp_server, manager=roots_manager)

    # GH-343: sampling manager chains its handler after the roots manager's
    # so server tools can request LLM completions from the client.
    sampling_manager = SamplingManager()
    wire_sampling_to_server(server=app._mcp_server, manager=sampling_manager)

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


def mcp_tool(fn):
    """Wrap an MCP handler with cwd binding + Result→dict unwrapping (GH-1426).

    Generalized from ``github_tools.github_tool`` — ``github_tools.py``
    factored "enter ``use_cwd``, call the domain function, route through
    ``to_wire()``" into one reusable wrapper applied to ~27 handlers,
    while five sibling tool modules (``git_tools``, ``gate_tools``,
    ``audit_tools``, ``task_index_tools``, ``plan_tools``) hand-wrote the
    identical boilerplate per handler instead — including re-importing
    ``use_cwd`` inside each function body. This is that cross-cutting
    concern lifted to the one place every tool module can import it from.

    The inner ``fn`` returns a ``Result``; this decorator enters
    ``use_cwd(kwargs["cwd"])`` and calls ``to_wire()`` at the MCP
    boundary, so the value FastMCP actually receives is the flattened
    wire ``dict`` — never a ``Result``.

    ``functools.wraps`` preserves the inner signature so FastMCP builds
    the correct *input* schema, but it also copies the inner ``->
    Result[dict]`` return annotation (and sets ``__wrapped__``). Newer
    FastMCP reads that annotation via ``inspect.signature(..., eval_str=
    True)`` and derives an *output* schema from the ``SuccessResult |
    ErrorResult`` union — which then rejects the flattened dict
    ``to_wire()`` returns (GH-712, GH-713: every github tool failed
    output-schema validation despite the underlying call succeeding).

    Pin the public signature's return type to ``dict`` (matching the
    directly-``@server.tool()`` handlers, for which no output schema is
    derived) via an explicit ``__signature__``. ``inspect.signature``
    honours ``__signature__`` ahead of the ``__wrapped__`` chain, so
    this is what FastMCP sees while the inner ``fn`` keeps its honest
    ``Result`` annotation for type-checking.

    Not every handler fits this shape — one that reports progress via
    an injected ``ctx: Context`` around the inner call (e.g.
    ``git_tools.rebase_groom``) has logic before/after the call that
    the decorator has no hook for, and stays on the direct
    ``@server.tool()`` + manual ``use_cwd``/``to_wire()`` pattern.
    """

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        with subprocess_utils.use_cwd(kwargs.get("cwd")):
            result = await fn(*args, **kwargs)
        return to_wire(result)

    wrapper.__signature__ = inspect.signature(fn, eval_str=True).replace(return_annotation=dict)
    return server.tool()(wrapper)
