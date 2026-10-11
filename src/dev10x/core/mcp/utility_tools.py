"""Core utility and plugin-maintenance MCP tools (split from misc_tools.py, GH-1548)."""

from __future__ import annotations

from dev10x.domain.common.result import err, ok, to_wire
from dev10x.mcp._app import server


@server.tool()
async def background_preamble() -> dict:
    """Return the friction-avoidance preamble for background subagents (GH-610).

    Background subagents (workflow / monitor / loop / fanout) start with a
    fresh system prompt and never receive the SessionStart friction briefing.
    Dispatchers fetch this text and prepend it verbatim to each subagent
    prompt so the subagent avoids hook-tripping command shapes and stays on
    the pre-approved tool surface. The canonical source is
    ``references/orchestration/background-preamble.md``; this tool serves it
    without a Read permission prompt and keeps the dispatch paths from
    drifting.

    Returns:
        Dictionary with key: preamble (str) — the preamble document text.
        Returns ``{"error": ...}`` when the canonical document is missing.
    """
    from dev10x.session.service import SessionService

    text = SessionService().build_background_preamble_context()
    if not text:
        return to_wire(err("background-preamble.md not found in plugin root"))
    return to_wire(ok({"preamble": text}))


@server.tool()
async def mktmp(
    namespace: str,
    prefix: str,
    ext: str = "",
    directory: bool = False,
    create: bool = False,
    cwd: str | None = None,
) -> dict:
    """Generate a unique temp path under /tmp/Dev10x/<namespace>/.

    Files: returns a path WITHOUT creating the file by default so
    callers using the Write tool don't trigger its overwrite gate
    (GH-39). Pass create=True for legacy pre-created behavior.
    Directories: always created (the directory is the resource).

    Args:
        namespace: Subdirectory under /tmp/Dev10x/ (e.g., "git", "skill-audit")
        prefix: Filename prefix (e.g., "commit-msg", "pr-review")
        ext: File extension including dot (e.g., ".txt", ".json"). Ignored for directories.
        directory: If True, create a directory instead of a file.
        create: If True (and directory=False), pre-create an empty file.
            Default False — Write callers should write fresh.
        cwd: Effective working directory (GH-410). The script writes to /tmp
            so the CWD does not affect the output path, but pinning a valid
            directory prevents ENOENT when the previously-bound worktree was
            deleted. When omitted, safe_effective_cwd() provides the fallback.

    Returns:
        Dictionary with key: path (str) — the temp file/directory path
    """
    from dev10x import utilities as util
    from dev10x.subprocess_utils import use_cwd

    with use_cwd(cwd):
        return to_wire(
            await util.mktmp(
                namespace=namespace,
                prefix=prefix,
                ext=ext,
                directory=directory,
                create=create,
                cwd=cwd,
            )
        )


@server.tool()
async def update_paths(
    version: str | None = None,
    dry_run: bool = False,
    ensure_base: bool = False,
    generalize: bool = False,
    ensure_scripts: bool = False,
    ensure_reads: bool = False,
    init: bool = False,
    quiet: bool = False,
) -> dict:
    """Maintain Dev10x plugin permission settings across projects.

    Args:
        version: Target version to update to (auto-detects if omitted)
        dry_run: Preview changes without modifying files
        ensure_base: Add missing base permissions from projects.yaml
        generalize: Replace session-specific args with wildcards
        ensure_scripts: Verify all plugin scripts have allow rules
        ensure_reads: Emit per-skill Read rules with ~/ + /home/<user>/ twins
        init: Create userspace config from plugin default
        quiet: Suppress per-file details

    Returns:
        Dictionary with keys: success (bool), output (str)
    """
    from dev10x import permission as perm

    return to_wire(
        await perm.update_paths(
            version=version,
            dry_run=dry_run,
            ensure_base=ensure_base,
            generalize=generalize,
            ensure_scripts=ensure_scripts,
            ensure_reads=ensure_reads,
            init=init,
            quiet=quiet,
        )
    )


@server.tool()
async def permission_catalog_gap(
    verbose: bool = False,
) -> dict:
    """Report catalog rules missing from each settings file (read-only).

    The MCP surface for `dev10x permission catalog-gap`, so
    `dev10x:diag-friction` Step 3a can run its coverage check without
    a `Bash(uvx:*)` allow rule (GH-1175). Answers "does this settings
    file carry the catalog?" — a non-zero `total_missing` means a
    propagation gap, not a missing rule.

    Args:
        verbose: List every missing rule, not just the counts by family

    Returns:
        Dictionary with keys: total_missing (int), files_checked (int),
        clean (bool), messages (list[str])
    """
    from dev10x import permission as perm

    return to_wire(await perm.catalog_gap(verbose=verbose))


@server.tool()
async def record_upgrade(version: str | None = None) -> dict:
    """Record the currently-installed plugin version as applied.

    Called by dev10x:upgrade-cleanup after a successful run so the
    SessionStart install-check stops emitting upgrade prompts.

    Args:
        version: Explicit version to record. Defaults to the value
            from $CLAUDE_PLUGIN_ROOT/.claude-plugin/plugin.json.

    Returns:
        Dictionary with keys: version (str), path (str). Returns
        ``{"error": ...}`` when no version can be resolved.
    """
    from dev10x.domain.install_version import record_upgrade as _record_upgrade

    return to_wire(_record_upgrade(version=version))
