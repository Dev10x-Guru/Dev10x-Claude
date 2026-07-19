"""Tests for hook orchestrator scripts (GH-959).

Verifies SessionStart/Stop orchestrators consolidate feature
invocations into single entries, tolerate per-feature failures,
and still emit valid hookSpecificOutput envelopes.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

from dev10x.domain.friction_level import FrictionLevel

SCRIPTS = Path(__file__).resolve().parents[2] / "hooks" / "scripts"
SESSION_START = SCRIPTS / "session-start.py"
SESSION_STOP = SCRIPTS / "session-stop.py"
PLUGIN_LOAD_GUARD = SCRIPTS / "plugin-load-guard.sh"

# Isolated HOME so orchestrator subprocesses read no real ~/.claude state —
# decouples assertions from the host's home layout (GH-570).
_ISOLATED_HOME = tempfile.mkdtemp(prefix="dev10x-orchestrator-home-")


def _run(script: Path, payload: dict) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(SCRIPTS.parent.parent),
        env={
            "DEV10X_HOOK_AUDIT": "0",
            "PATH": "/usr/bin:/bin:/usr/local/bin",
            "HOME": _ISOLATED_HOME,
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

    def test_fires_on_adaptive_solo_maintainer(self) -> None:
        from dev10x.domain.session_rules import BuildAutonomyReassuranceRule

        result = BuildAutonomyReassuranceRule(
            friction_level=FrictionLevel.ADAPTIVE, active_modes=["solo-maintainer"]
        ).apply()
        assert "Supervisor monitors context" in result
        assert "trust the plan" in result

    def test_silent_when_friction_guided(self) -> None:
        from dev10x.domain.session_rules import BuildAutonomyReassuranceRule

        rule = BuildAutonomyReassuranceRule(
            friction_level=FrictionLevel.GUIDED, active_modes=["solo-maintainer"]
        )
        assert rule.apply() == ""

    def test_silent_when_solo_maintainer_missing(self) -> None:
        from dev10x.domain.session_rules import BuildAutonomyReassuranceRule

        rule = BuildAutonomyReassuranceRule(friction_level=FrictionLevel.ADAPTIVE, active_modes=[])
        assert rule.apply() == ""

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


class TestAutoPlanGuidanceWiring:
    """GH-678: auto-plan SessionStart briefing flows dispatch -> service -> rule."""

    def _write_session_yaml(self, *, tmp_path: Path, content: str) -> Path:
        toplevel = tmp_path / "repo"
        (toplevel / ".claude" / "Dev10x").mkdir(parents=True)
        (toplevel / ".claude" / "Dev10x" / "session.yaml").write_text(content)
        return toplevel

    def test_dispatch_returns_empty_without_toplevel(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from dev10x.hooks import session_dispatch

        monkeypatch.setattr(session_dispatch, "_get_toplevel", lambda: None)
        assert session_dispatch.build_auto_plan_guidance_context() == ""

    def test_dispatch_emits_briefing_with_auto_plan(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from dev10x.hooks import session_dispatch

        toplevel = self._write_session_yaml(
            tmp_path=tmp_path,
            content="friction_level: guided\nactive_modes: [auto-plan]\n",
        )
        monkeypatch.setattr(session_dispatch, "_get_toplevel", lambda: str(toplevel))
        assert "`auto-plan` mode active" in session_dispatch.build_auto_plan_guidance_context()

    def test_dispatch_silent_without_auto_plan(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from dev10x.hooks import session_dispatch

        toplevel = self._write_session_yaml(
            tmp_path=tmp_path,
            content="friction_level: adaptive\nactive_modes: [solo-maintainer]\n",
        )
        monkeypatch.setattr(session_dispatch, "_get_toplevel", lambda: str(toplevel))
        assert session_dispatch.build_auto_plan_guidance_context() == ""

    def test_facade_reexports_dispatch(self) -> None:
        from dev10x.hooks import session

        assert hasattr(session, "build_auto_plan_guidance_context")


class TestModeGuardWiring:
    """GH-805: durable-mode guard flows dispatch -> service -> rule."""

    def _write_config(self, *, tmp_path: Path, content: str) -> Path:
        toplevel = tmp_path / "repo"
        (toplevel / ".claude" / "Dev10x").mkdir(parents=True)
        (toplevel / ".claude" / "Dev10x" / "config.yaml").write_text(content)
        return toplevel

    def test_dispatch_returns_empty_without_toplevel(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from dev10x.hooks import session_dispatch

        monkeypatch.setattr(session_dispatch, "_get_toplevel", lambda: None)
        assert session_dispatch.build_mode_guard_context() == ""

    def test_dispatch_warns_on_forbidden_overlay(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from dev10x.hooks import session_dispatch

        toplevel = self._write_config(
            tmp_path=tmp_path,
            content=(
                "friction_level: guided\nactive_modes: [solo-maintainer]\nallowed_overlays: []\n"
            ),
        )
        monkeypatch.setattr(session_dispatch, "_get_toplevel", lambda: str(toplevel))
        assert "Durable-mode guard (GH-805)" in session_dispatch.build_mode_guard_context()

    def test_dispatch_silent_when_permissive(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from dev10x.hooks import session_dispatch

        toplevel = self._write_config(
            tmp_path=tmp_path,
            content="friction_level: guided\nactive_modes: [solo-maintainer]\n",
        )
        monkeypatch.setattr(session_dispatch, "_get_toplevel", lambda: str(toplevel))
        assert session_dispatch.build_mode_guard_context() == ""

    def test_facade_reexports_dispatch(self) -> None:
        from dev10x.hooks import session

        assert hasattr(session, "build_mode_guard_context")


class TestFrictionSetupNudge:
    """GH-886: SessionStart detects unconfigured repos and nudges the
    supervisor to run Dev10x:friction-setup instead of silently falling back
    to a preset. Global friction.yaml absent → seed a strict baseline + note;
    present but this repo unmatched → nudge (no write); matched → silent."""

    def _isolate_config(self, *, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
        from dev10x.domain.dev10x_paths import Dev10xConfigDir

        cfg = tmp_path / "config-home"
        monkeypatch.setenv("DEV10X_CONFIG_HOME", str(cfg))
        Dev10xConfigDir.reset_cache()
        return cfg

    def test_rule_seeded_text_points_to_skill(self) -> None:
        from dev10x.domain.session_rules import FrictionSetupNudgeRule, FrictionSetupState

        text = FrictionSetupNudgeRule(state=FrictionSetupState.SEEDED).apply()
        assert "strict" in text
        assert "/Dev10x:friction-setup" in text

    def test_rule_unmatched_names_repo(self) -> None:
        from dev10x.domain.session_rules import FrictionSetupNudgeRule, FrictionSetupState

        text = FrictionSetupNudgeRule(
            state=FrictionSetupState.UNMATCHED, repo_name="my-repo"
        ).apply()
        assert "my-repo" in text
        assert "/Dev10x:friction-setup" in text

    def test_rule_matched_is_silent(self) -> None:
        from dev10x.domain.session_rules import FrictionSetupNudgeRule, FrictionSetupState

        assert FrictionSetupNudgeRule(state=FrictionSetupState.MATCHED).apply() == ""

    def test_dispatch_returns_empty_without_toplevel(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from dev10x.hooks import session_dispatch

        monkeypatch.setattr(session_dispatch, "_get_toplevel", lambda: None)
        assert session_dispatch.build_friction_setup_context() == ""

    def test_seeds_strict_baseline_when_absent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from dev10x.domain.dev10x_paths import Dev10xConfigDir
        from dev10x.session.service import SessionService

        self._isolate_config(monkeypatch=monkeypatch, tmp_path=tmp_path)
        repo = tmp_path / "repo"
        repo.mkdir()
        try:
            text = SessionService().build_friction_setup_context(toplevel=str(repo))
            friction = Dev10xConfigDir.friction_yaml()
            assert friction.exists()
            assert "friction_level: strict" in friction.read_text()
            assert "/Dev10x:friction-setup" in text
        finally:
            Dev10xConfigDir.reset_cache()

    def test_unmatched_nudges_without_writing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from dev10x.session.service import SessionService

        cfg = self._isolate_config(monkeypatch=monkeypatch, tmp_path=tmp_path)
        cfg.mkdir(parents=True)
        friction = cfg / "friction.yaml"
        friction.write_text("defaults:\n  friction_level: guided\n")
        before = friction.read_text()
        repo = tmp_path / "repo"
        repo.mkdir()
        try:
            from dev10x.domain.dev10x_paths import Dev10xConfigDir

            text = SessionService().build_friction_setup_context(toplevel=str(repo))
            assert "/Dev10x:friction-setup" in text
            assert "repo" in text
            # Skip = no write: an unmatched project must not mutate friction.yaml.
            assert friction.read_text() == before
        finally:
            Dev10xConfigDir.reset_cache()

    def test_matched_is_silent(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import os

        from dev10x.domain.dev10x_paths import Dev10xConfigDir
        from dev10x.session.service import SessionService

        cfg = self._isolate_config(monkeypatch=monkeypatch, tmp_path=tmp_path)
        cfg.mkdir(parents=True)
        repo = tmp_path / "repo"
        repo.mkdir()
        target = os.path.realpath(str(repo))
        (cfg / "friction.yaml").write_text(
            "defaults:\n  friction_level: guided\n"
            "projects:\n"
            f"  - match: ['{target}']\n"
            "    gate_preset: strict\n"
        )
        try:
            assert SessionService().build_friction_setup_context(toplevel=str(repo)) == ""
        finally:
            Dev10xConfigDir.reset_cache()

    def test_legacy_config_yaml_is_silent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A repo with a legacy .claude/Dev10x/config.yaml is configured (the
        # resolver honors it above friction.yaml defaults), so it must NOT be
        # nudged as unconfigured (GH-886 one-layer-down guard).
        from dev10x.domain.dev10x_paths import Dev10xConfigDir
        from dev10x.session.service import SessionService

        cfg = self._isolate_config(monkeypatch=monkeypatch, tmp_path=tmp_path)
        cfg.mkdir(parents=True)
        (cfg / "friction.yaml").write_text("defaults:\n  friction_level: guided\n")
        repo = tmp_path / "repo"
        (repo / ".claude" / "Dev10x").mkdir(parents=True)
        (repo / ".claude" / "Dev10x" / "config.yaml").write_text(
            "friction_level: adaptive\nactive_modes: [solo-maintainer]\n"
        )
        try:
            assert SessionService().build_friction_setup_context(toplevel=str(repo)) == ""
        finally:
            Dev10xConfigDir.reset_cache()

    def test_seed_failure_still_nudges(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A failing seed write must not degrade to a silent "" (GH-886 failure
        # mode, one layer down) — the supervisor still gets the nudge.
        from dev10x.domain.documents import session_yaml
        from dev10x.session.service import SessionService

        self._isolate_config(monkeypatch=monkeypatch, tmp_path=tmp_path)
        repo = tmp_path / "repo"
        repo.mkdir()

        def _boom(*, path: Path | None = None) -> bool:
            raise OSError("disk full")

        monkeypatch.setattr(session_yaml, "seed_strict_baseline_if_absent", _boom)
        try:
            text = SessionService().build_friction_setup_context(toplevel=str(repo))
            assert "/Dev10x:friction-setup" in text
        finally:
            from dev10x.domain.dev10x_paths import Dev10xConfigDir

            Dev10xConfigDir.reset_cache()

    def test_facade_reexports_dispatch(self) -> None:
        from dev10x.hooks import session

        assert hasattr(session, "build_friction_setup_context")


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


class TestSessionLoadMarker:
    """GH-874: SessionStart writes a per-session plugin-load marker so a
    userspace guard can detect a silently-skipped plugin."""

    def test_feature_writes_marker(self) -> None:
        from dev10x.hooks.session_place import session_load_marker

        session_id = f"gh874-{uuid.uuid4()}"
        marker = Path("/tmp/Dev10x/sessions") / session_id
        try:
            session_load_marker(data={"session_id": session_id})
            assert marker.exists()
        finally:
            marker.unlink(missing_ok=True)

    def test_feature_noop_without_session_id(self) -> None:
        from dev10x.hooks.session_place import session_load_marker

        # Empty session_id must return without raising and without
        # creating a named marker file.
        assert session_load_marker(data={"session_id": ""}) is None

    def test_feature_reads_stdin_when_no_data(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from dev10x.hooks.session_place import session_load_marker

        session_id = f"gh874-stdin-{uuid.uuid4()}"
        marker = Path("/tmp/Dev10x/sessions") / session_id
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"session_id": session_id})))
        try:
            session_load_marker()
            assert marker.exists()
        finally:
            marker.unlink(missing_ok=True)

    def test_feature_exits_on_invalid_stdin(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from dev10x.hooks.session_place import session_load_marker

        monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
        with pytest.raises(SystemExit):
            session_load_marker()

    def test_facade_reexports_marker(self) -> None:
        from dev10x.hooks import session

        assert hasattr(session, "session_load_marker")

    def test_orchestrator_writes_marker(self) -> None:
        session_id = f"gh874-orch-{uuid.uuid4()}"
        marker = Path("/tmp/Dev10x/sessions") / session_id
        try:
            result = _run(SESSION_START, {"session_id": session_id})
            assert result.returncode == 0
            assert marker.exists()
        finally:
            marker.unlink(missing_ok=True)


class TestPluginLoadGuard:
    """GH-874: the userspace guard warns only when the plugin's marker is
    absent though the marker directory exists — silent otherwise."""

    def _run_guard(
        self,
        *,
        payload: dict,
        marker_dir: Path,
        home: Path,
        grace: str = "0",
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["sh", str(PLUGIN_LOAD_GUARD)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=30,
            env={
                "PATH": "/usr/bin:/bin:/usr/local/bin",
                "HOME": str(home),
                "DEV10X_PLUGIN_LOAD_GUARD_DIR": str(marker_dir),
                "DEV10X_PLUGIN_LOAD_GUARD_GRACE": grace,
            },
        )

    def test_silent_when_marker_present(self, tmp_path: Path) -> None:
        marker_dir = tmp_path / "sessions"
        marker_dir.mkdir()
        (marker_dir / "s-1").touch()
        result = self._run_guard(
            payload={"session_id": "s-1"}, marker_dir=marker_dir, home=tmp_path
        )
        assert result.returncode == 0
        assert result.stdout.strip() == ""

    def test_warns_when_marker_absent_but_dir_exists(self, tmp_path: Path) -> None:
        marker_dir = tmp_path / "sessions"
        marker_dir.mkdir()  # dir exists, but no marker for this session
        result = self._run_guard(
            payload={"session_id": "s-2"}, marker_dir=marker_dir, home=tmp_path
        )
        assert result.returncode == 0
        obj = json.loads(result.stdout)
        assert obj["hookSpecificOutput"]["hookEventName"] == "SessionStart"
        assert "/plugin reload" in obj["hookSpecificOutput"]["additionalContext"]

    def test_silent_when_marker_dir_missing(self, tmp_path: Path) -> None:
        marker_dir = tmp_path / "does-not-exist"
        result = self._run_guard(
            payload={"session_id": "s-3"}, marker_dir=marker_dir, home=tmp_path
        )
        assert result.returncode == 0
        assert result.stdout.strip() == ""

    def test_silent_without_session_id(self, tmp_path: Path) -> None:
        marker_dir = tmp_path / "sessions"
        marker_dir.mkdir()
        result = self._run_guard(payload={}, marker_dir=marker_dir, home=tmp_path)
        assert result.returncode == 0
        assert result.stdout.strip() == ""

    def test_silent_when_plugin_disabled(self, tmp_path: Path) -> None:
        marker_dir = tmp_path / "sessions"
        marker_dir.mkdir()  # dir exists, marker absent — would warn if enabled
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "settings.json").write_text(
            json.dumps({"enabledPlugins": {"Dev10x@Dev10x-Guru": False}})
        )
        result = self._run_guard(
            payload={"session_id": "s-4"}, marker_dir=marker_dir, home=tmp_path
        )
        assert result.returncode == 0
        assert result.stdout.strip() == ""
