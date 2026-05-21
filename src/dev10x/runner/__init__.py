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


__all__ = ["run_tests"]
