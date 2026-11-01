"""Test runner module — invokes ``pytest`` via ``uv run`` from MCP.

Provides a structured entry point for the ``dev10x:py-test`` skill so
the test gate works inside worktree sessions where ``pytest`` is not
on PATH and the Bash PreToolUse hook blocks every direct invocation
form (``pytest``, ``python -m pytest``, ``uv run pytest``). Because
the subprocess is launched from the MCP server, the Bash hook does
not apply (GH-238, mirrors the GH-232 ``merge_pr`` pattern).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tomllib
from pathlib import Path
from typing import Any

from dev10x.domain.common.result import Result, err, ok
from dev10x.domain.transport_budget import (
    MAX_TOOL_CALL_SECONDS,
    ClampedTimeout,
    clamp_tool_timeout,
)
from dev10x.subprocess_utils import async_run, effective_cwd

# GH-1285: the outcome vocabulary used to be a closed set, so a run
# reporting an outcome outside it broke the comma-separated chain and the
# whole line failed to match -- "9543 passed, 13 skipped, 1 xpassed" scored
# zeros on every field. pytest's outcome names are open-ended (xpassed,
# xfailed, deselected, warnings, rerun, ...), so the shape is matched
# instead and _COUNT_RE picks out the four that are reported.
_OUTCOME = r"\d+\s+[a-z]+"
_SUMMARY_RE = re.compile(
    rf"=+\s+({_OUTCOME}(?:,\s+{_OUTCOME})*)\s+in\s+[\d.]+s(?:\s+\([^)]*\))?\s+=+",
    re.MULTILINE,
)
# The `-q` form carries the same counts with no `=` decoration.
_SUMMARY_QUIET_RE = re.compile(
    rf"^({_OUTCOME}(?:,\s+{_OUTCOME})*)\s+in\s+[\d.]+s(?:\s+\([^)]*\))?$",
    re.MULTILINE,
)
_COUNT_RE = re.compile(r"(\d+)\s+(passed|failed|skipped|error|errors)\b")
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

# GH-1730: uv reports its own failures (an undefined extra, a Python it
# cannot download) on one `error:` line. Without it the caller sees only
# a non-zero exit and empty stdout.
_UV_ERROR_RE = re.compile(r"^error: .+$", re.MULTILINE)

_RETRY_EXTRA = "dev"


def _requirement_name(*, requirement: str) -> str:
    """Return the bare package name from a PEP 508 requirement string."""
    return re.split(r"[\s\[<>=!~;(]", requirement.strip(), maxsplit=1)[0].lower()


def _project_root(*, cwd: str | None = None) -> Path:
    return Path(cwd or effective_cwd() or os.getcwd())


def read_pyproject(*, cwd: str | None = None) -> dict[str, Any] | None:
    """Return the parsed ``pyproject.toml``, or None when absent or unparseable."""
    try:
        text = (_project_root(cwd=cwd) / _PYPROJECT).read_text(encoding="utf-8")
        return tomllib.loads(text)
    except (OSError, tomllib.TOMLDecodeError):
        return None


def _optional_dependency_groups(*, pyproject: dict[str, Any] | None) -> dict[str, Any]:
    groups = (pyproject or {}).get("project", {}).get("optional-dependencies", {})
    return groups if isinstance(groups, dict) else {}


def resolve_test_extras(*, cwd: str | None = None) -> list[str]:
    """Return the ``pyproject.toml`` extras that provide the test dependencies.

    Empty when there is no ``pyproject.toml``, it cannot be parsed, or no
    optional-dependency group declares pytest -- all of which mean a bare
    ``uv run pytest`` is the right command and nothing needs adding.
    """
    groups = _optional_dependency_groups(pyproject=read_pyproject(cwd=cwd))

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


def _uv_can_resolve(*, pyproject: dict[str, Any]) -> bool:
    # Virtual uv projects carry [tool.uv] or [dependency-groups] but no [project].
    has_tool_uv = "uv" in pyproject.get("tool", {})
    return "project" in pyproject or has_tool_uv or "dependency-groups" in pyproject


def _venv_python(*, root: Path) -> Path | None:
    candidate = root / ".venv" / "bin" / "python"
    return candidate if candidate.is_file() else None


def _uv_error_line(*, stderr: str) -> str | None:
    """uv's own ``error:`` line, e.g. "No interpreter found" or an undefined extra."""
    match = _UV_ERROR_RE.search(stderr)
    return match.group(0).strip() if match else None


