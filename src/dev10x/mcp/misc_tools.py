"""Miscellaneous MCP tool registrations (split from server_cli.py, GH-243/A6)."""

from __future__ import annotations

from typing import Literal, cast

# Context is required at runtime: FastMCP evaluates tool annotations with
# eval_str=True to detect the injected context parameter (GH-342). The
# noqa keeps ruff from stripping it as a type-only import under
# `from __future__ import annotations`.
from mcp.server.fastmcp import Context  # noqa: F401

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
async def slack_thread_is_forward(
    parent_body: str,
    reply_count: int,
) -> dict:
    """Detect whether a Slack thread is likely a forward / cross-post (GH-218).

    Pure heuristic over an already-fetched thread payload. The caller
    fetches the thread via `mcp__claude_ai_Slack__slack_read_thread`
    and passes the parent message body + reply count here.

    Signals:
    - short_body: parent body word count below threshold (~30 words)
    - zero_replies: thread has no replies
    - external_link OR forwarding_language: parent references an
      external URL or uses forwarding phrasing (fwd, FYI, sharing, ...)

    Confidence:
    - high: all 3 signals present
    - medium: exactly 2 signals present
    - low: 0 or 1 signals present

    Args:
        parent_body: The parent message text from the Slack thread.
        reply_count: Number of replies on the thread.

    Returns:
        Dictionary with keys: is_forward (bool), confidence (str),
        signals (list[str]), upstream_hints (list[str]).
    """
    from dev10x.utilities import slack as slack_helper

    return to_wire(
        await slack_helper.slack_thread_is_forward(
            parent_body=parent_body,
            reply_count=reply_count,
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
async def generate_skill_index(
    force: bool = False,
) -> dict:
    """Generate SKILLS.md and .skills-menu.txt files.

    Args:
        force: Regenerate even when cache is fresh

    Returns:
        Dictionary with keys: success (bool), output (str)
    """
    from dev10x import skill_index as idx

    return to_wire(await idx.generate_all(force=force))


@server.tool()
async def record_upgrade(version: str | None = None) -> dict:
    """Record the currently-installed plugin version as applied.

    Called by Dev10x:upgrade-cleanup after a successful run so the
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


@server.tool()
async def run_tests(
    args: list[str] | None = None,
    coverage: bool = True,
    timeout: int = 600,
    cwd: str | None = None,
    ctx: Context | None = None,
) -> dict:
    """Run pytest with coverage via ``uv run`` (GH-238).

    Symmetric to ``merge_pr``/``create_pr``/``push_safe``: the
    subprocess is launched from the MCP server so the PreToolUse
    hook that blocks raw ``pytest`` / ``uv run pytest`` Bash
    invocations does not apply. This makes the documented test
    gate reachable from worktree sessions where ``pytest`` is not
    on PATH and every direct invocation form is hook-blocked.

    Args:
        args: Extra pytest arguments appended after coverage flags.
            Example: ``["src/dev10x/runner/"]`` or ``["-k", "name"]``.
        coverage: When True (default), add
            ``--cov --cov-report=term-missing``.
        timeout: Subprocess timeout in seconds (default 600).
        cwd: Effective working directory (GH-979).
        ctx: FastMCP context injected automatically — do not pass (GH-342).

    Returns:
        Dictionary with keys: returncode (int), summary (str),
        passed (int), failed (int), skipped (int), errors (int),
        coverage_percent (int | None), failed_tests (list[dict]),
        missing_coverage (list[dict]), stdout (str), stderr (str).
        A non-zero ``returncode`` is *not* an MCP-level error —
        callers read ``returncode`` and ``failed_tests`` to decide.
    """
    from dev10x import runner
    from dev10x.subprocess_utils import use_cwd

    extra_desc = " ".join(args) if args else "full suite"
    if ctx is not None:
        await ctx.report_progress(progress=0, total=100, message=f"Starting pytest: {extra_desc}")
        await ctx.info(f"run_tests: launching pytest ({extra_desc})")

    with use_cwd(cwd):
        result = to_wire(await runner.run_tests(args=args, coverage=coverage, timeout=timeout))

    if ctx is not None:
        summary = result.get("summary", "")
        failed = result.get("failed", 0)
        await ctx.report_progress(progress=100, total=100, message=f"pytest done: {summary}")
        level = cast(
            Literal["debug", "info", "warning", "error"],
            "warning" if failed else "info",
        )
        await ctx.log(level=level, message=f"run_tests: {summary or 'complete'}")

    return result


@server.tool()
async def run_node_tests(
    runner: str = "jest",
    args: list[str] | None = None,
    coverage: bool = True,
    timeout: int = 600,
    cwd: str | None = None,
    ctx: Context | None = None,
) -> dict:
    """Run jest / yarn / npm / pnpm / vitest tests off the Bash layer (GH-703).

    Symmetric to ``run_tests`` but for the node dev loop: the subprocess
    is launched from the MCP server, so the PreToolUse hook — including
    the core-harness brace-expansion block that no allow-rule can suppress
    (e.g. a quoted ``--collectCoverageFrom="…{ts,tsx}"`` glob) — does not
    apply. This makes ``yarn … test`` reachable from sessions where the
    Bash layer would otherwise prompt or hard-block it.

    Args:
        runner: One of ``jest`` (default), ``vitest``, ``yarn``, ``npm``,
            ``pnpm``. ``jest``/``vitest`` accept ``--coverage`` directly;
            the package-manager runners delegate to the project's
            configured ``test`` script.
        args: Extra arguments appended after the coverage flag.
        coverage: When True (default) and the runner supports it, add
            ``--coverage``.
        timeout: Subprocess timeout in seconds (default 600).
        cwd: Effective working directory (GH-979).
        ctx: FastMCP context injected automatically — do not pass (GH-342).

    Returns:
        Dictionary with keys: returncode (int), runner (str),
        summary (str), passed (int), failed (int), skipped (int),
        todo (int), total (int | None), stdout (str), stderr (str).
        A non-zero ``returncode`` is *not* an MCP-level error —
        callers read ``returncode`` to decide.
    """
    from dev10x import runner as test_runner
    from dev10x.subprocess_utils import use_cwd

    if ctx is not None:
        await ctx.report_progress(progress=0, total=100, message=f"Starting {runner}")
        await ctx.info(f"run_node_tests: launching {runner}")

    with use_cwd(cwd):
        result = to_wire(
            await test_runner.run_node_tests(
                runner=runner, args=args, coverage=coverage, timeout=timeout
            )
        )

    if ctx is not None:
        summary = result.get("summary", "")
        failed = result.get("failed", 0)
        await ctx.report_progress(progress=100, total=100, message=f"{runner} done: {summary}")
        level = cast(
            Literal["debug", "info", "warning", "error"],
            "warning" if failed else "info",
        )
        await ctx.log(level=level, message=f"run_node_tests: {summary or 'complete'}")

    return result
