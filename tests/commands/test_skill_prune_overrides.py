"""Tests for `dev10x skill prune-overrides` (GH-1627)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner, Result
from dev10x.domain.dev10x_paths import Dev10xConfigDir

from dev10x.commands.skill import prune_overrides


@pytest.fixture(autouse=True)
def _isolated_config_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DEV10X_CONFIG_HOME", str(tmp_path / "config"))
    Dev10xConfigDir.reset_cache()


@pytest.fixture
def settings_path(tmp_path: Path) -> Path:
    path = tmp_path / "settings.local.json"
    path.write_text(
        json.dumps({"permissions": {"allow": []}, "skillOverrides": {"legacy": "off"}}),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def allowlist_path(tmp_path: Path) -> Path:
    path = tmp_path / "skill-prune.yaml"
    path.write_text("keep:\n  - deploy\n", encoding="utf-8")
    return path


def _invoke(*args: str) -> Result:
    return CliRunner().invoke(prune_overrides, list(args))


def _report(result: Result) -> dict:
    return json.loads(result.output)


def test_dry_run_prints_plan_and_writes_nothing(settings_path: Path, allowlist_path: Path) -> None:
    before = settings_path.read_text(encoding="utf-8")

    result = _invoke(
        "--settings", str(settings_path), "--allowlist", str(allowlist_path),
        "--set", "ios=off", "--set", "deploy=off",
    )  # fmt: skip

    assert result.exit_code == 0
    report = _report(result)
    assert [c["name"] for c in report["skill_changes"]] == ["ios"]
    assert report["kept_by_allowlist"] == ["deploy"]
    assert "written" not in report
    assert settings_path.read_text(encoding="utf-8") == before


def test_apply_merges_and_rerun_is_noop(settings_path: Path, allowlist_path: Path) -> None:
    args = ("--settings", str(settings_path), "--allowlist", str(allowlist_path))

    applied = _invoke(*args, "--set", "ios=off", "--disable-plugin", "svelte@m", "--apply")
    rerun = _invoke(*args, "--set", "ios=off", "--disable-plugin", "svelte@m", "--apply")

    data = json.loads(settings_path.read_text(encoding="utf-8"))
    assert _report(applied)["written"] == str(settings_path)
    assert data["skillOverrides"] == {"ios": "off", "legacy": "off"}
    assert data["enabledPlugins"] == {"svelte@m": False}
    assert data["permissions"] == {"allow": []}
    assert _report(rerun)["has_changes"] is False


def test_missing_settings_file_plans_from_empty(tmp_path: Path, allowlist_path: Path) -> None:
    result = _invoke(
        "--settings", str(tmp_path / "absent.json"), "--allowlist", str(allowlist_path),
        "--set", "ios=off", "--keep", "other",
    )  # fmt: skip

    assert _report(result)["skill_changes"] == [{"name": "ios", "before": None, "after": "off"}]


def test_missing_explicit_allowlist_is_a_json_error(settings_path: Path, tmp_path: Path) -> None:
    result = _invoke(
        "--settings", str(settings_path), "--allowlist", str(tmp_path / "none.yaml"),
        "--set", "deploy=off",
    )  # fmt: skip

    assert result.exit_code == 1
    assert "allowlist not found" in _report(result)["error"]


def test_missing_default_allowlist_keeps_nothing(settings_path: Path) -> None:
    result = _invoke("--settings", str(settings_path), "--set", "deploy=off")

    assert _report(result)["kept_by_allowlist"] == []


def test_non_object_settings_is_a_json_error(tmp_path: Path) -> None:
    path = tmp_path / "list.json"
    path.write_text("[]", encoding="utf-8")

    result = _invoke("--settings", str(path), "--set", "ios=off")

    assert result.exit_code == 1
    assert "must hold a JSON object" in _report(result)["error"]


def test_non_utf8_settings_is_a_json_error(tmp_path: Path) -> None:
    path = tmp_path / "binary.json"
    path.write_bytes(b"\xff\xfe")

    result = _invoke("--settings", str(path), "--set", "ios=off")

    assert result.exit_code == 1
    assert "cannot read" in _report(result)["error"]


def test_invalid_visibility_is_a_json_error(settings_path: Path) -> None:
    result = _invoke("--settings", str(settings_path), "--set", "ios=hidden")

    assert result.exit_code == 1
    assert "invalid --set" in _report(result)["error"]


def test_unreadable_settings_is_a_json_error(tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text("{", encoding="utf-8")

    result = _invoke("--settings", str(path), "--set", "ios=off")

    assert result.exit_code == 1
    assert "cannot read" in _report(result)["error"]


def test_malformed_allowlist_is_a_json_error(settings_path: Path, tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("keep: deploy\n", encoding="utf-8")

    result = _invoke(
        "--settings", str(settings_path), "--allowlist", str(path), "--set", "deploy=off"
    )

    assert result.exit_code == 1
    assert "must be a list of skill names" in _report(result)["error"]
