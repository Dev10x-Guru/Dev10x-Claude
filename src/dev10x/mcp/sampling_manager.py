"""MCP sampling support for Dev10x (GH-343).

Lets server-side tools request LLM completions from the connected client
through the MCP ``sampling/createMessage`` request, so a tool can perform a
reasoning step without shipping its own API client or key.  The client owns
the model and the credentials; the server merely asks for a completion.

Architecture
------------
``SamplingManager`` mirrors :class:`~dev10x.mcp.roots_manager.ClientRootsManager`:
it is created once per server lifespan in ``_app.py`` and wired to the
low-level MCP server via an ``InitializedNotification`` handler that captures
the active :class:`~mcp.server.session.ServerSession`.  Unlike roots, sampling
is purely on-demand — there is no proactive fetch on initialisation and no
``list_changed`` notification to listen for.  The manager simply holds the
session so a later tool call can issue a ``sampling/createMessage`` request.

``request_sampling`` is the backing domain function for the
``request_sampling`` MCP tool.  It returns a
:class:`~dev10x.domain.common.result.Result` so the handler unwraps it via
``to_wire()`` at the MCP boundary like every other tool (ADR-0009).

Environment variables
---------------------
DEV10X_SAMPLING_ENABLED
    Set to ``0`` (or ``false``/``no``) to disable sampling entirely.
    Defaults to ``1`` (enabled).  Useful in tests or environments where the
    client does not implement the sampling capability.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

from dev10x.domain.common.result import Result, err, ok

if TYPE_CHECKING:  # pragma: no cover
    from mcp.server.session import ServerSession

log = logging.getLogger(__name__)

_DEFAULT_MAX_TOKENS = 512


def _sampling_enabled() -> bool:
    """Return True when sampling is enabled.

    Reads ``DEV10X_SAMPLING_ENABLED``; defaults to ``True``.
    Set to ``0``/``false``/``no`` to disable.
    """
    raw = os.environ.get("DEV10X_SAMPLING_ENABLED", "").strip()
    return raw not in ("0", "false", "no")


# ── Manager ────────────────────────────────────────────────────────


class SamplingManager:
    """Issue server-initiated ``sampling/createMessage`` requests (GH-343).

    Lifecycle::

        manager = SamplingManager()
        wire_sampling_to_server(server=app._mcp_server, manager=manager)
        # (set_session called automatically on InitializedNotification)
        # tools may call manager.create_message(...) at any time

    Args:
        enabled: When ``False``, skip all network calls (useful in tests).
            ``None`` (default) reads ``DEV10X_SAMPLING_ENABLED``.
    """

    def __init__(self, enabled: bool | None = None) -> None:
        self._enabled: bool = enabled if enabled is not None else _sampling_enabled()
        self._session: ServerSession | None = None

    @property
    def enabled(self) -> bool:
        """Return whether sampling integration is enabled."""
        return self._enabled

    @property
    def has_session(self) -> bool:
        """Return whether an MCP session is currently attached."""
        return self._session is not None

    def set_session(self, session: ServerSession | None) -> None:
        """Attach (or detach) the active MCP session.

        Called by the ``InitializedNotification`` handler.

        Args:
            session: Active ``ServerSession``, or ``None`` to detach.
        """
        self._session = session
        if session is not None:
            log.debug("SamplingManager: session attached")
        else:
            log.debug("SamplingManager: session detached")

    async def create_message(
        self,
        *,
        prompt: str,
        system_prompt: str | None = None,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
        temperature: float | None = None,
    ) -> Result[dict[str, Any]]:
        """Request an LLM completion from the connected client.

        Sends a single user message via ``sampling/createMessage`` and
        returns the assistant response.

        Args:
            prompt: The user message to send to the client's LLM.
            system_prompt: Optional system prompt.
            max_tokens: Maximum number of tokens to generate.
            temperature: Optional sampling temperature.

        Returns:
            On success, ``ok`` with keys ``text`` (the assistant text, or
            ``None`` for non-text content), ``model``, ``role``,
            ``stop_reason``, and ``content_type``.  On failure, ``err`` with a
            descriptive message — sampling disabled, no active session, or the
            client rejected / does not support the request.
        """
        if not self._enabled:
            return err("Sampling is disabled (DEV10X_SAMPLING_ENABLED=0).")
        session = self._session
        if session is None:
            return err("No active MCP session — cannot request sampling.")

        import mcp.types as mcp_types

        message = mcp_types.SamplingMessage(
            role="user",
            content=mcp_types.TextContent(type="text", text=prompt),
        )
        try:
            result = await session.create_message(
                messages=[message],
                max_tokens=max_tokens,
                system_prompt=system_prompt,
                temperature=temperature,
            )
        except Exception as exc:
            log.debug(
                "SamplingManager: create_message failed (client may not support sampling)",
                exc_info=True,
            )
            return err(f"Sampling request failed: {exc}")

        content = result.content
        text = content.text if getattr(content, "type", None) == "text" else None
        return ok(
            {
                "text": text,
                "content_type": getattr(content, "type", None),
                "model": result.model,
                "role": result.role,
                "stop_reason": result.stopReason,
            }
        )


# ── module-level registry ──────────────────────────────────────────

_manager: SamplingManager | None = None


def get_manager() -> SamplingManager | None:
    """Return the currently registered :class:`SamplingManager`, or ``None``."""
    return _manager


async def request_sampling(
    *,
    prompt: str,
    system_prompt: str | None = None,
    max_tokens: int = _DEFAULT_MAX_TOKENS,
    temperature: float | None = None,
) -> Result[dict[str, Any]]:
    """Request an LLM completion from the client (GH-343).

    Backing domain function for the ``request_sampling`` MCP tool.  Resolves
    the registered :class:`SamplingManager` and delegates to its
    :meth:`SamplingManager.create_message`.  Returns ``err`` when no manager is
    registered (the server lifespan has not wired one yet).

    Args:
        prompt: The user message to send to the client's LLM.
        system_prompt: Optional system prompt.
        max_tokens: Maximum number of tokens to generate.
        temperature: Optional sampling temperature.
    """
    manager = get_manager()
    if manager is None:
        return err("Sampling is not available — no SamplingManager registered.")
    return await manager.create_message(
        prompt=prompt,
        system_prompt=system_prompt,
        max_tokens=max_tokens,
        temperature=temperature,
    )


def wire_sampling_to_server(
    server: object,
    manager: SamplingManager,
) -> None:
    """Register *manager* with the MCP low-level *server*'s handlers.

    Installs an ``InitializedNotification`` handler that captures the active
    MCP session so later tool calls can issue ``sampling/createMessage``
    requests.  When another component (the resource watcher or roots manager)
    already registered an ``InitializedNotification`` handler, the two are
    chained so both fire in sequence.

    Args:
        server: The low-level MCP ``Server`` instance
            (e.g. ``fastmcp_instance._mcp_server``).
        manager: The sampling manager to attach.
    """

    import mcp.types as mcp_types

    global _manager
    _manager = manager

    async def _on_initialized(notification: mcp_types.InitializedNotification) -> None:
        try:
            session = server.request_context.session  # type: ignore[attr-defined]
            manager.set_session(session=session)
        except Exception:
            log.debug(
                "SamplingManager: could not wire session on initialized",
                exc_info=True,
            )

    # Chain with any existing InitializedNotification handler (the resource
    # watcher and roots manager register theirs first).
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

    log.debug(
        "SamplingManager: handlers registered (InitializedNotification chained=%s)",
        existing_init is not None,
    )
