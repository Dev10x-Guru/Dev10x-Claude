"""Release MCP tool registrations (split from github_tools.py, GH-585)."""

from __future__ import annotations

from dev10x.mcp._app import server


@server.tool()
async def collect_prs(
    repo_path: str,
    from_tag: str | None = None,
    to_tag: str | None = None,
    ticket_pattern: str | None = None,
) -> dict:
    """Collect PRs between git tags for release notes.

    Args:
        repo_path: Path to the git repository
        from_tag: Start tag (optional)
        to_tag: End tag (optional)
        ticket_pattern: Regex override for ticket pattern

    Returns:
        Dictionary with keys: success (bool), output (str)
    """
    from dev10x import release as rel

    return (
        await rel.collect_prs(
            repo_path=repo_path,
            from_tag=from_tag,
            to_tag=to_tag,
            ticket_pattern=ticket_pattern,
        )
    ).to_dict()
