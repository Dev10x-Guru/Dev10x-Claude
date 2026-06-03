"""MCP tool registrations for client-roots awareness (GH-344)."""

from __future__ import annotations

from dev10x.mcp._app import server


@server.tool()
async def list_client_roots() -> dict:
    """Return the client-declared MCP directory roots (GH-344).

    MCP clients (e.g. Claude Code after ``EnterWorktree``) may declare one
    or more filesystem roots via the ``roots`` capability.  Dev10x fetches
    this list on session initialisation and refreshes it whenever the
    client sends ``notifications/roots/list_changed``.

    The roots complement the existing GH-979 effective-CWD discipline: a
    skill that passes ``cwd=`` to an MCP tool can call this tool first to
    confirm the target directory is inside a declared root and fail early
    with a clear message if it is not.

    Returns:
        Dictionary with keys:

        * ``roots`` — list of ``{"uri": str, "name": str | null}`` objects,
          one per client-declared root.  Empty list when the client
          declares no roots.  ``null`` when no session has been established
          yet (e.g. the tool is called before the MCP handshake).
        * ``enabled`` — ``bool``, False when ``DEV10X_ROOTS_ENABLED=0``.
    """
    from dev10x.mcp.roots_manager import get_manager

    manager = get_manager()
    if manager is None:
        return {"roots": None, "enabled": False}

    roots = manager.roots
    return {
        "roots": [r.to_dict() for r in roots] if roots is not None else None,
        "enabled": manager._enabled,
    }
