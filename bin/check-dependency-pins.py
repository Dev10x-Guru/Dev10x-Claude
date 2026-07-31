#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
"""Fail when any dependency requirement lacks an upper bound (GH-916).

Usage:
    bin/check-dependency-pins.py

Scans every PEP 723 uv-script header (`# dependencies = [...]`) and
`pyproject.toml`'s `[project.dependencies]` / `[project.optional-dependencies]`
arrays under the plugin root. See `dev10x.dependency_pins` for the
detection logic and rationale, and `tests/test_dependency_pins.py` for
the pytest-side unit coverage of the same detector.

Wired into `.pre-commit-config.yaml` as a local hook so the check runs
in the canonical lint suite, not only under `pytest` (GH-916).

Exits with status 1 if any unbounded requirement is found.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from dev10x.dependency_pins import scan_repository  # noqa: E402


def main() -> int:
    offenders = scan_repository(REPO_ROOT)
    if not offenders:
        return 0

    print(
        "An unbounded dependency requirement lets a new major release change "
        "behaviour without any commit touching the file (GH-914, GH-916). "
        "Add an upper bound, e.g. pyyaml>=6.0,<7:",
        file=sys.stderr,
    )
    for offender in offenders:
        print(f"  - {offender}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
