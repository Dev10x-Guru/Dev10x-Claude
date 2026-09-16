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


class TestPlaybookDiffCliSkippedReporting:
    """GH-1329: a skipped override must never be reported as "up to date".

    ``plugin_default_path`` can still fail to resolve a default (e.g. an
    incomplete plugin root missing even the shared ``skills/playbook``
    fallback) — when that happens the diff must say so distinctly instead
    of folding the skip into a false "up to date" summary.
    """

    def test_all_overrides_skipped_reports_unchecked_not_up_to_date(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Plugin root with no default anywhere for this skill (no dedicated,
        # no shared skills/playbook/references/playbook.yaml either).
        plugin_root = tmp_path / "plugin"
        (plugin_root / "skills").mkdir(parents=True)
        project_root = tmp_path / "project"
        override_dir = project_root / ".claude" / "Dev10x" / "playbooks"
        override_dir.mkdir(parents=True)
        (override_dir / "ghost-skill.yaml").write_text(yaml.dump({"overrides": []}))
        monkeypatch.chdir(project_root)

        runner = CliRunner()
        result = runner.invoke(
            playbook,
            ["diff", "--plugin-root", str(plugin_root)],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert "1 override(s) skipped" in result.output
        assert "unchecked" in result.output
        assert "up to date" not in result.output

    def test_mixed_checked_and_skipped_reports_both(
        self,
        plugin_root: Path,
        project_root: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # project_root already has a work-on override with findings (from the
        # shared fixtures); add a second override with no matching default.
        override_dir = project_root / ".claude" / "Dev10x" / "playbooks"
        (override_dir / "ghost-skill.yaml").write_text(yaml.dump({"overrides": []}))
        monkeypatch.chdir(project_root)

        runner = CliRunner()
        result = runner.invoke(
            playbook,
            ["diff", "--plugin-root", str(plugin_root)],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert "override(s) have upstream changes worth reviewing" in result.output
        assert "skipped" in result.output
        assert "ghost-skill" in result.output

    def test_mixed_up_to_date_and_skipped_reports_both(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        plugin_root = tmp_path / "plugin"
        default_dir = plugin_root / "skills" / "clean-skill" / "references"
        default_dir.mkdir(parents=True)
        default_doc = {"defaults": {"feature": {"steps": [{"subject": "Step", "type": "x"}]}}}
        (default_dir / "playbook.yaml").write_text(yaml.dump(default_doc))

        project_root = tmp_path / "project"
        override_dir = project_root / ".claude" / "Dev10x" / "playbooks"
        override_dir.mkdir(parents=True)
        user_doc = {
            "overrides": [
                {"play": "feature", "steps": [{"subject": "Step", "type": "x"}]},
            ]
        }
        (override_dir / "clean-skill.yaml").write_text(yaml.dump(user_doc))
        (override_dir / "ghost-skill.yaml").write_text(yaml.dump({"overrides": []}))
        monkeypatch.chdir(project_root)

        runner = CliRunner()
        result = runner.invoke(
            playbook,
            ["diff", "--plugin-root", str(plugin_root)],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert "up to date" in result.output
        assert "skipped" in result.output
        assert "ghost-skill" in result.output


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
