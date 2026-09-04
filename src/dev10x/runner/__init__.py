"""Test runner module — invokes ``pytest`` via ``uv run`` from MCP.

Provides a structured entry point for the ``Dev10x:py-test`` skill so
the test gate works inside worktree sessions where ``pytest`` is not
on PATH and the Bash PreToolUse hook blocks every direct invocation
form (``pytest``, ``python -m pytest``, ``uv run pytest``). Because
the subprocess is launched from the MCP server, the Bash hook does
not apply (GH-238, mirrors the GH-232 ``merge_pr`` pattern).
"""

from __future__ import annotations

import os
import re
import subprocess
import tomllib
from pathlib import Path
from typing import Any

from dev10x.domain.common.result import Result, err, ok
from dev10x.subprocess_utils import async_run, effective_cwd

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

# GH-1198: a suite whose test dependencies live in an optional-dependency
# group dies at collection under a bare `uv run pytest`, and the agent then
# falls back to the raw `uv run --extra dev pytest` the routing table
# forbids -- for every iteration of the fix-test loop, not just the first.
# The wrapper resolves the extra itself so the sanctioned path is the one
# that works.
_PYPROJECT = "pyproject.toml"

# A requirement name that means "this group carries the test dependencies".
# Deliberately narrow: matching on any dev-ish tool would pull in a lint-only
# group and install more than the run needs.
_TEST_REQUIREMENT_MARKERS = ("pytest",)

# Preferred order when several groups qualify. A project that ships both
# `test` and `dev` usually means the narrower one.
_EXTRA_PREFERENCE = ("test", "tests", "dev", "develop", "testing")

# Collection died because an import was missing, rather than a test failing.
_MISSING_MODULE_RE = re.compile(r"ModuleNotFoundError: No module named", re.MULTILINE)


def _requirement_name(*, requirement: str) -> str:
    """Return the bare package name from a PEP 508 requirement string."""
    return re.split(r"[\s\[<>=!~;(]", requirement.strip(), maxsplit=1)[0].lower()


