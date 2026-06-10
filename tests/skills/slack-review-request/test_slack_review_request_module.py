"""Tests for the importable slack_review_request module (GH-546).

The standalone script copy keeps its own print/sys.exit entry-point
glue; these tests cover the src module's domain-layer contract.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from dev10x.skills.notifications import slack_review_request as mod


class TestGhJson:
    def test_raises_gh_command_error_on_nonzero_exit(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """GH-546: gh failures raise instead of print + sys.exit in domain code."""

        def fake_run(*args: object, **kwargs: object) -> SimpleNamespace:
            return SimpleNamespace(returncode=1, stdout="", stderr="boom")

        monkeypatch.setattr(mod.subprocess, "run", fake_run)
        with pytest.raises(mod.GhCommandError, match="boom"):
            mod.gh_json(args=["pr", "view", "1"])

    def test_returns_parsed_json_on_success(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def fake_run(*args: object, **kwargs: object) -> SimpleNamespace:
            return SimpleNamespace(returncode=0, stdout='{"ok": true}', stderr="")

        monkeypatch.setattr(mod.subprocess, "run", fake_run)
        assert mod.gh_json(args=["pr", "view", "1"]) == {"ok": True}
