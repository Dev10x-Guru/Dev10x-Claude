"""Lint test: every dependency requirement declares an upper bound (GH-916).

Generalizes the GH-914 `mcp`-only detector
(`tests/test_mcp_version_pin.py`, now folded into this file) to cover
every PEP 723 uv-script header and `pyproject.toml`'s dependency arrays.
See `dev10x.dependency_pins` for the rationale and the shared detector
used here and by `bin/check-dependency-pins.py` (wired into
`.pre-commit-config.yaml`).
"""

from __future__ import annotations

from pathlib import Path

from dev10x.dependency_pins import (
    find_unbounded_pep723_requirements,
    find_unbounded_pyproject_requirements,
    scan_repository,
)
from dev10x.subprocess_utils import get_plugin_root


def test_every_dependency_requirement_is_upper_bounded() -> None:
    root = get_plugin_root()
    offenders = scan_repository(root)

    assert not offenders, (
        "An unbounded dependency requirement lets a new major release change "
        "behaviour without any commit touching the file — see GH-914 (`mcp` 2.x "
        "broke both MCP servers) and GH-916. Add an upper bound "
        "(e.g. `pyyaml>=6.0,<7`). Offenders:\n  - " + "\n  - ".join(offenders)
    )


def test_pep723_lint_detects_an_unbounded_requirement(tmp_path: Path) -> None:
    unbounded = tmp_path / "server.py"
    unbounded.write_text('# dependencies = ["mcp>=1.0", "pyyaml>=6.0,<7"]\n')

    offenders = find_unbounded_pep723_requirements(path=unbounded, root=tmp_path)

    assert offenders == ["server.py:1: mcp>=1.0"]


def test_pep723_lint_detects_a_completely_unpinned_requirement(tmp_path: Path) -> None:
    unbounded = tmp_path / "server.py"
    unbounded.write_text('# dependencies = ["requests"]\n')

    offenders = find_unbounded_pep723_requirements(path=unbounded, root=tmp_path)

    assert offenders == ["server.py:1: requests"]


def test_pep723_lint_accepts_a_bounded_requirement(tmp_path: Path) -> None:
    bounded = tmp_path / "server.py"
    bounded.write_text('# dependencies = ["mcp>=1.0,<2", "pyyaml>=6.0,<7"]\n')

    assert find_unbounded_pep723_requirements(path=bounded, root=tmp_path) == []


def test_pep723_lint_accepts_an_exact_pin(tmp_path: Path) -> None:
    exact = tmp_path / "server.py"
    exact.write_text('# dependencies = ["mcp==1.9.4"]\n')

    assert find_unbounded_pep723_requirements(path=exact, root=tmp_path) == []


def test_pep723_lint_ignores_non_dependency_lines(tmp_path: Path) -> None:
    unrelated = tmp_path / "server.py"
    unrelated.write_text('requires_version = ">=1.0"\nprint("mcp>=1.0")\n')

    assert find_unbounded_pep723_requirements(path=unrelated, root=tmp_path) == []


def test_pyproject_lint_detects_an_unbounded_dependency(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        "[project]\n"
        'dependencies = ["click>=8.0"]\n\n'
        "[project.optional-dependencies]\n"
        'dev = ["pytest>=8.0"]\n'
    )

    offenders = find_unbounded_pyproject_requirements(path=pyproject, root=tmp_path)

    assert offenders == [
        "pyproject.toml: [project.dependencies] click>=8.0",
        "pyproject.toml: [project.optional-dependencies.dev] pytest>=8.0",
    ]


def test_pyproject_lint_accepts_bounded_dependencies(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\ndependencies = ["click>=8.0,<9"]\n')

    assert find_unbounded_pyproject_requirements(path=pyproject, root=tmp_path) == []


def test_pyproject_lint_skips_non_pyproject_files(tmp_path: Path) -> None:
    other = tmp_path / "other.toml"
    other.write_text('[project]\ndependencies = ["click>=8.0"]\n')

    assert find_unbounded_pyproject_requirements(path=other, root=tmp_path) == []
