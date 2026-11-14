"""`dev10x permission remove` drops rules by glob, guarded and backed up (GH-1925)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner, Result
from dev10x.domain.claude_paths import CLAUDE_HOME_ENV_VAR

from dev10x.commands.permission import remove
from dev10x.skills.permission import backup, remove_rules

PERMISSIONS = {
    "allow": ["Read(a/Dev10x/**)", "Bash(git log:*)", "Read(b/Dev10x/**)"],
    "ask": ["Read(c/Dev10x/**)", "Bash(rm:*)"],
    "deny": ["Read(d/Dev10x/**)"],
}


@pytest.fixture
def claude_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / ".claude"
    home.mkdir()
    monkeypatch.setenv(CLAUDE_HOME_ENV_VAR, str(home))
    return home


@pytest.fixture
def project_settings(tmp_path: Path) -> Path:
    path = tmp_path / "proj" / ".claude" / "settings.local.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"model": "x", "permissions": PERMISSIONS}))
    return path


@pytest.fixture
def global_settings(claude_home: Path) -> Path:
    path = claude_home / "settings.json"
    path.write_text(json.dumps({"permissions": PERMISSIONS}))
    return path


@pytest.fixture
def tracked_paths() -> set[Path]:
    return set()


@pytest.fixture
def settings_files() -> list[Path]:
    return []


@pytest.fixture
def env(
    settings_files: list[Path],
    tracked_paths: set[Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Context:
        pass

    context = Context()
    context.settings_files = settings_files
    monkeypatch.setattr("dev10x.commands.permission._require_context", lambda **_kw: context)
    monkeypatch.setattr(
        "dev10x.skills.permission.catalog_write._is_git_tracked",
        lambda path: path in tracked_paths,
    )


@pytest.fixture
def args() -> list[str]:
    return ["--pattern", "Read(*Dev10x/**)"]


@pytest.fixture
def run(env: None, args: list[str]) -> Result:
    return CliRunner().invoke(remove, args)


def read_permissions(path: Path) -> dict[str, list[str]]:
    return json.loads(path.read_text())["permissions"]


class TestRemoveFromProject:
    @pytest.fixture
    def settings_files(self, project_settings: Path) -> list[Path]:
        return [project_settings]

    def test_removes_matching_rules_from_every_list(
        self, run: Result, project_settings: Path
    ) -> None:
        assert read_permissions(project_settings) == {
            "allow": ["Bash(git log:*)"],
            "ask": ["Bash(rm:*)"],
            "deny": [],
        }

    def test_reports_the_total(self, run: Result) -> None:
        assert "Removed 4 rules matching 'Read(*Dev10x/**)'." in run.output

    def test_keeps_unrelated_keys(self, run: Result, project_settings: Path) -> None:
        assert json.loads(project_settings.read_text())["model"] == "x"

    def test_leaves_a_backup_with_the_original_rules(
        self, run: Result, project_settings: Path
    ) -> None:
        original = json.loads(backup.find_latest_backup(project_settings).read_text())
        assert original["permissions"] == PERMISSIONS


class TestRemoveDryRun:
    @pytest.fixture
    def settings_files(self, project_settings: Path) -> list[Path]:
        return [project_settings]

    @pytest.fixture
    def args(self) -> list[str]:
        return ["--pattern", "Read(*Dev10x/**)", "--dry-run"]

    def test_changes_nothing_and_makes_no_backup(
        self, run: Result, project_settings: Path
    ) -> None:
        assert read_permissions(project_settings) == PERMISSIONS
        assert backup.find_backups(project_settings) == []

    def test_says_what_it_would_do(self, run: Result) -> None:
        assert "would remove [allow] Read(a/Dev10x/**)" in run.output
        assert "Would remove 4 rules" in run.output


class TestRemoveSingleList:
    @pytest.fixture
    def settings_files(self, project_settings: Path) -> list[Path]:
        return [project_settings]

    @pytest.fixture
    def args(self) -> list[str]:
        return ["--pattern", "Read(*Dev10x/**)", "--list", "ask"]

    def test_touches_only_the_named_list(self, run: Result, project_settings: Path) -> None:
        assert read_permissions(project_settings) == {**PERMISSIONS, "ask": ["Bash(rm:*)"]}


class TestRemoveNoMatch:
    @pytest.fixture
    def settings_files(self, project_settings: Path) -> list[Path]:
        return [project_settings]

    @pytest.fixture
    def args(self) -> list[str]:
        return ["--pattern", "Nothing(*)"]

    def test_reports_zero_and_writes_nothing(self, run: Result, project_settings: Path) -> None:
        assert "Removed 0 rules" in run.output
        assert backup.find_backups(project_settings) == []


class TestRemoveTrackedGuard:
    @pytest.fixture
    def settings_files(self, project_settings: Path) -> list[Path]:
        return [project_settings]

    @pytest.fixture
    def tracked_paths(self, project_settings: Path) -> set[Path]:
        return {project_settings}

    def test_skips_a_git_tracked_file(self, run: Result, project_settings: Path) -> None:
        assert f"SKIP (git-tracked): {project_settings}" in run.output
        assert read_permissions(project_settings) == PERMISSIONS


class TestRemoveGlobal:
    @pytest.fixture
    def tracked_paths(self, global_settings: Path) -> set[Path]:
        return {global_settings}

    def test_leaves_the_user_file_without_the_flag(
        self, run: Result, global_settings: Path
    ) -> None:
        assert "No settings files found." in run.output
        assert read_permissions(global_settings) == PERMISSIONS

    def test_prunes_a_tracked_user_file_with_the_flag(
        self, env: None, global_settings: Path
    ) -> None:
        result = CliRunner().invoke(remove, ["--pattern", "Read(*Dev10x/**)", "--global"])

        assert result.exit_code == 0, result.output
        assert read_permissions(global_settings)["allow"] == ["Bash(git log:*)"]

    def test_ignores_a_missing_user_file(self, env: None, global_settings: Path) -> None:
        global_settings.unlink()

        result = CliRunner().invoke(remove, ["--pattern", "x", "--global"])

        assert "No settings files found." in result.output


class TestRemoveFromFile:
    def test_skips_invalid_json(self, tmp_path: Path) -> None:
        path = tmp_path / "settings.json"
        path.write_text("{not json")

        outcome = remove_rules.remove_from_file(path, pattern="*")

        assert outcome.skipped is not None
        assert remove_rules.format_removal(outcome, dry_run=False) == [f"  {outcome.skipped}"]

    def test_ignores_a_non_list_permission_entry(self, tmp_path: Path) -> None:
        path = tmp_path / "settings.json"
        path.write_text(json.dumps({"permissions": {"allow": "oops", "ask": [1, "Bash(x)"]}}))

        outcome = remove_rules.remove_from_file(path, pattern="Bash(*)")

        assert outcome.removed == {"ask": ["Bash(x)"]}
