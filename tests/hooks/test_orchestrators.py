"""Tests for hook orchestrator scripts (GH-959).

Verifies SessionStart/Stop orchestrators consolidate feature
invocations into single entries, tolerate per-feature failures,
and still emit valid hookSpecificOutput envelopes.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "hooks" / "scripts"
SESSION_START = SCRIPTS / "session-start.py"
SESSION_STOP = SCRIPTS / "session-stop.py"


def _run(script: Path, payload: dict) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=str(SCRIPTS.parent.parent),
        env={
            "DEV10X_HOOK_AUDIT": "0",
            "PATH": "/usr/bin:/bin:/usr/local/bin",
            "HOME": str(Path.home()),
        },
    )


class TestSessionStartOrchestrator:
    def test_exits_cleanly_with_empty_payload(self, tmp_path: Path) -> None:
        result = _run(SESSION_START, {})
        assert result.returncode == 0

    def test_produces_json_envelope_when_context_available(self) -> None:
        result = _run(SESSION_START, {"session_id": "test-session"})
        assert result.returncode == 0
        if result.stdout.strip():
            obj = json.loads(result.stdout)
            assert "hookSpecificOutput" in obj
            assert obj["hookSpecificOutput"]["hookEventName"] == "SessionStart"


class TestSessionStopOrchestrator:
    def test_exits_cleanly_with_empty_payload(self) -> None:
        result = _run(SESSION_STOP, {})
        assert result.returncode == 0

    def test_goodbye_message_present_with_session_id(self) -> None:
        result = _run(SESSION_STOP, {"session_id": "test-abc"})
        assert result.returncode == 0
        assert "Thank you for using Dev10x" in result.stdout


class TestOrchestratorConsolidation:
    """Orchestrators must survive feature failures — one broken feature
    does not skip the rest."""

    def test_session_start_survives_subfeature_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Feed malformed data that one feature might choke on
        result = _run(SESSION_START, {"session_id": ""})
        assert result.returncode == 0


class TestAutonomyReassurance:
    """GH-261: SessionStart MOTD injects a reassurance block when the
    supervisor opted into adaptive + solo-maintainer autonomy.

    The block fires ONLY when both conditions hold — any other profile
    must leave session output unchanged so attended/team sessions are
    not nudged toward auto-advance behavior.
    """

    def _write_session_yaml(self, *, tmp_path: Path, content: str) -> Path:
        toplevel = tmp_path / "repo"
        (toplevel / ".claude" / "Dev10x").mkdir(parents=True)
        (toplevel / ".claude" / "Dev10x" / "session.yaml").write_text(content)
        return toplevel

    def test_fires_on_adaptive_solo_maintainer(self, tmp_path: Path) -> None:
        from dev10x.hooks.session_policy import BuildAutonomyReassuranceRule

        toplevel = self._write_session_yaml(
            tmp_path=tmp_path,
            content="friction_level: adaptive\nactive_modes: [solo-maintainer]\n",
        )
        result = BuildAutonomyReassuranceRule(toplevel=str(toplevel)).apply()
        assert "Supervisor monitors context" in result
        assert "trust the plan" in result

    def test_silent_when_friction_guided(self, tmp_path: Path) -> None:
        from dev10x.hooks.session_policy import BuildAutonomyReassuranceRule

        toplevel = self._write_session_yaml(
            tmp_path=tmp_path,
            content="friction_level: guided\nactive_modes: [solo-maintainer]\n",
        )
        assert BuildAutonomyReassuranceRule(toplevel=str(toplevel)).apply() == ""

    def test_silent_when_solo_maintainer_missing(self, tmp_path: Path) -> None:
        from dev10x.hooks.session_policy import BuildAutonomyReassuranceRule

        toplevel = self._write_session_yaml(
            tmp_path=tmp_path,
            content="friction_level: adaptive\nactive_modes: []\n",
        )
        assert BuildAutonomyReassuranceRule(toplevel=str(toplevel)).apply() == ""

    def test_silent_when_session_yaml_missing(self, tmp_path: Path) -> None:
        from dev10x.hooks.session_policy import BuildAutonomyReassuranceRule

        toplevel = tmp_path / "repo"
        toplevel.mkdir()
        assert BuildAutonomyReassuranceRule(toplevel=str(toplevel)).apply() == ""

    def test_silent_when_session_yaml_malformed(self, tmp_path: Path) -> None:
        from dev10x.hooks.session_policy import BuildAutonomyReassuranceRule

        toplevel = self._write_session_yaml(
            tmp_path=tmp_path,
            content="friction_level: adaptive\nactive_modes: [solo-maintainer\n",
        )
        assert BuildAutonomyReassuranceRule(toplevel=str(toplevel)).apply() == ""

    def test_dispatch_returns_empty_without_toplevel(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from dev10x.hooks import session_dispatch

        monkeypatch.setattr(session_dispatch, "_get_toplevel", lambda: None)
        assert session_dispatch.build_autonomy_reassurance_context() == ""

    def test_dispatch_resolves_through_rule_with_toplevel(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from dev10x.hooks import session_dispatch

        toplevel = self._write_session_yaml(
            tmp_path=tmp_path,
            content="friction_level: adaptive\nactive_modes: [solo-maintainer]\n",
        )
        monkeypatch.setattr(session_dispatch, "_get_toplevel", lambda: str(toplevel))
        assert (
            "Supervisor monitors context" in session_dispatch.build_autonomy_reassurance_context()
        )

    def test_facade_reexports_dispatch(self) -> None:
        from dev10x.hooks import session

        assert hasattr(session, "build_autonomy_reassurance_context")


class TestRunFeatureBufferDiscard:
    """E9: _run_feature must discard partial stdout when a feature raises.

    Appending half-written JSON to context_parts would corrupt the
    SessionStart envelope.
    """

    def _import_session_start(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("_session_start_under_test", SESSION_START)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_returns_empty_on_exception(self) -> None:
        module = self._import_session_start()

        def fake_audit_hook(*, name: str, event: str = ""):
            def decorator(fn):
                return fn

            return decorator

        def feature_that_prints_then_raises() -> None:
            print("PARTIAL_JSON_PAYLOAD")
            raise RuntimeError("boom")

        result = module._run_feature(
            name="test",
            fn=feature_that_prints_then_raises,
            audit_hook=fake_audit_hook,
        )
        assert result == ""

    def test_keeps_output_on_systemexit(self) -> None:
        module = self._import_session_start()

        def fake_audit_hook(*, name: str, event: str = ""):
            def decorator(fn):
                return fn

            return decorator

        def feature_that_exits() -> None:
            print("CLEAN_OUTPUT")
            raise SystemExit(0)

        result = module._run_feature(
            name="test",
            fn=feature_that_exits,
            audit_hook=fake_audit_hook,
        )
        assert "CLEAN_OUTPUT" in result

    def test_returns_clean_output_on_success(self) -> None:
        module = self._import_session_start()

        def fake_audit_hook(*, name: str, event: str = ""):
            def decorator(fn):
                return fn

            return decorator

        def feature_clean() -> None:
            print("HELLO")

        result = module._run_feature(
            name="test",
            fn=feature_clean,
            audit_hook=fake_audit_hook,
        )
        assert "HELLO" in result
