"""Test-runner MCP tool registrations (split from misc_tools.py, GH-1548)."""

from __future__ import annotations

from typing import Literal, cast

# Context is required at runtime: FastMCP evaluates tool annotations with
# eval_str=True to detect the injected context parameter (GH-342). The
# noqa keeps ruff from stripping it as a type-only import under
# `from __future__ import annotations`.
from mcp.server.fastmcp import Context  # noqa: F401

from dev10x.domain.common.result import to_wire
from dev10x.domain.transport_budget import MAX_TOOL_CALL_SECONDS
from dev10x.mcp._app import server


@server.tool()
async def run_tests(
    args: list[str] | None = None,
    coverage: bool = True,
    timeout: int = MAX_TOOL_CALL_SECONDS,
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
        timeout: Subprocess timeout in seconds (default
            ``MAX_TOOL_CALL_SECONDS``, GH-1331 — the transport ceiling
            a larger value is clamped to anyway, GH-1288). A suite whose
            full run genuinely exceeds this needs narrowing (``-k``, a
            path) or the test skill's documented fallback, not a bigger
            number here.
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
    from dev10x.coding import runner
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
    script: str = "test",
    args: list[str] | None = None,
    coverage: bool = True,
    env: dict[str, str] | None = None,
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
            the package-manager runners delegate to a ``package.json``
            script.
        script: The ``package.json`` script to run (default ``test``). Use
            it to bring a non-test check such as ``lint:tsc`` inside this
            wrapper instead of invoking ``tsc``/``node`` raw on the Bash
            layer (GH-1029). Only ``yarn``/``npm``/``pnpm`` resolve a
            script name — pairing it with ``jest``/``vitest`` returns an
            error rather than ignoring it.
        args: Extra arguments appended after the coverage flag.
        coverage: When True (default) and the runner supports it, add
            ``--coverage``.
        env: Variables overlaid on the inherited environment (e.g.
            ``{"TZ": "America/New_York"}`` to match a CI-pinned timezone
            that snapshot tests depend on).
        timeout: Subprocess timeout in seconds (default 600).
        cwd: Effective working directory (GH-979). Must be ABSOLUTE — a
            relative path is rejected, because the server resolves it
            against its own directory rather than the caller's checkout
            and a green run then certifies the wrong tree (GH-1264).
        ctx: FastMCP context injected automatically — do not pass (GH-342).

    Returns:
        Dictionary with keys: returncode (int), runner (str), script (str),
        summary (str), passed (int), failed (int), skipped (int),
        todo (int), total (int | None), cwd (str), stdout (str),
        stderr (str). ``cwd`` is the absolute directory the run actually
        happened in, so a green result can be audited against the tree it
        was meant to cover (GH-1264). A non-zero ``returncode`` is *not*
        an MCP-level error — callers read ``returncode`` to decide.
    """
    import os

    from dev10x.coding import runner as test_runner
    from dev10x.subprocess_utils import effective_cwd, use_cwd

    if ctx is not None:
        await ctx.report_progress(progress=0, total=100, message=f"Starting {runner}")
        await ctx.info(f"run_node_tests: launching {runner}")

    with use_cwd(cwd):
        result = to_wire(
            await test_runner.run_node_tests(
                runner=runner,
                script=script,
                args=args,
                coverage=coverage,
                env=env,
                timeout=timeout,
            )
        )
        # Echo where the run actually happened (GH-1264), so a green
        # result can be audited against the tree it was meant to cover.
        result.setdefault("cwd", effective_cwd() or os.getcwd())

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
