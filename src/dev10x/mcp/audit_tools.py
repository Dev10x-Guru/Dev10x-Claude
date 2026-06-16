"""Audit MCP tool registrations (split from server_cli.py, GH-243/A6)."""

from __future__ import annotations

from dev10x.domain.common.result import to_wire
from dev10x.mcp._app import server


@server.tool()
async def audit_extract_session(
    jsonl_path: str,
    output_path: str | None = None,
) -> dict:
    """Extract a Claude Code JSONL session into readable markdown.

    Args:
        jsonl_path: Path to the JSONL session file
        output_path: Optional output file path

    Returns:
        Dictionary with keys: success (bool), output (str)
    """
    from dev10x import audit

    return to_wire(
        await audit.extract_session(
            jsonl_path=jsonl_path,
            output_path=output_path,
        )
    )


@server.tool()
async def audit_analyze_actions(
    transcript_path: str,
    output_path: str | None = None,
) -> dict:
    """Analyze actions from a session transcript.

    Args:
        transcript_path: Path to the markdown transcript
        output_path: Optional output file path

    Returns:
        Dictionary with keys: success (bool), output (str)
    """
    from dev10x import audit

    return to_wire(
        await audit.analyze_actions(
            transcript_path=transcript_path,
            output_path=output_path,
        )
    )


@server.tool()
async def audit_analyze_permissions(
    transcript_path: str,
    settings_path: str | None = None,
    output_path: str | None = None,
) -> dict:
    """Analyze permission friction from a session transcript.

    Args:
        transcript_path: Path to the markdown transcript
        settings_path: Optional settings.json path
        output_path: Optional output file path

    Returns:
        Dictionary with keys: success (bool), output (str)
    """
    from dev10x import audit

    return to_wire(
        await audit.analyze_permissions(
            transcript_path=transcript_path,
            settings_path=settings_path,
            output_path=output_path,
        )
    )


@server.tool()
async def audit_hook_log_path() -> dict:
    """Return the active audit-wrap JSONL log directory and today's log file.

    Resolves DEV10X_HOOK_AUDIT_DIR (default /tmp/Dev10x/hook-audit) so
    agents can locate hook-audit data without grep-hunting (GH-29).

    Returns:
        Dictionary with keys: audit_dir, today_log, today_log_exists,
        audit_dir_exists, available_logs, audit_disabled
    """
    from dev10x import audit

    return to_wire(await audit.hook_log_path())


@server.tool()
async def audit_hook_recent(
    limit: int = 50,
    hook_name: str | None = None,
    span_id: str | None = None,
    log_path: str | None = None,
) -> dict:
    """Return recent records from the audit-wrap JSONL log.

    Args:
        limit: Maximum records to return (most recent). 0 returns all.
        hook_name: Optional filter on the "hook" field.
        span_id: Optional filter on the "span_id" field.
        log_path: Optional explicit log file path. Defaults to today.

    Returns:
        Dictionary with keys: log_path, exists, count, records
    """
    from dev10x import audit

    return to_wire(
        await audit.hook_recent(
            limit=limit,
            hook_name=hook_name,
            span_id=span_id,
            log_path=log_path,
        )
    )
