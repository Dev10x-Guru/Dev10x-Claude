"""MCP tool registrations for server-initiated sampling (GH-343)."""

from __future__ import annotations

from dev10x.mcp._app import server


@server.tool()
async def request_sampling(
    prompt: str,
    system_prompt: str | None = None,
    max_tokens: int = 512,
    temperature: float | None = None,
) -> dict:
    """Request an LLM completion from the connected client (GH-343).

    MCP clients that declare the ``sampling`` capability can run LLM
    completions on behalf of the server.  This lets a Dev10x tool perform a
    reasoning step through the client's model — no bespoke API client or key
    on the server side.  The client owns the model selection and may reject or
    rewrite the request.

    Args:
        prompt: The user message to send to the client's LLM.
        system_prompt: Optional system prompt to steer the completion.
        max_tokens: Maximum number of tokens to generate (default 512).
        temperature: Optional sampling temperature.

    Returns:
        On success, a dictionary with keys:

        * ``text`` — the assistant's text response, or ``null`` when the
          client returned non-text content.
        * ``content_type`` — the returned content block type (e.g. ``text``).
        * ``model`` — the model the client used.
        * ``role`` — the responder role (typically ``assistant``).
        * ``stop_reason`` — why sampling stopped, if known.

        On failure, ``{"error": "..."}`` — sampling disabled
        (``DEV10X_SAMPLING_ENABLED=0``), no active MCP session, no manager
        registered, or the client rejected / does not support sampling.
    """
    from dev10x.mcp.sampling_manager import request_sampling as _request_sampling

    result = await _request_sampling(
        prompt=prompt,
        system_prompt=system_prompt,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return result.to_dict()
