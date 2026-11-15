"""GH-1571: the doctor flags a satellite enabled without its dependencies."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dev10x.core.plugin_map import PluginMap, load_plugin_map
from dev10x.core.skills.doctor.registry import load_strategies
from dev10x.core.skills.doctor.strategies.satellite_dependencies import (
    STRATEGY,
    detect,
    detect_with_map,
)
from dev10x.core.skills.doctor.strategy import Context, Finding

PLUGIN_MAP = PluginMap(
    plugins={"core": ("afk",), "tasks": ("park",), "coding": ("work-on",), "qa": ("tts",)},
    plugin_names={
        "core": "dev10x",
        "tasks": "dev10x-tasks",
        "coding": "dev10x-coding",
        "qa": "dev10x-qa",
    },
    marketplace="Dev10x-Guru",
    extracted=("tasks", "coding", "qa"),
    dependencies={"coding": ("tasks",)},
)


@pytest.fixture
def user_settings(tmp_path: Path) -> Path:
    return tmp_path / "user" / "settings.json"


@pytest.fixture
def project_settings(tmp_path: Path) -> Path:
    return tmp_path / "project" / ".claude" / "settings.local.json"


def _write(*, path: Path, plugins: dict[str, bool]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"enabledPlugins": plugins}))
    return path


def _detect(*paths: Path) -> list[Finding]:
    return detect_with_map(Context(settings_paths=paths), plugin_map=PLUGIN_MAP)


class TestClean:
    def test_satellite_with_core_enabled_is_clean(self, user_settings: Path) -> None:
        _write(
            path=user_settings,
            plugins={"dev10x@Dev10x-Guru": True, "dev10x-qa@Dev10x-Guru": True},
        )

        assert _detect(user_settings) == []

    def test_legacy_core_id_counts_as_core(self, user_settings: Path) -> None:
        _write(
            path=user_settings,
            plugins={"Dev10x@Dev10x-Guru": True, "dev10x-qa@Dev10x-Guru": True},
        )

        assert _detect(user_settings) == []

    def test_disabled_satellite_is_ignored(self, user_settings: Path) -> None:
        _write(
            path=user_settings,
            plugins={"dev10x@Dev10x-Guru": False, "dev10x-qa@Dev10x-Guru": False},
        )

        assert _detect(user_settings) == []

    @pytest.mark.parametrize("body", ["{not json", "[1, 2]", '{"enabledPlugins": []}'])
    def test_unreadable_files_are_skipped(self, user_settings: Path, body: str) -> None:
        user_settings.parent.mkdir(parents=True)
        user_settings.write_text(body)

        assert _detect(user_settings) == []

    def test_missing_file_is_skipped(self, user_settings: Path) -> None:
        assert _detect(user_settings) == []


class TestDisabledDependency:
    @pytest.fixture
    def findings(self, user_settings: Path, project_settings: Path) -> list[Finding]:
        _write(
            path=user_settings,
            plugins={"dev10x@Dev10x-Guru": True, "dev10x-qa@Dev10x-Guru": True},
        )
        _write(path=project_settings, plugins={"dev10x@Dev10x-Guru": False})
        return _detect(user_settings, project_settings)

    def test_one_finding(self, findings: list[Finding]) -> None:
        assert len(findings) == 1

    def test_is_drift(self, findings: list[Finding]) -> None:
        assert findings[0].severity == "drift"

    def test_points_at_the_file_that_disabled_it(
        self, findings: list[Finding], project_settings: Path
    ) -> None:
        assert findings[0].location == f"{project_settings}:enabledPlugins"

    def test_remediation_enables_the_dependency(
        self, findings: list[Finding], project_settings: Path
    ) -> None:
        remediation = STRATEGY.remediate(findings[0])

        assert remediation.kind == "edit_settings"
        assert remediation.target == str(project_settings)
        assert remediation.action == {
            "bucket": "enabledPlugins",
            "set": {"dev10x@Dev10x-Guru": True},
            "required_by": "dev10x-qa@Dev10x-Guru",
        }


class TestAbsentDependency:
    def test_absent_core_is_a_suggestion(self, user_settings: Path) -> None:
        _write(path=user_settings, plugins={"dev10x-qa@Dev10x-Guru": True})

        findings = _detect(user_settings)

        assert [finding.severity for finding in findings] == ["suggestion"]
        assert "not enabled in any settings file" in findings[0].evidence

    def test_hard_dependency_is_checked_too(self, user_settings: Path) -> None:
        _write(
            path=user_settings,
            plugins={"dev10x@Dev10x-Guru": True, "dev10x-coding@Dev10x-Guru": True},
        )

        findings = _detect(user_settings)

        assert [finding.data.dependency_id for finding in findings] == [  # type: ignore[union-attr]
            "dev10x-tasks@Dev10x-Guru"
        ]


class TestShippedMap:
    def test_every_extracted_satellite_depends_on_core(self) -> None:
        plugin_map = load_plugin_map()

        assert plugin_map.extracted
        for key in plugin_map.extracted:
            assert plugin_map.manifest_dependencies(key=key)[0] == "dev10x"

    def test_detect_reads_the_shipped_map(self, user_settings: Path) -> None:
        _write(path=user_settings, plugins={"dev10x-qa@Dev10x-Guru": True})

        findings = detect(Context(settings_paths=(user_settings,)))

        assert [finding.severity for finding in findings] == ["suggestion"]


class TestRegistration:
    def test_the_doctor_loads_it_by_default(self) -> None:
        assert "satellite-dependencies" in [strategy.id for strategy in load_strategies()]
