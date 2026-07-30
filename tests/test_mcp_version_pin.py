"""Lint test: every `mcp` requirement declares an upper bound.

`mcp` 2.x removed `mcp.server.fastmcp`, which `dev10x.mcp._app` imports.
Because the MCP server entry points are PEP 723 uv-scripts, an unbounded
`mcp>=1.0` resolves the newest release on every invocation — so the day
2.0 published, both servers died with `ModuleNotFoundError` at plugin
load and Claude Code silently started sessions with no Dev10x tools.
An upper bound makes the major-version bump a deliberate edit instead of
a surprise at session start.
"""

from __future__ import annotations

import re
from pathlib import Path

from dev10x.subprocess_utils import get_plugin_root

_SCANNED_SUFFIXES = frozenset({".py", ".toml", ".sh"})
_SKIPPED_DIRS = frozenset({".git", ".venv", "node_modules", "__pycache__", "dist", "build"})

# Matches a quoted requirement for the `mcp` distribution. The leading quote
# keeps prose out of the results and makes `fastmcp` / `mcp-server-foo`
# non-matches; the specifier runs to the closing quote so a comma-joined range
# like `mcp>=1.0,<2` is captured whole rather than truncated at the comma.
_MCP_REQUIREMENT = re.compile(r"[\"']mcp\s*(?P<specifier>[<>=!~][^\"']*)")


def _scanned_files() -> list[Path]:
    root = get_plugin_root()
    return sorted(
        path
        for path in root.rglob("*")
        if path.suffix in _SCANNED_SUFFIXES
        and path.is_file()
        and path != Path(__file__)
        and not _SKIPPED_DIRS.intersection(path.relative_to(root).parts)
    )


def _unbounded_mcp_requirements(*, path: Path, root: Path) -> list[str]:
    offenders: list[str] = []
    for lineno, line in enumerate(path.read_text().splitlines(), start=1):
        for match in _MCP_REQUIREMENT.finditer(line):
            specifier = match.group("specifier")
            if "<" not in specifier and "==" not in specifier:
                offenders.append(f"{path.relative_to(root)}:{lineno}: mcp{specifier.strip()}")
    return offenders


def test_every_mcp_requirement_is_upper_bounded() -> None:
    root = get_plugin_root()
    offenders: list[str] = []
    for path in _scanned_files():
        offenders.extend(_unbounded_mcp_requirements(path=path, root=root))

    assert not offenders, (
        "An unbounded `mcp` requirement lets a new major release break the MCP "
        "servers at plugin load — `mcp` 2.x dropped `mcp.server.fastmcp`. Add an "
        "upper bound (e.g. `mcp>=1.0,<2`). Offenders:\n  - " + "\n  - ".join(offenders)
    )


def test_the_lint_detects_an_unbounded_requirement(tmp_path: Path) -> None:
    unbounded = tmp_path / "server.py"
    unbounded.write_text('# dependencies = ["mcp>=1.0", "pyyaml>=6.0"]\n')

    offenders = _unbounded_mcp_requirements(path=unbounded, root=tmp_path)

    assert offenders == ["server.py:1: mcp>=1.0"]


def test_the_lint_accepts_a_bounded_requirement(tmp_path: Path) -> None:
    bounded = tmp_path / "server.py"
    bounded.write_text('# dependencies = ["mcp>=1.0,<2", "pyyaml>=6.0"]\n')

    assert _unbounded_mcp_requirements(path=bounded, root=tmp_path) == []
