"""disableAutoMode / disableBypassPermissionsMode as a floor (GH-1320).

Covers the write-time validator (boolean rejected, literal "disable"
accepted), the additive seeder, the doctor check, and the two writer
entry points (`write_safety_keys_to_file`, `ensure_safety_keys`).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dev10x.domain.common.result import ErrorResult, SuccessResult
from dev10x.skills.permission import safety_keys as mod
from dev10x.skills.permission import update_paths


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every settings file in these tests is untracked (GH-1155 guard is
    covered separately in TestEnsureSafetyKeysGitTrackedGuard)."""
    monkeypatch.setattr(update_paths, "_is_git_tracked", lambda _path: False)


class TestValidateSafetyKeyValue:
    def test_accepts_the_literal_string(self) -> None:
        result = mod.validate_safety_key_value("disableAutoMode", "disable")

        assert isinstance(result, SuccessResult)
        assert result.value == "disable"

    @pytest.mark.parametrize(
        "value",
        [True, False, "true", "True", 1, 0, None, "Disable", "disabled"],
    )
    def test_rejects_anything_else(self, value: object) -> None:
        result = mod.validate_safety_key_value("disableAutoMode", value)

        assert isinstance(result, ErrorResult)
        assert "disableAutoMode" in result.error
        assert repr(value) in result.error

    def test_boolean_true_is_named_as_the_documented_failure_mode(self) -> None:
        """The whole defect class: `true` reads as configured but is inert."""
        result = mod.validate_safety_key_value("disableBypassPermissionsMode", True)

        assert isinstance(result, ErrorResult)
        assert "silently ignored" in result.error

    def test_rejects_an_unrecognized_key(self) -> None:
        result = mod.validate_safety_key_value("disableSomethingElse", "disable")

        assert isinstance(result, ErrorResult)
        assert "not a recognized safety key" in result.error

    @pytest.mark.parametrize("key", mod.SAFETY_KEYS)
    def test_both_keys_are_recognized(self, key: str) -> None:
        assert isinstance(mod.validate_safety_key_value(key, "disable"), SuccessResult)


class TestCheckSafetyKeys:
    def test_both_missing(self) -> None:
        findings = mod.check_safety_keys({})

        assert {f.key for f in findings} == set(mod.SAFETY_KEYS)
        assert all(f.issue == "missing" for f in findings)

    def test_both_valid_reports_nothing(self) -> None:
        settings = {key: "disable" for key in mod.SAFETY_KEYS}

        assert mod.check_safety_keys(settings) == []

    def test_boolean_value_reported_as_invalid_not_missing(self) -> None:
        settings = {"disableAutoMode": True, "disableBypassPermissionsMode": "disable"}

        findings = mod.check_safety_keys(settings)

        assert len(findings) == 1
        assert findings[0].key == "disableAutoMode"
        assert findings[0].issue == "invalid"
        assert "silently ignored" in findings[0].detail

    def test_ignores_unrelated_keys(self) -> None:
        settings = {key: "disable" for key in mod.SAFETY_KEYS}
        settings["unrelatedKey"] = True

        assert mod.check_safety_keys(settings) == []


class TestSeedSafetyKeys:
    def test_adds_both_when_absent(self) -> None:
        settings, added = mod.seed_safety_keys({})

        assert set(added) == set(mod.SAFETY_KEYS)
        assert all(settings[key] == "disable" for key in mod.SAFETY_KEYS)

    def test_adds_only_the_missing_one(self) -> None:
        settings, added = mod.seed_safety_keys({"disableAutoMode": "disable"})

        assert added == ["disableBypassPermissionsMode"]
        assert settings["disableAutoMode"] == "disable"
        assert settings["disableBypassPermissionsMode"] == "disable"

    def test_never_overwrites_an_existing_invalid_value(self) -> None:
        """An existing (even wrong) value is a human decision, not an
        auto-coerce target — check_safety_keys is what flags it."""
        settings, added = mod.seed_safety_keys({"disableAutoMode": True})

        assert added == ["disableBypassPermissionsMode"]
        assert settings["disableAutoMode"] is True

    def test_preserves_unrelated_keys(self) -> None:
        settings, _ = mod.seed_safety_keys({"model": "opus"})

        assert settings["model"] == "opus"


class TestWriteSafetyKeysToFile:
    @pytest.fixture()
    def settings_file(self, tmp_path: Path) -> Path:
        path = tmp_path / "settings.local.json"
        path.write_text("{}\n")
        return path

    def test_writes_missing_keys(self, settings_file: Path) -> None:
        count, messages = mod.write_safety_keys_to_file(settings_file)

        assert count == 2
        assert len(messages) == 2
        data = json.loads(settings_file.read_text())
        assert data["disableAutoMode"] == "disable"
        assert data["disableBypassPermissionsMode"] == "disable"

    def test_no_op_when_already_present(self, settings_file: Path) -> None:
        settings_file.write_text(json.dumps({key: "disable" for key in mod.SAFETY_KEYS}) + "\n")

        count, messages = mod.write_safety_keys_to_file(settings_file)

        assert count == 0
        assert messages == []

    def test_dry_run_does_not_write(self, settings_file: Path) -> None:
        original = settings_file.read_text()

        count, messages = mod.write_safety_keys_to_file(settings_file, dry_run=True)

        assert count == 2
        assert len(messages) == 2
        assert settings_file.read_text() == original

    def test_skips_invalid_json(self, settings_file: Path) -> None:
        settings_file.write_text("{not json")

        count, messages = mod.write_safety_keys_to_file(settings_file)

        assert count == 0
        assert any("SKIP" in m for m in messages)

    def test_preserves_other_settings_keys(self, settings_file: Path) -> None:
        settings_file.write_text(json.dumps({"model": "opus", "hooks": {"PreToolUse": []}}))

        mod.write_safety_keys_to_file(settings_file)

        data = json.loads(settings_file.read_text())
        assert data["model"] == "opus"
        assert data["hooks"] == {"PreToolUse": []}

    def test_does_not_touch_an_existing_invalid_value(self, settings_file: Path) -> None:
        settings_file.write_text(json.dumps({"disableAutoMode": True}))

        count, _ = mod.write_safety_keys_to_file(settings_file)

        data = json.loads(settings_file.read_text())
        assert count == 1
        assert data["disableAutoMode"] is True
        assert data["disableBypassPermissionsMode"] == "disable"


