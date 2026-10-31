"""Google Chat watch MCP tool registrations (GH-1682).

They touch only the local watch store, so a skill can arm a watch from
inside a session without a shell permission prompt. Reading Chat and
delivering to the bus is `dev10x skill notify gchat-watch poll`'s job.
"""

from __future__ import annotations

from dev10x.domain.common.result import ErrorResult, ok, to_wire
from dev10x.mcp._app import server


@server.tool()
async def gchat_watch_arm(
    thread: str | None = None,
    space: str | None = None,
    notify: list[str] | None = None,
    notify_roles: list[str] | None = None,
    route: bool = False,
    mode: str = "reply",
    ttl_hours: float = 24.0,
    own_message_names: list[str] | None = None,
) -> dict:
    """Arm a Google Chat watch that tells bus mailboxes about new messages (GH-1682).

    Re-arming the same space/thread merges targets, extends the TTL and
    keeps the cursor, so it never replays messages already delivered.

    Args:
        thread: Full spaces/<space>/threads/<id> name, or a bare thread id
            together with `space`. Omit to watch the whole space.
        space: Space alias from gchat-config.yaml, a space id, or spaces/<id>.
        notify: claude-bus mailbox names to deliver each new message to.
        notify_roles: Bus registry Roles, resolved at delivery time to the
            Reply-To of the newest hello with that Role.
        route: Dispatcher mode — with no notify targets, route each message
            by domain (explicit address, configured map, content).
        mode: "reply" disarms after the first delivered message; "ttl" stays
            armed until the TTL runs out.
        ttl_hours: Hours until the watch expires (default 24).
        own_message_names: Message names the watch must never report — the
            bot's own posts.

    Returns:
        Dictionary with key `watch` (the armed record).
    """
    from datetime import timedelta

    from dev10x.comm.skills.notifications import gchat_watch

    result = gchat_watch.arm_watch(
        space=space,
        thread=thread,
        notify=notify or (),
        notify_roles=notify_roles or (),
        route=route,
        mode=mode,
        ttl=timedelta(hours=ttl_hours),
        own_message_names=own_message_names or (),
    )
    if isinstance(result, ErrorResult):
        return to_wire(result)
    return to_wire(ok({"watch": result.value.to_dict()}))


@server.tool()
async def gchat_watch_disarm(
    watch_id: str | None = None,
    thread: str | None = None,
    space: str | None = None,
) -> dict:
    """Disarm a Google Chat watch by id, or by the space/thread it watches (GH-1682).

    Args:
        watch_id: Watch id as returned by gchat_watch_arm or gchat_watch_list.
        thread: Thread name of the watch, when no id is given.
        space: Space of the watch, when no id is given.

    Returns:
        Dictionary with key `watch` (the removed record).
    """
    from dev10x.comm.skills.notifications import gchat_watch

    result = gchat_watch.disarm_watch(watch_id=watch_id, space=space, thread=thread)
    if isinstance(result, ErrorResult):
        return to_wire(result)
    return to_wire(ok({"watch": result.value.to_dict()}))


@server.tool()
async def gchat_watch_list() -> dict:
    """List armed Google Chat watches with their targets, cursor and expiry (GH-1682).

    Returns:
        Dictionary with keys `watches` (list of records) and `count`.
    """
    from dev10x.comm.skills.notifications import gchat_watch

    result = gchat_watch.list_watches()
    if isinstance(result, ErrorResult):
        return to_wire(result)
    watches = [watch.to_dict() for watch in result.value]
    return to_wire(ok({"watches": watches, "count": len(watches)}))
