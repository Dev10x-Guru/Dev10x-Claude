"""Test runner module — invokes ``pytest`` via ``uv run`` from MCP.

Provides a structured entry point for the ``Dev10x:py-test`` skill so
the test gate works inside worktree sessions where ``pytest`` is not
on PATH and the Bash PreToolUse hook blocks every direct invocation
form (``pytest``, ``python -m pytest``, ``uv run pytest``). Because
the subprocess is launched from the MCP server, the Bash hook does
not apply (GH-238, mirrors the GH-232 ``merge_pr`` pattern).
"""

from __future__ import annotations

import re
from typing import Any

from dev10x.domain.common.result import Result, err, ok
from dev10x.subprocess_utils import async_run

_SUMMARY_RE = re.compile(
    r"=+\s+(\d+\s+(?:passed|failed|skipped|error|errors)"
    r"(?:,\s+\d+\s+(?:passed|failed|skipped|error|errors))*)"
    r"\s+in\s+[\d.]+s\s+=+",
    re.MULTILINE,
)
_COUNT_RE = re.compile(r"(\d+)\s+(passed|failed|skipped|error|errors)")
_COVERAGE_TOTAL_RE = re.compile(
    r"^TOTAL\s+\d+\s+\d+(?:\s+\d+\s+\d+)?\s+(\d+)%",
    re.MULTILINE,
)
_FAILED_LINE_RE = re.compile(r"^FAILED\s+(\S+)(?:\s+-\s+(.*))?$", re.MULTILINE)
_MISSING_LINE_RE = re.compile(
    r"^(src/\S+\.py)\s+\d+\s+\d+(?:\s+\d+\s+\d+)?\s+(\d+)%\s+(.+)$",
    re.MULTILINE,
)


async def run_tests(
    *,
    args: list[str] | None = None,
    coverage: bool = True,
    timeout: float = 600,
) -> Result[dict[str, Any]]:
    """Run pytest via ``uv run`` and return a structured summary.

    Args:
        args: Extra pytest arguments appended after the coverage flags.
        coverage: When True, add ``--cov --cov-report=term-missing``.
        timeout: Subprocess timeout in seconds (default 10 minutes).

    Returns:
        ok({
            "returncode": int,
            "summary": str,            # e.g. "150 passed"
            "passed": int,
            "failed": int,
            "skipped": int,
            "errors": int,
            "coverage_percent": int | None,
            "failed_tests": [{"id": str, "message": str | None}, ...],
            "missing_coverage": [{"file": str, "percent": int, "lines": str}, ...],
            "stdout": str,
            "stderr": str,
        })

        err(...) only when ``uv`` itself is missing or the subprocess
        times out. A non-zero pytest returncode is *not* an MCP-level
        error — the caller reads ``returncode`` and ``failed_tests``.
    """
    extra = list(args) if args else []
    cmd = ["uv", "run", "pytest"]
    if coverage:
        cmd += ["--cov", "--cov-report=term-missing"]
    cmd += ["--tb=short", "--color=no"]
    cmd += extra

    try:
        proc = await async_run(args=cmd, timeout=timeout)
    except FileNotFoundError:
        return err(
            "uv not found on PATH — install uv or call pytest via the "
            "test skill's documented fallback."
        )

    if proc.returncode == -1 and "timed out" in proc.stderr.lower():
        return err(
            f"pytest timed out after {timeout:.0f}s",
            stdout=proc.stdout,
            stderr=proc.stderr,
        )

    parsed = _parse(proc.stdout)
    payload: dict[str, Any] = {
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        **parsed,
    }
    return ok(payload)


# GH-703: node/JS test runners. Routing the run through the MCP server
# keeps it off the Bash layer — including the core-harness brace-expansion
# check that no allow-rule can suppress (e.g. a quoted ``{ts,tsx}`` glob).
_NODE_RUNNERS: dict[str, list[str]] = {
    "jest": ["npx", "jest"],
    "vitest": ["npx", "vitest", "run"],
    "yarn": ["yarn", "test"],
    "npm": ["npm", "test"],
    "pnpm": ["pnpm", "test"],
}
# Runners that accept a ``--coverage`` flag directly. ``yarn``/``npm``/
# ``pnpm`` delegate to the project's configured ``test`` script, so the
# coverage flag is left to that script rather than injected here.
_NODE_COVERAGE_FLAG: dict[str, str] = {"jest": "--coverage", "vitest": "--coverage"}

_NODE_TESTS_RE = re.compile(r"^Tests:\s+(?P<body>.+)$", re.MULTILINE)
_NODE_COUNT_RE = re.compile(r"(\d+)\s+(passed|failed|skipped|todo|pending)")
_NODE_TOTAL_RE = re.compile(r"(\d+)\s+total")


