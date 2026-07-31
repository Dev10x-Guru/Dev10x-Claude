"""Detect unbounded dependency requirements (GH-916).

GH-914 showed the failure mode concretely: `mcp` 2.x removed
`mcp.server.fastmcp`, and because the MCP server entry points are PEP 723
uv-scripts, an unbounded `mcp>=1.0` resolved the newest release on every
invocation — the day 2.0 published, both servers died with
`ModuleNotFoundError` at plugin load. The same exposure exists in every
other PEP 723 uv-script (`# /// script` header) and in `pyproject.toml`'s
`[project.dependencies]` / `[project.optional-dependencies]` arrays: an
unbounded requirement lets a new major release change behaviour without
any commit touching the file.

This module is the single detector shared by the pytest suite
(`tests/test_dependency_pins.py`) and the pre-commit entry point
(`bin/check-dependency-pins.py`), so the two never drift.

Policy: `requires-python` is intentionally exempt from the upper-bound
rule. Python itself does not ship breaking major-version churn the way
PyPI packages do, and pinning an upper bound would block running on a
newer interpreter that a script only needs a lower bound to support.
"""

from __future__ import annotations

import logging
import re
import tomllib
from pathlib import Path

_logger = logging.getLogger(__name__)

SCANNED_SUFFIXES = frozenset({".py", ".toml", ".sh"})
SKIPPED_DIRS = frozenset({".git", ".venv", "node_modules", "__pycache__", "dist", "build"})

# A PEP 723 dependency block in this repo is always a single-line TOML
# array comment: `# dependencies = ["pyyaml>=6.0,<7", ...]`.
_PEP723_DEPS_LINE = re.compile(r"^#\s*dependencies\s*=\s*(?P<array>\[.*\])\s*$")
# TOML permits both quote styles for a literal array item; match either
# so a single-quoted PEP 723 header isn't silently scanned as empty.
_QUOTED_ITEM = re.compile(r"""(?:"(?P<dq>[^"]*)"|'(?P<sq>[^']*)')""")
_REQUIREMENT = re.compile(
    r"^(?P<req>[A-Za-z][A-Za-z0-9_.\-]*(?:\[[^\]]*\])?)\s*(?P<specifier>.*)$"
)


def _is_bounded(specifier: str) -> bool:
    """A requirement is bounded when it pins an upper bound or an exact version.

    Only the version part counts — a PEP 508 environment marker (the
    clause after `;`, e.g. `foo; python_version<'3.12'`) can contain a
    `<` that has nothing to do with `foo`'s own version constraint, so
    it must be stripped before checking or an unbounded requirement
    with a marker would be silently treated as bounded.
    """
    version_part = specifier.split(";", 1)[0]
    return "<" in version_part or "==" in version_part


def _offending_requirements(items: list[str]) -> list[str]:
    offenders: list[str] = []
    for item in items:
        match = _REQUIREMENT.match(item.strip())
        if match is None:
            continue
        specifier = match.group("specifier").strip()
        if not _is_bounded(specifier):
            offenders.append(item.strip())
    return offenders


def find_unbounded_pep723_requirements(*, path: Path, root: Path) -> list[str]:
    """Return `path:lineno: requirement` offenders in a PEP 723 script header."""
    offenders: list[str] = []
    try:
        text = path.read_text()
    except (OSError, UnicodeDecodeError):
        _logger.warning("Skipping unreadable file during dependency-pin scan: %s", path)
        return offenders
    for lineno, line in enumerate(text.splitlines(), start=1):
        # Anchored on the raw (unstripped) line: a genuine PEP 723 header
        # comment always starts at column 0. Requiring that excludes
        # indented prose that merely *describes* the syntax (e.g. a
        # docstring example inside a validator message).
        deps_match = _PEP723_DEPS_LINE.match(line)
        if deps_match is None:
            continue
        items = [
            match.group("dq") if match.group("dq") is not None else match.group("sq")
            for match in _QUOTED_ITEM.finditer(deps_match.group("array"))
        ]
        for offender in _offending_requirements(items):
            offenders.append(f"{path.relative_to(root)}:{lineno}: {offender}")
    return offenders


def find_unbounded_pyproject_requirements(*, path: Path, root: Path) -> list[str]:
    """Return `path: [section] requirement` offenders in a pyproject.toml."""
    if path.name != "pyproject.toml":
        return []
    try:
        data = tomllib.loads(path.read_text())
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        _logger.warning("Skipping unreadable/invalid pyproject.toml during scan: %s", path)
        return []
    project = data.get("project", {})
    offenders: list[str] = []
    relpath = path.relative_to(root)

    for offender in _offending_requirements(project.get("dependencies", [])):
        offenders.append(f"{relpath}: [project.dependencies] {offender}")

    for extra, items in project.get("optional-dependencies", {}).items():
        for offender in _offending_requirements(items):
            offenders.append(f"{relpath}: [project.optional-dependencies.{extra}] {offender}")

    return offenders


def scanned_files(root: Path) -> list[Path]:
    # Excludes symlinks: Path.rglob() follows symlinked directories on this
    # project's floor Python (3.12 — the recurse_symlinks opt-out landed in
    # 3.13), so an unguarded scan could read a symlink's target content
    # (mild info-disclosure into pre-commit stderr) or hang on a cycle.
    return sorted(
        path
        for path in root.rglob("*")
        if path.suffix in SCANNED_SUFFIXES
        and path.is_file()
        and not path.is_symlink()
        and not SKIPPED_DIRS.intersection(path.relative_to(root).parts)
    )


def scan_repository(root: Path) -> list[str]:
    """Scan the whole tree and return every unbounded-requirement offender."""
    offenders: list[str] = []
    for path in scanned_files(root):
        offenders.extend(find_unbounded_pep723_requirements(path=path, root=root))
        offenders.extend(find_unbounded_pyproject_requirements(path=path, root=root))
    return offenders