def _pytest_command(
    *,
    extras: list[str],
    coverage: bool,
    extra_args: list[str],
    python: Path | None = None,
) -> list[str]:
    if python is not None:
        cmd = [str(python), "-m", "pytest"]
    else:
        cmd = ["uv", "run"]
        for extra in extras:
            cmd += ["--extra", extra]
        cmd += ["pytest"]
    if coverage:
        cmd += ["--cov", "--cov-report=term-missing"]
    cmd += ["--tb=short", "--color=no"]
    return cmd + extra_args


def _timed_out_message(*, runner: str, budget: ClampedTimeout, narrowing: str) -> str:
    """Say which ceiling ended the run, not merely that one did.

    A suite that genuinely needs longer than the transport allows is a
    different problem from a suite that hung, and the caller can only act
    differently on them if the message separates the two. When the clamp
    is what ended it, the caller is also told how to get the run it
    wanted — an unexplained ceiling just moves the dead end.
    """
    timed_out = f"{runner} timed out after {budget.seconds:.0f}s"
    if not budget.was_clamped:
        return timed_out
    return (
        f"{timed_out} — the requested {budget.requested:.0f}s was clamped "
        f"to the MCP transport budget (GH-1288). {narrowing}"
    )


async def run_tests(
    *,
    args: list[str] | None = None,
    coverage: bool = True,
    timeout: float = MAX_TOOL_CALL_SECONDS,
) -> Result[dict[str, Any]]:
    """Run pytest via ``uv run`` and return a structured summary.

    Args:
        args: Extra pytest arguments appended after the coverage flags.
        coverage: When True, add ``--cov --cov-report=term-missing``.
        timeout: Subprocess timeout in seconds (default
            ``MAX_TOOL_CALL_SECONDS``, GH-1331). A lower default used to
            sit under real full-suite runtimes (GH-1331's own suite:
            ~10,200 tests, observed exceeding 600s with coverage twice in
            one day), so the documented full-suite gate timed out on the
            call it mandates and every caller reached for the raw
            ``pytest`` the routing table forbids — discovering
            ``timeout=`` only by reading the tool schema. Defaulting to
            the transport ceiling closes that gap without inviting a
            value the transport will not sit through: anything higher is
            still clamped to ``MAX_TOOL_CALL_SECONDS`` (GH-1288), and the
            connection would drop before a bigger number bought anything.
            The error payload names the clamp when it bites.

    Returns:
        ok({
            "returncode": int,
            "summary": str,            # e.g. "150 passed"
            "summary_parsed": bool,    # False => counts below are not evidence
            "passed": int,
            "failed": int,
            "skipped": int,
            "errors": int,
            "coverage_percent": int | None,
            "failed_tests": [{"id": str, "message": str | None}, ...],
            "missing_coverage": [{"file": str, "percent": int, "lines": str}, ...],
            "extras": list[str],       # optional-dependency extras applied
            "retried_with_extras": bool,
            "launcher": "uv" | "venv", # how pytest was started (GH-1730)
            "uv_error": str | None,    # uv's own `error:` line, if any
            "stdout": str,
            "stderr": str,
        })

        err(...) when ``uv`` itself is missing, the subprocess times out,
        or the ``pyproject.toml`` has no ``[project]`` table and no
        ``.venv`` to fall back on (``verdict: "no_project_table"``). A
        non-zero pytest returncode is *not* an MCP-level error — the
        caller reads ``returncode`` and ``failed_tests``.
    """
    extra_args = list(args) if args else []
    root = _project_root()
    pyproject = read_pyproject()
    extras = resolve_test_extras()
    budget = clamp_tool_timeout(timeout)

    # GH-1730: with no PEP 621 [project] table (poetry, a bare tool-config
    # file) uv ignores the repo's Python pin and cannot see its
    # dependencies, so `uv run pytest` fails with nothing pointing at the
    # layout. An existing virtualenv is the environment the project's own
    # tooling built; without one, say what is wrong.
    python: Path | None = None
    if pyproject is not None and not _uv_can_resolve(pyproject=pyproject):
        python = _venv_python(root=root)
        if python is None:
            return err(
                f"{root / _PYPROJECT} has no [project] table (poetry or a "
                "tool-config-only file), so `uv run pytest` cannot resolve "
                "its Python version or dependencies. Create the project's "
                "virtualenv at .venv (e.g. `poetry install` with "
                "virtualenvs.in-project) and retry, or add a PEP 621 "
                "[project] table.",
                verdict="no_project_table",
            )
        extras = []

    try:
        proc = await async_run(
            args=_pytest_command(
                extras=extras,
                coverage=coverage,
                extra_args=extra_args,
                python=python,
            ),
            timeout=budget.seconds,
        )
    except FileNotFoundError:
        return err(
            "uv not found on PATH — install uv or call pytest via the "
            "test skill's documented fallback."
        )

    if proc.returncode == -1 and "timed out" in proc.stderr.lower():
        return err(
            _timed_out_message(
                runner="pytest",
                budget=budget,
                narrowing=(
                    "Narrow the run (-k, a path) or invoke pytest through the "
                    "test skill's documented fallback for a full serial suite."
                ),
            ),
            verdict="timeout",
            elapsed=budget.seconds,
            timeout_clamped=budget.was_clamped,
            stdout=proc.stdout,
            stderr=proc.stderr,
        )

    # Safety net for the case resolution cannot see: a group that carries the
    # test deps without declaring pytest itself (a shared `conftest` import
    # like factory-boy). Retrying once here is what keeps the caller from
    # reaching for the raw command. Only when the extra exists: uv rejects
    # an undeclared one outright, which replaced a useful collection error
    # with a misleading one (GH-1730).
    retried = False
    can_retry = python is None and _RETRY_EXTRA in _optional_dependency_groups(pyproject=pyproject)
    if not extras and can_retry and _looks_like_missing_dependency(proc=proc):
        retried = True
        extras = [_RETRY_EXTRA]
        try:
            proc = await async_run(
                args=_pytest_command(extras=extras, coverage=coverage, extra_args=extra_args),
                timeout=budget.seconds,
            )
        except FileNotFoundError:  # pragma: no cover - first call already proved uv exists
            pass

    parsed = _parse(proc.stdout)
    payload: dict[str, Any] = {
        "returncode": proc.returncode,
        "extras": extras,
        "retried_with_extras": retried,
        "launcher": "uv" if python is None else "venv",
        "uv_error": _uv_error_line(stderr=proc.stderr) if python is None else None,
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

# GH-1683: vitest prints `      Tests  2 failed | 554 passed (556)` — no
# colon, a pipe separator, and the total in parentheses.
_VITEST_TESTS_RE = re.compile(r"^\s*Tests\s{2,}(?P<body>\d.*)$", re.MULTILINE)
_VITEST_TOTAL_RE = re.compile(r"\((\d+)\)\s*$")
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

# GH-1683: defaulting to jest ran zero tests in a vitest repo and returned
# passed 0 / failed 0. Detection reads only fixed config filenames and
# package.json, so the same checkout always resolves to the same runner.
_CONFIG_EXTENSIONS = ("ts", "mts", "cts", "js", "mjs", "cjs")
_VITEST_CONFIGS = tuple(f"vitest.config.{ext}" for ext in _CONFIG_EXTENSIONS)
_JEST_CONFIGS = (*(f"jest.config.{ext}" for ext in _CONFIG_EXTENSIONS), "jest.config.json")
_LOCKFILE_MANAGERS = (("pnpm-lock.yaml", "pnpm"), ("yarn.lock", "yarn"))
_PACKAGE_JSON = "package.json"
_FALLBACK_NODE_RUNNER = "jest"


def _read_package_json(*, root: Path) -> dict[str, Any]:
    try:
        parsed = json.loads((root / _PACKAGE_JSON).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def detect_node_runner(*, cwd: str) -> str:
    root = Path(cwd)
    if any((root / name).is_file() for name in _VITEST_CONFIGS):
        return "vitest"
    package = _read_package_json(root=root)
    if any((root / name).is_file() for name in _JEST_CONFIGS) or "jest" in package:
        return "jest"
    scripts = package.get("scripts")
    if isinstance(scripts, dict) and _NODE_DEFAULT_SCRIPT in scripts:
        for lockfile, manager in _LOCKFILE_MANAGERS:
            if (root / lockfile).is_file():
                return manager
        return "npm"
    return _FALLBACK_NODE_RUNNER


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
    runner: str | None = None,
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
            ``None`` (default) detects it from the working directory
            (GH-1683): a ``vitest.config.*`` selects vitest, a
            ``jest.config.*`` or a ``jest`` key in ``package.json``
            selects jest, a ``test`` script selects the lockfile's
            package manager, and jest is the last resort.
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
        ok({"returncode", "runner", "script", "summary", "summary_parsed",
            "passed", "failed", "skipped", "todo", "total", "stdout",
            "stderr"})

        ``summary_parsed`` is False when no summary line was found, in
        which case the counts below it are not evidence of anything.

        err(...) when the runner binary is missing, the runner name is
        unknown, ``script`` is unsupported by the runner, the subprocess
        times out, or the default test script exited non-zero without
        reporting any executed test (GH-1683) — a run that executed
        nothing must not read as clean. A non-zero returncode with parsed
        failures is *not* an MCP-level error.
    """
    if runner is None:
        runner = detect_node_runner(cwd=effective_cwd() or os.getcwd())
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

    budget = clamp_tool_timeout(timeout)

    try:
        proc = await async_run(args=cmd, env=_overlay_env(env), timeout=budget.seconds)
    except FileNotFoundError:
        return err(
            f"{base[0]} not found on PATH — install Node tooling or run the "
            f"test via the documented fallback."
        )

    if proc.returncode == -1 and "timed out" in proc.stderr.lower():
        return err(
            _timed_out_message(
                runner="node tests",
                budget=budget,
                narrowing=(
                    "Narrow the run (a test-name filter, a path) or split the suite across calls."
                ),
            ),
            verdict="timeout",
            elapsed=budget.seconds,
            timeout_clamped=budget.was_clamped,
            stdout=proc.stdout,
            stderr=proc.stderr,
        )

    # jest/vitest write their summary to stderr; scan both streams.
    parsed = _parse_node(f"{proc.stdout}\n{proc.stderr}")
    if _ran_nothing(returncode=proc.returncode, script=script, parsed=parsed):
        return err(
            f"{runner} exited {proc.returncode} without reporting any executed "
            f"test — the runner may not match this project. Pass runner= "
            f"explicitly (one of: {', '.join(sorted(_NODE_RUNNERS))}).",
            verdict="no_tests_ran",
            runner=runner,
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
        )
    payload: dict[str, Any] = {
        "returncode": proc.returncode,
        "runner": runner,
        "script": script,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        **parsed,
    }
    return ok(payload)


def _ran_nothing(*, returncode: int, script: str, parsed: dict[str, Any]) -> bool:
    # A named non-test script (``lint:tsc``) never prints a test summary, so
    # its non-zero exit is an ordinary result rather than a silent no-op.
    if returncode == 0 or script != _NODE_DEFAULT_SCRIPT:
        return False
    if not parsed["summary_parsed"]:
        return True
    total = parsed["total"]
    if total is None:
        total = sum(parsed[key] for key in ("passed", "failed", "skipped", "todo"))
    return total == 0


def _parse_node(output: str) -> dict[str, Any]:
    """Extract structured results from a jest ``Tests:`` or vitest ``Tests`` line."""
    output = _ANSI_RE.sub("", output)
    counts = {"passed": 0, "failed": 0, "skipped": 0, "todo": 0}
    summary = ""
    total: int | None = None

    match = _NODE_TESTS_RE.search(output) or _VITEST_TESTS_RE.search(output)
    if match:
        summary = match.group("body").strip()
        for count, label in _NODE_COUNT_RE.findall(summary):
            key = "skipped" if label == "pending" else label
            counts[key] = int(count)
        total_match = _NODE_TOTAL_RE.search(summary) or _VITEST_TOTAL_RE.search(summary)
        total = int(total_match.group(1)) if total_match else None

    return {
        "summary": summary,
        # Same ambiguity as the pytest parser, and the same remedy: an
        # unmatched `Tests:` line is indistinguishable from a run that
        # collected nothing unless the caller is told which it was.
        "summary_parsed": bool(match),
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

    match = _SUMMARY_RE.search(stdout) or _SUMMARY_QUIET_RE.search(stdout)
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
        # GH-1285: all-zero counts otherwise read identically whether the
        # run collected nothing or the parser simply found no summary line
        # -- and "collected nothing" is the false-green this wrapper exists
        # to catch. A caller branching on the counts must check this first.
        "summary_parsed": bool(match),
        "passed": counts["passed"],
        "failed": counts["failed"],
        "skipped": counts["skipped"],
        "errors": counts["errors"],
        "coverage_percent": coverage_percent,
        "failed_tests": failed_tests,
        "missing_coverage": missing_coverage,
    }


__all__ = ["resolve_test_extras", "run_node_tests", "run_tests"]
