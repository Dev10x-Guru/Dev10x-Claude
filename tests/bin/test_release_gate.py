"""Locks in the GH-387 release-gate rewrite (inform + guard, no smoke gate).

The gate logic in bin/release.sh runs only after sync_branches (git
checkout/pull), so it cannot be exercised end-to-end in a unit test.
These source-level assertions guard against a regression to the removed
dogfood smoke gate.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
RELEASE = _REPO_ROOT / "bin" / "release.sh"


class TestSyntax:
    def test_bash_syntax_is_valid(self) -> None:
        result = subprocess.run(
            ["bash", "-n", str(RELEASE)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr


class TestInformGuardGate:
    def test_uses_confirm_release_guard(self) -> None:
        source = RELEASE.read_text()
        assert "CONFIRM_RELEASE" in source
        assert "release_notice" in source

    def test_proceeds_for_interactive_tty(self) -> None:
        # `[[ -t 0 ]]` is the human-at-a-TTY fast path.
        assert "[[ -t 0 ]]" in RELEASE.read_text()


class TestRemovedDogfoodGate:
    def test_no_blocking_smoke_confirmation(self) -> None:
        source = RELEASE.read_text()
        assert "dogfood_gate" not in source
        assert "SKIP_DOGFOOD" not in source
        assert "ship ${rc_version}" not in source

    def test_no_broken_installed_plugin_probe(self) -> None:
        # The old probe looked for a Dev10x-Claude path that never exists.
        source = RELEASE.read_text()
        assert "installed_plugin_version" not in source
        assert "Dev10x-Claude" not in source
