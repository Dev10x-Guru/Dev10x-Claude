"""CLI tests for ``dev10x playbook diff`` (GH-247 finding G8)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from dev10x.commands.playbook import playbook

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def plugin_root(tmp_path: Path) -> Path:
    """Create a minimal plugin root with a ``work-on`` default playbook."""
    skill_dir = tmp_path / "plugin" / "skills" / "work-on" / "references"
    skill_dir.mkdir(parents=True)
    default = {
        "version": "1.0.0",
        "defaults": {
            "feature": {
                "steps": [
                    {"subject": "New upstream step", "type": "detailed"},
                    {"subject": "Shared step", "type": "detailed", "prompt": "do it"},
                    {
                        "subject": "Changed step",
                        "type": "detailed",
                        "prompt": "updated prompt",
                    },
                ],
            },
        },
    }
    (skill_dir / "playbook.yaml").write_text(yaml.dump(default))
    return tmp_path / "plugin"


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    """Create a project directory with a ``work-on`` user override."""
    override_dir = tmp_path / "project" / ".claude" / "Dev10x" / "playbooks"
    override_dir.mkdir(parents=True)
    user = {
        "overrides": [
            {
                "play": "feature",
                "steps": [
                    # "New upstream step" is absent → will appear as (new)
                    {"subject": "Shared step", "type": "detailed", "prompt": "do it"},
                    {
                        "subject": "Changed step",
                        "type": "detailed",
                        # user has customized prompt → customized (preserved)
                        "prompt": "my custom prompt",
                    },
                    {"subject": "Removed user step", "type": "detailed"},
                ],
            }
        ]
    }
    (override_dir / "work-on.yaml").write_text(yaml.dump(user))
    return tmp_path / "project"


@pytest.fixture
def result(
    plugin_root: Path,
    project_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> object:
    """Invoke ``playbook diff`` via CliRunner with isolated fixtures."""
    monkeypatch.chdir(project_root)
    runner = CliRunner()
    return runner.invoke(
        playbook,
        ["diff", "--plugin-root", str(plugin_root)],
        catch_exceptions=False,
    )


# ── TestPlaybookDiffCli ───────────────────────────────────────────────────────


class TestPlaybookDiffCli:
    """``dev10x playbook diff`` surfaces New/Removed/Changed/Customized in output."""

    def test_exits_successfully(self, result: object) -> None:
        assert result.exit_code == 0

    def test_new_step_appears_in_output(self, result: object) -> None:
        assert "(new)" in result.output

    def test_removed_step_appears_in_output(self, result: object) -> None:
        assert "(removed)" in result.output

    def test_changed_step_appears_in_output(self, result: object) -> None:
        assert "(changed)" in result.output

    def test_customized_field_appears_in_output(self, result: object) -> None:
        assert "customized" in result.output

    def test_skill_key_appears_in_output(self, result: object) -> None:
        assert "work-on" in result.output

    def test_findings_summary_line_appears(self, result: object) -> None:
        assert "override(s) have upstream changes worth reviewing" in result.output


class TestPlaybookDiffCliNoOverrides:
    """``dev10x playbook diff`` handles the case where no overrides are found."""

    def test_prints_no_overrides_message(
        self,
        plugin_root: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        empty_project = tmp_path / "empty"
        empty_project.mkdir()
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.chdir(empty_project)
        monkeypatch.setenv("HOME", str(fake_home))
        runner = CliRunner()
        result = runner.invoke(
            playbook,
            ["diff", "--plugin-root", str(plugin_root)],
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        assert "No user playbook overrides found" in result.output


class TestPlaybookDiffCliSkillFilter:
    """``--skill`` flag limits the diff to the specified skill key."""

    def test_skill_filter_matches_override(
        self,
        plugin_root: Path,
        project_root: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(project_root)
        runner = CliRunner()
        result = runner.invoke(
            playbook,
            ["diff", "--plugin-root", str(plugin_root), "--skill", "work-on"],
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        assert "work-on" in result.output

    def test_skill_filter_misses_when_no_match(
        self,
        plugin_root: Path,
        project_root: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(project_root)
        runner = CliRunner()
        result = runner.invoke(
            playbook,
            ["diff", "--plugin-root", str(plugin_root), "--skill", "nonexistent-skill"],
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        assert "No user override found for skill" in result.output