class TestEnsureSafetyKeys:
    def test_seeds_across_multiple_files(self, tmp_path: Path) -> None:
        first = tmp_path / "a" / "settings.local.json"
        second = tmp_path / "b" / "settings.local.json"
        for path in (first, second):
            path.parent.mkdir(parents=True)
            path.write_text("{}\n")

        result = mod.ensure_safety_keys(settings_files=[first, second], dry_run=False)

        assert result["exit_code"] == 0
        assert result["total_added"] == 4
        assert result["files_changed"] == 2
        for path in (first, second):
            data = json.loads(path.read_text())
            assert data["disableAutoMode"] == "disable"
            assert data["disableBypassPermissionsMode"] == "disable"

    def test_dry_run_does_not_write_any_file(self, tmp_path: Path) -> None:
        path = tmp_path / "settings.local.json"
        path.write_text("{}\n")

        result = mod.ensure_safety_keys(settings_files=[path], dry_run=True)

        assert result["total_added"] == 2
        assert path.read_text() == "{}\n"

    def test_reports_all_already_present(self, tmp_path: Path) -> None:
        path = tmp_path / "settings.local.json"
        path.write_text(json.dumps({key: "disable" for key in mod.SAFETY_KEYS}))

        result = mod.ensure_safety_keys(settings_files=[path], dry_run=False, quiet=False)

        assert result["total_added"] == 0
        assert any("already carry both safety keys" in m for m in result["messages"])

    def test_surfaces_invalid_json_as_an_error_not_silent_skip(self, tmp_path: Path) -> None:
        path = tmp_path / "settings.local.json"
        path.write_text("{not json")

        result = mod.ensure_safety_keys(settings_files=[path], dry_run=False)

        assert result["total_added"] == 0
        assert any("SKIP" in e for e in result["errors"])


class TestEnsureSafetyKeysGitTrackedGuard:
    """GH-1155: a tracked settings.json redirects to its local sibling
    instead of being rewritten in place, same as ensure_workspace."""

    def test_tracked_settings_json_redirects_to_local_sibling(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        tracked = tmp_path / "settings.json"
        tracked.write_text("{}\n")
        local = tmp_path / "settings.local.json"
        local.write_text("{}\n")
        monkeypatch.setattr(
            update_paths,
            "_is_git_tracked",
            lambda path: path.name == "settings.json",
        )

        result = mod.ensure_safety_keys(settings_files=[tracked], dry_run=False)

        assert result["total_added"] == 2
        assert json.loads(tracked.read_text()) == {}
        data = json.loads(local.read_text())
        assert data["disableAutoMode"] == "disable"

    def test_allow_tracked_disables_the_guard(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        tracked = tmp_path / "settings.json"
        tracked.write_text("{}\n")
        monkeypatch.setattr(update_paths, "_is_git_tracked", lambda _path: True)

        result = mod.ensure_safety_keys(
            settings_files=[tracked], dry_run=False, allow_tracked=True
        )

        assert result["total_added"] == 2
        assert json.loads(tracked.read_text())["disableAutoMode"] == "disable"


class TestSafetyKeysGap:
    def test_clean_files_exit_zero(self, tmp_path: Path) -> None:
        path = tmp_path / "settings.local.json"
        path.write_text(json.dumps({key: "disable" for key in mod.SAFETY_KEYS}))

        result = mod.safety_keys_gap(settings_files=[path])

        assert result["exit_code"] == 0
        assert any("0 missing / 0 invalid" in m for m in result["messages"])

    def test_missing_key_exits_nonzero(self, tmp_path: Path) -> None:
        path = tmp_path / "settings.local.json"
        path.write_text("{}\n")

        result = mod.safety_keys_gap(settings_files=[path])

        assert result["exit_code"] == 1
        assert any("finding(s)" in e for e in result["errors"])
        assert any("missing" in m for m in result["messages"])

    def test_invalid_value_exits_nonzero(self, tmp_path: Path) -> None:
        path = tmp_path / "settings.local.json"
        path.write_text(
            json.dumps({"disableAutoMode": True, "disableBypassPermissionsMode": True})
        )

        result = mod.safety_keys_gap(settings_files=[path])

        assert result["exit_code"] == 1
        assert any("invalid" in m for m in result["messages"])

    def test_invalid_json_reported_as_error(self, tmp_path: Path) -> None:
        path = tmp_path / "settings.local.json"
        path.write_text("{not json")

        result = mod.safety_keys_gap(settings_files=[path])

        assert any("SKIP" in e for e in result["errors"])

    def test_quiet_suppresses_per_file_detail(self, tmp_path: Path) -> None:
        path = tmp_path / "settings.local.json"
        path.write_text("{}\n")

        result = mod.safety_keys_gap(settings_files=[path], quiet=True)

        assert not any(str(path) in m for m in result["messages"])