async def run_node_tests(
    *,
    runner: str = "jest",
    args: list[str] | None = None,
    coverage: bool = True,
    timeout: float = 600,
) -> Result[dict[str, Any]]:
    """Run a node/JS test runner and return a structured summary (GH-703).

    Mirrors :func:`run_tests` for the node dev loop. ``yarn ... test`` and
    ``jest`` can only run through the Bash layer otherwise, where they hit
    permission prompts and the brace-expansion core-harness block. Because
    the subprocess is launched from the MCP server, the Bash hook does not
    apply (GH-238 pattern).

    Args:
        runner: One of ``jest``, ``vitest``, ``yarn``, ``npm``, ``pnpm``.
        args: Extra arguments appended after the coverage flag.
        coverage: When True and the runner supports it, add ``--coverage``.
        timeout: Subprocess timeout in seconds (default 10 minutes).

    Returns:
        ok({"returncode", "runner", "summary", "passed", "failed",
            "skipped", "todo", "total", "stdout", "stderr"})

        err(...) only when the runner binary is missing, the runner name
        is unknown, or the subprocess times out. A non-zero runner
        returncode is *not* an MCP-level error.
    """
    base = _NODE_RUNNERS.get(runner)
    if base is None:
        return err(
            f"Unknown node test runner {runner!r}. "
            f"Expected one of: {', '.join(sorted(_NODE_RUNNERS))}."
        )
    cmd = list(base)
    if coverage and runner in _NODE_COVERAGE_FLAG:
        cmd.append(_NODE_COVERAGE_FLAG[runner])
    cmd += list(args) if args else []

    try:
        proc = await async_run(args=cmd, timeout=timeout)
    except FileNotFoundError:
        return err(
            f"{base[0]} not found on PATH — install Node tooling or run the "
            f"test via the documented fallback."
        )

    if proc.returncode == -1 and "timed out" in proc.stderr.lower():
        return err(
            f"node tests timed out after {timeout:.0f}s",
            stdout=proc.stdout,
            stderr=proc.stderr,
        )

    # jest/vitest write their summary to stderr; scan both streams.
    parsed = _parse_node(f"{proc.stdout}\n{proc.stderr}")
    payload: dict[str, Any] = {
        "returncode": proc.returncode,
        "runner": runner,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        **parsed,
    }
    return ok(payload)


def _parse_node(output: str) -> dict[str, Any]:
    """Extract structured results from a jest/vitest-style ``Tests:`` line."""
    counts = {"passed": 0, "failed": 0, "skipped": 0, "todo": 0}
    summary = ""
    total: int | None = None

    match = _NODE_TESTS_RE.search(output)
    if match:
        summary = match.group("body").strip()
        for count, label in _NODE_COUNT_RE.findall(summary):
            key = "skipped" if label == "pending" else label
            counts[key] = int(count)
        total_match = _NODE_TOTAL_RE.search(summary)
        total = int(total_match.group(1)) if total_match else None

    return {
        "summary": summary,
        "passed": counts["passed"],
        "failed": counts["failed"],
        "skipped": counts["skipped"],
        "todo": counts["todo"],
        "total": total,
    }


def _parse(stdout: str) -> dict[str, Any]:
    """Extract structured test results from pytest stdout."""
    counts = {"passed": 0, "failed": 0, "skipped": 0, "errors": 0}
    summary = ""

    match = _SUMMARY_RE.search(stdout)
    if match:
        summary = match.group(1).strip()
        for count, label in _COUNT_RE.findall(summary):
            key = "errors" if label.startswith("error") else label
            counts[key] = int(count)

    cov_match = _COVERAGE_TOTAL_RE.search(stdout)
    coverage_percent: int | None = int(cov_match.group(1)) if cov_match else None

    failed_tests = [
        {"id": test_id, "message": message or None}
        for test_id, message in _FAILED_LINE_RE.findall(stdout)
    ]

    missing_coverage = [
        {"file": path, "percent": int(percent), "lines": lines.strip()}
        for path, percent, lines in _MISSING_LINE_RE.findall(stdout)
        if int(percent) < 100
    ]

    return {
        "summary": summary,
        "passed": counts["passed"],
        "failed": counts["failed"],
        "skipped": counts["skipped"],
        "errors": counts["errors"],
        "coverage_percent": coverage_percent,
        "failed_tests": failed_tests,
        "missing_coverage": missing_coverage,
    }


__all__ = ["run_node_tests", "run_tests"]