def resolve_test_extras(*, cwd: str | None = None) -> list[str]:
    """Return the ``pyproject.toml`` extras that provide the test dependencies.

    Empty when there is no ``pyproject.toml``, it cannot be parsed, or no
    optional-dependency group declares pytest -- all of which mean a bare
    ``uv run pytest`` is the right command and nothing needs adding.
    """
    root = Path(cwd or effective_cwd() or os.getcwd())
    try:
        parsed = tomllib.loads((root / _PYPROJECT).read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return []

    groups = parsed.get("project", {}).get("optional-dependencies", {})
    if not isinstance(groups, dict):
        return []

    qualifying = [
        name
        for name, requirements in groups.items()
        if isinstance(requirements, list)
        and any(
            _requirement_name(requirement=str(req)).startswith(_TEST_REQUIREMENT_MARKERS)
            for req in requirements
        )
    ]
    if not qualifying:
        return []

    for preferred in _EXTRA_PREFERENCE:
        if preferred in qualifying:
            return [preferred]
    return [sorted(qualifying)[0]]


def _pytest_command(*, extras: list[str], coverage: bool, extra_args: list[str]) -> list[str]:
    cmd = ["uv", "run"]
    for extra in extras:
        cmd += ["--extra", extra]
    cmd += ["pytest"]
    if coverage:
        cmd += ["--cov", "--cov-report=term-missing"]
    cmd += ["--tb=short", "--color=no"]
    return cmd + extra_args


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
            "extras": list[str],       # optional-dependency extras applied
            "retried_with_extras": bool,
            "stdout": str,
            "stderr": str,
        })

        err(...) only when ``uv`` itself is missing or the subprocess
        times out. A non-zero pytest returncode is *not* an MCP-level
        error — the caller reads ``returncode`` and ``failed_tests``.
    """
    extra_args = list(args) if args else []
    extras = resolve_test_extras()

    try:
        proc = await async_run(
            args=_pytest_command(extras=extras, coverage=coverage, extra_args=extra_args),
            timeout=timeout,
        )
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

    # Safety net for the case resolution cannot see: a group that carries the
    # test deps without declaring pytest itself (a shared `conftest` import
    # like factory-boy), or a project whose pyproject is unreadable. Retrying
    # once here is what keeps the caller from reaching for the raw command.
    retried = False
    if not extras and _looks_like_missing_dependency(proc=proc):
        retried = True
        extras = ["dev"]
        try:
            proc = await async_run(
                args=_pytest_command(extras=extras, coverage=coverage, extra_args=extra_args),
                timeout=timeout,
            )
        except FileNotFoundError:  # pragma: no cover - first call already proved uv exists
            pass

    parsed = _parse(proc.stdout)
    payload: dict[str, Any] = {
        "returncode": proc.returncode,
        "extras": extras,
        "retried_with_extras": retried,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        **parsed,
    }
    return ok(payload)


def _looks_like_missing_dependency(*, proc: subprocess.CompletedProcess[str]) -> bool:
    """True when the run died on a missing import rather than a failing test.

    Scoped to a non-zero exit so a suite that merely *mentions*
    ``ModuleNotFoundError`` in a passing test's output is not retried.
    """
    if proc.returncode == 0:
        return False
    return bool(_MISSING_MODULE_RE.search(proc.stdout) or _MISSING_MODULE_RE.search(proc.stderr))


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

# Runners that resolve a named ``package.json`` script (GH-1029). Only these
# understand ``script=``; ``jest``/``vitest`` are invoked directly through
# ``npx`` and have no script table to look a name up in.
_NODE_SCRIPT_RUNNERS = frozenset({"yarn", "npm", "pnpm"})

# The script name every runner already ran before ``script=`` existed.
# Keeping it the sentinel default preserves the exact historical command
# shape (``yarn test``, not ``yarn run test``) for every existing caller.
_NODE_DEFAULT_SCRIPT = "test"

_NODE_TESTS_RE = re.compile(r"^Tests:\s+(?P<body>.+)$", re.MULTILINE)
_NODE_COUNT_RE = re.compile(r"(\d+)\s+(passed|failed|skipped|todo|pending)")
_NODE_TOTAL_RE = re.compile(r"(\d+)\s+total")


def _overlay_env(extra: dict[str, str] | None) -> dict[str, str] | None:
    """Overlay ``extra`` on the inherited environment, or ``None`` when empty.

    ``asyncio.create_subprocess_exec(env=...)`` REPLACES the environment
    rather than extending it, so handing it a bare ``{"TZ": "UTC"}`` would
    launch the runner without ``PATH`` — the node binary would not even be
    found. Returning ``None`` for the empty case keeps the inherit-everything
    default rather than passing a copied environment for no reason.
    """
    if not extra:
        return None
    return {**os.environ, **extra}


async def run_node_tests(
    *,
    runner: str = "jest",
    script: str = _NODE_DEFAULT_SCRIPT,
    args: list[str] | None = None,
    coverage: bool = True,
    env: dict[str, str] | None = None,
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
        script: The ``package.json`` script to run (default ``test``), so a
            check like ``lint:tsc`` reaches the same structured wrapper
            instead of falling back to a raw ``node``/``tsc`` invocation
            (GH-1029). Only the package-manager runners resolve a script
            name; naming one alongside ``jest``/``vitest`` is an error
            rather than a silently ignored argument.
        args: Extra arguments appended after the coverage flag.
        coverage: When True and the runner supports it, add ``--coverage``.
            Never applies to a package-manager runner, so it cannot
            collide with a non-test ``script``.
        env: Variables overlaid on the inherited environment — for a script
            whose own definition pins something the wrapper would otherwise
            drop (e.g. ``TZ``, which snapshot tests are sensitive to).
        timeout: Subprocess timeout in seconds (default 10 minutes).

    Returns:
        ok({"returncode", "runner", "script", "summary", "passed", "failed",
            "skipped", "todo", "total", "stdout", "stderr"})

        err(...) only when the runner binary is missing, the runner name
        is unknown, ``script`` is unsupported by the runner, or the
        subprocess times out. A non-zero runner returncode is *not* an
        MCP-level error.
    """
    base = _NODE_RUNNERS.get(runner)
    if base is None:
        return err(
            f"Unknown node test runner {runner!r}. "
            f"Expected one of: {', '.join(sorted(_NODE_RUNNERS))}."
        )
    if script != _NODE_DEFAULT_SCRIPT and runner not in _NODE_SCRIPT_RUNNERS:
        return err(
            f"Runner {runner!r} cannot run the package.json script {script!r} — "
            f"it is invoked directly, not through a script table. Use one of: "
            f"{', '.join(sorted(_NODE_SCRIPT_RUNNERS))}."
        )
    cmd = list(base)
    if script != _NODE_DEFAULT_SCRIPT:
        # ``[pm, "test"]`` is the historical shape for the default script;
        # anything else goes through the explicit ``run`` verb.
        cmd = [base[0], "run", script]
    if coverage and runner in _NODE_COVERAGE_FLAG:
        cmd.append(_NODE_COVERAGE_FLAG[runner])
    cmd += list(args) if args else []

    try:
        proc = await async_run(args=cmd, env=_overlay_env(env), timeout=timeout)
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
        "script": script,
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


__all__ = ["resolve_test_extras", "run_node_tests", "run_tests"]
