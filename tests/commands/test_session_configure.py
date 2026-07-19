"""Tests for `dev10x session set-friction` / `set-playbook` (GH-886).

These are the persistence writers the ``Dev10x:friction-setup`` skill invokes
on genuine completion of the guided walk. Both write only to the global
``~/.config/Dev10x`` tree (isolated to a tmp home by the autouse conftest
fixture), never under a repo's ``.claude/`` — so no self-settings gate fires.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from click.testing import CliRunner

from dev10x.commands.session import session
from dev10x.domain.dev10x_paths import Dev10xConfigDir
from dev10x.domain.documents.session_yaml import (
    FRICTION_SETUP_SKIP_MODE,
    FrictionYamlDocument,
)


class TestSetFriction:
    """Gate axis: upsert a projects[] entry into the global friction.yaml."""

    def test_writes_preset_overlays_and_overrides(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        result = CliRunner().invoke(
            session,
            [
                "set-friction",
                "--path",
                str(repo),
                "--preset",
                "adaptive",
                "--overlay",
                "solo-maintainer",
                "--gate-override",
                "merge=ask",
            ],
        )
        assert result.exit_code == 0
        matched = FrictionYamlDocument(toplevel=str(repo.resolve())).matched()
        assert matched == {
            "gate_preset": "adaptive",
            "gate_overlays": ["solo-maintainer"],
            "gate_overrides": {"merge": "ask"},
        }

    def test_omits_empty_axes(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        CliRunner().invoke(session, ["set-friction", "--path", str(repo), "--preset", "strict"])
        matched = FrictionYamlDocument(toplevel=str(repo.resolve())).matched()
        assert matched == {"gate_preset": "strict"}

    def test_idempotent_replaces_entry(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        runner = CliRunner()
        runner.invoke(session, ["set-friction", "--path", str(repo), "--preset", "strict"])
        runner.invoke(session, ["set-friction", "--path", str(repo), "--preset", "adaptive"])
        doc = yaml.safe_load(Dev10xConfigDir.friction_yaml().read_text())
        assert len(doc["projects"]) == 1
        assert doc["projects"][0]["gate_preset"] == "adaptive"

    def test_rejects_malformed_gate_override(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        result = CliRunner().invoke(
            session,
            ["set-friction", "--path", str(repo), "--preset", "strict", "--gate-override", "oops"],
        )
        assert result.exit_code != 0

    def test_rejects_unknown_gate_name(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        result = CliRunner().invoke(
            session,
            [
                "set-friction",
                "--path",
                str(repo),
                "--preset",
                "strict",
                "--gate-override",
                "marge=ask",
            ],
        )
        assert result.exit_code != 0
        assert not Dev10xConfigDir.friction_yaml().exists()

    def test_rejects_invalid_gate_value(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        result = CliRunner().invoke(
            session,
            [
                "set-friction",
                "--path",
                str(repo),
                "--preset",
                "strict",
                "--gate-override",
                "merge=nope",
            ],
        )
        assert result.exit_code != 0


class TestSetPlaybook:
    """Playbook axis: write active_modes / step skips to playbooks/<skill>.yaml."""

    def _playbook(self, skill: str = "work-on") -> Path:
        return Dev10xConfigDir.home() / "playbooks" / f"{skill}.yaml"

    def test_writes_active_modes(self) -> None:
        result = CliRunner().invoke(
            session, ["set-playbook", "--skill", "work-on", "--mode", "solo-maintainer"]
        )
        assert result.exit_code == 0
        doc = yaml.safe_load(self._playbook().read_text())
        assert doc["active_modes"] == ["solo-maintainer"]

    def test_skip_step_records_extension_and_synthetic_mode(self) -> None:
        CliRunner().invoke(
            session, ["set-playbook", "--skill", "work-on", "--skip-step", "Draft Job Story"]
        )
        doc = yaml.safe_load(self._playbook().read_text())
        assert FRICTION_SETUP_SKIP_MODE in doc["active_modes"]
        assert doc["mode_extensions"][FRICTION_SETUP_SKIP_MODE]["steps"]["Draft Job Story"] == {
            "skip": True
        }

    def test_rejects_path_traversal_skill_name(self, tmp_path: Path) -> None:
        outside = tmp_path / "evil.yaml"
        result = CliRunner().invoke(
            session, ["set-playbook", "--skill", "../../evil", "--mode", "solo-maintainer"]
        )
        assert result.exit_code != 0
        assert not outside.exists()

    def test_writes_under_config_home_not_repo(self, tmp_path: Path) -> None:
        CliRunner().invoke(session, ["set-playbook", "--mode", "solo-maintainer"])
        written = self._playbook()
        assert written.exists()
        # Global config home, never under a repo's .claude/.
        assert os.environ["DEV10X_CONFIG_HOME"] in str(written)
