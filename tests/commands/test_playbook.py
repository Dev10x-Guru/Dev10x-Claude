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


class TestPlaybookDiffCliProjectsList:
    """GH-1375: an override addressed at another repo must not diff clean.

    ``playbook diff`` located override *files* by path and never read the
    ``projects:`` list inside them, so a block selecting nothing was
    reported as up to date while applying to nothing.
    """

    @staticmethod
    def _run_with(
        *,
        projects: list,
        address,
        plugin_root: Path,
        project_root: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> object:
        override = project_root / ".claude" / "Dev10x" / "playbooks" / "work-on.yaml"
        document = yaml.safe_load(override.read_text())
        document["projects"] = projects
        override.write_text(yaml.dump(document))
        monkeypatch.chdir(project_root)
        monkeypatch.setattr(
            "dev10x.session.repo_address.resolve_name_with_owner",
            lambda **_: address,
        )
        return CliRunner().invoke(
            playbook,
            ["diff", "--plugin-root", str(plugin_root)],
            catch_exceptions=False,
        )

    def test_matching_list_is_confirmed(
        self, plugin_root: Path, project_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from dev10x.domain.common.result import ok

        result = self._run_with(
            projects=[{"match_repo": ["org/*"]}],
            address=ok("org/repo"),
            plugin_root=plugin_root,
            project_root=project_root,
            monkeypatch=monkeypatch,
        )
        assert "`projects:` entry 0 selects `org/repo`" in result.output

    def test_non_matching_list_is_reported(
        self, plugin_root: Path, project_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from dev10x.domain.common.result import ok

        result = self._run_with(
            projects=[{"match_repo": ["other/*"]}],
            address=ok("org/repo"),
            plugin_root=plugin_root,
            project_root=project_root,
            monkeypatch=monkeypatch,
        )
        assert "`projects:` list needs attention" in result.output
        assert "no `match_repo:` glob matched 'org/repo'" in result.output

    def test_retired_match_key_no_longer_selects_and_is_reported(
        self, plugin_root: Path, project_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from dev10x.domain.common.result import ok

        result = self._run_with(
            projects=[{"match": ["org/*"]}],
            address=ok("org/repo"),
            plugin_root=plugin_root,
            project_root=project_root,
            monkeypatch=monkeypatch,
        )
        assert "no `match_repo:` glob matched 'org/repo'" in result.output
        assert "`match:` is no longer read in this file" in result.output

    def test_unresolved_repo_is_not_reported_as_no_match(
        self, plugin_root: Path, project_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from dev10x.domain.common.result import err

        result = self._run_with(
            projects=[{"match_repo": ["org/*"]}],
            address=err("no `origin` remote"),
            plugin_root=plugin_root,
            project_root=project_root,
            monkeypatch=monkeypatch,
        )
        assert "NOT evaluated — no `origin` remote" in result.output
        assert "glob matched" not in result.output

    def test_override_without_a_projects_list_is_silent(self, result: object) -> None:
        assert "`projects:`" not in result.output


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


class TestPlaybookDiffCliSharedDefault:
    """GH-1555: a split shared default is diffed as its merged whole."""

    @pytest.fixture
    def split_root(self, tmp_path: Path) -> Path:
        root = tmp_path / "split"
        core = root / "skills" / "playbook" / "references"
        core.mkdir(parents=True)
        (core / "playbook.yaml").write_text("version: '2.0.0'\noverrides: []\n")
        fragment = root / "skills" / "work-on" / "references" / "playbook.d"
        fragment.mkdir(parents=True)
        (fragment / "coding.yaml").write_text(
            "defaults:\n  feature:\n    steps:\n"
            "    - {subject: New upstream step, type: detailed}\n"
            "    - {subject: Shared step, type: detailed, prompt: do it}\n"
        )
        return root

    def _invoke(self, *, root: Path, project_root: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.chdir(project_root)
        return CliRunner().invoke(playbook, ["diff", "--plugin-root", str(root)])

    def test_fragment_steps_reach_the_diff(
        self, split_root: Path, project_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result = self._invoke(root=split_root, project_root=project_root, monkeypatch=monkeypatch)

        assert "New upstream step" in result.output

    def test_malformed_fragment_fails_loudly(
        self, split_root: Path, project_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bad = split_root / "skills" / "work-on" / "references" / "playbook.d" / "coding.yaml"
        bad.write_text("- not a mapping\n")

        result = self._invoke(root=split_root, project_root=project_root, monkeypatch=monkeypatch)

        assert result.exit_code == 1
        assert "a fragment must be a YAML mapping" in result.output
