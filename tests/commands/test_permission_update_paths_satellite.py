"""`update-paths` moves extracted skills' rules to their satellite (GH-1793)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner, Result
from dev10x.domain.common.result import ok

from dev10x.commands.permission import update_paths
from dev10x.core.plugin_map import parse_plugin_map
from dev10x.core.skills.permission.satellite_paths import SatelliteRelocator


@pytest.fixture
def cache(tmp_path: Path) -> Path:
    core = tmp_path / ".claude" / "plugins" / "cache" / "Dev10x-Guru" / "dev10x"
    (core / "0.114.0").mkdir(parents=True)
    return core


@pytest.fixture
def core_rule(cache: Path) -> str:
    return f"Bash({cache}/0.114.0/skills/k8s/scripts/k8s.sh:*)"


@pytest.fixture
def satellite_rule(cache: Path) -> str:
    return f"Bash({cache.parent}/dev10x-infra/0.114.0/skills/k8s/scripts/k8s.sh:*)"


@pytest.fixture
def rules(core_rule: str) -> list[str]:
    return [core_rule]


@pytest.fixture
def settings_content(rules: list[str]) -> str:
    return json.dumps({"permissions": {"allow": rules}})


@pytest.fixture
def user_settings(
    tmp_path: Path,
    cache: Path,
    settings_content: str,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    config_path = tmp_path / "projects.yaml"
    config_path.write_text(
        f"plugin_cache: {cache}\nroots: []\ninclude_user_settings: true\nbase_permissions: []\n"
    )
    settings = tmp_path / ".claude" / "settings.local.json"
    settings.write_text(settings_content)
    plugin_map = parse_plugin_map(
        data={
            "marketplace": "Dev10x-Guru",
            "extracted": ["infra"],
            "plugin_names": {"infra": "dev10x-infra"},
            "plugins": {"infra": ["k8s"]},
        }
    )
    monkeypatch.setattr(
        "dev10x.core.skills.permission.satellite_paths.default_relocator",
        lambda: SatelliteRelocator(plugin_map=plugin_map),
    )
    monkeypatch.setattr(
        "dev10x.skills.permission.catalog_write.Path.home",
        classmethod(lambda cls: tmp_path),
    )
    monkeypatch.setattr(
        "dev10x.skills.permission.update_paths.find_config", lambda: ok(config_path)
    )
    monkeypatch.setattr(
        "dev10x.skills.permission.update_paths.detect_latest_version", lambda _cache: "0.114.0"
    )
    monkeypatch.setattr(
        "dev10x.skills.permission.update_paths.find_settings_files", lambda **_kw: [settings]
    )
    return settings


@pytest.fixture
def cli_args() -> list[str]:
    return []


@pytest.fixture
def run(user_settings: Path, cli_args: list[str]) -> Result:
    return CliRunner().invoke(update_paths, cli_args)


class TestUpdatePathsMovesSatelliteRules:
    def test_rewrites_the_rule_into_the_satellite_dir(
        self,
        run: Result,
        user_settings: Path,
        satellite_rule: str,
    ) -> None:
        assert run.exit_code == 0
        assert json.loads(user_settings.read_text())["permissions"] == {"allow": [satellite_rule]}

    def test_reports_the_move_and_the_total(self, run: Result, satellite_rule: str) -> None:
        assert f"→ {satellite_rule}" in run.output
        assert "Moved 1 rule(s)" in run.output

    @pytest.mark.usefixtures("run")
    def test_second_run_reports_nothing_to_do(self) -> None:
        assert "All files already up to date." in CliRunner().invoke(update_paths, []).output


class TestUpdatePathsSummary:
    @pytest.fixture
    def cli_args(self) -> list[str]:
        return ["--summary"]

    def test_prints_one_line_per_file(self, run: Result, user_settings: Path) -> None:
        assert f"{user_settings}: moved 1 rule(s) to a satellite plugin" in run.output


class TestUpdatePathsDryRun:
    @pytest.fixture
    def cli_args(self) -> list[str]:
        return ["--dry-run", "--summary"]

    def test_says_would_move_and_leaves_the_file_alone(
        self,
        run: Result,
        user_settings: Path,
        settings_content: str,
    ) -> None:
        assert f"{user_settings}: would move 1 rule(s)" in run.output
        assert "Would move 1 rule(s)" in run.output
        assert user_settings.read_text() == settings_content


class TestUpdatePathsQuiet:
    @pytest.fixture
    def cli_args(self) -> list[str]:
        return ["--quiet"]

    def test_moves_without_listing_rules(
        self,
        run: Result,
        user_settings: Path,
        satellite_rule: str,
    ) -> None:
        assert "→" not in run.output
        assert json.loads(user_settings.read_text())["permissions"]["allow"] == [satellite_rule]


class TestUpdatePathsWithVersionBump:
    @pytest.fixture
    def rules(self, core_rule: str, cache: Path) -> list[str]:
        return [core_rule, f"Bash({cache}/0.100.0/skills/git/scripts/git.sh:*)"]

    def test_prints_the_file_header_once(self, run: Result, user_settings: Path) -> None:
        assert run.output.count(f"\n{user_settings}\n") == 1


class TestUpdatePathsUnusableFile:
    @pytest.fixture
    def settings_content(self) -> str:
        return "[]"

    def test_shows_the_skip_message(self, run: Result) -> None:
        assert "SKIP (unexpected structure)" in run.output
