#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
"""Fail when a PEP 723 uv-script shells out with no timeout (GH-1414).

Usage:
    bin/check-subprocess-timeouts.py

Scans every PEP 723 uv-script (`# /// script` header) under the plugin
root for `subprocess.run` / `check_output` / `check_call` calls that pass
no `timeout=`. See `dev10x.subprocess_timeouts` for the detection logic
and the scope rationale, and `tests/test_subprocess_timeouts.py` for the
pytest-side unit coverage of the same detector.

Wired into `.pre-commit-config.yaml` as a local hook so the check runs in
the canonical lint suite, not only under `pytest` — mirroring
`bin/check-dependency-pins.py`, the guard built for the same class of
drift.

Exits with status 1 if any unbounded call is found.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from dev10x.subprocess_timeouts import scan_repository  # noqa: E402


def main() -> int:
    offenders = scan_repository(REPO_ROOT)
    if not offenders:
        return 0

    print(
        "A PEP 723 script cannot import dev10x.subprocess_utils, so an "
        "unbounded subprocess call hangs forever on a stalled `gh` or a "
        "keyring daemon with no TTY — in an unattended run, until morning "
        "(GH-1414). Declare a local _SUBPROCESS_TIMEOUT_SECONDS and pass "
        "timeout= :",
        file=sys.stderr,
    )
    for offender in offenders:
        print(f"  - {offender}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
