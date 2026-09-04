"""Deny-aware allow seeding, sanctioned pre-commit coverage, and the
shared git-tracked write guard (GH-1149, GH-1152, GH-1155)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from dev10x.skills.permission import enumerate_mcp
from dev10x.skills.permission import update_paths as mod

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PROJECTS_YAML = _REPO_ROOT / "skills" / "upgrade-cleanup" / "projects.yaml"


@pytest.fixture
def settings_file(tmp_path: Path) -> Path:
    path = tmp_path / "settings.local.json"
    path.write_text("{}\n")
    return path


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(enumerate_mcp, "discover_mcp_tools", lambda **_kw: {})


def _allow(path: Path) -> list[str]:
    return json.loads(path.read_text())["permissions"]["allow"]


class TestDenyAwareAllowSeeding:
    """GH-1152: never re-add a rule the file's own deny list already names."""

    def test_rule_already_denied_is_not_re_added(self, settings_file: Path) -> None:
        settings_file.write_text(json.dumps({"permissions": {"deny": ["Bash(sudo:*)"]}}))
        count, messages = mod.ensure_base_permissions(
            settings_file,
            ["Bash(sudo:*)"],
            dry_run=False,
        )
        assert count == 0
        assert any("skipped 1 denied by this file" in m for m in messages)
        data = json.loads(settings_file.read_text())
        assert "Bash(sudo:*)" not in data.get("permissions", {}).get("allow", [])

    def test_rule_not_denied_is_added_normally(self, settings_file: Path) -> None:
        settings_file.write_text(json.dumps({"permissions": {"deny": ["Bash(sudo:*)"]}}))
        count, messages = mod.ensure_base_permissions(
            settings_file,
            ["Bash(ls:*)"],
            dry_run=False,
        )
        assert count == 1
        assert "Bash(ls:*)" in _allow(settings_file)
        assert not any("skipped" in m for m in messages)


class TestSanctionedPreCommitCoverage:
    """GH-1149: the catalog must carry the sanctioned bare `pre-commit run` form."""

    def test_shipped_catalog_carries_sanctioned_pre_commit_rule(self) -> None:
        config = yaml.safe_load(_PROJECTS_YAML.read_text(encoding="utf-8"))
        assert "Bash(pre-commit run:*)" in config["base_permissions"]


class TestPartitionWritableGitGuard:
    """GH-1155: the git-tracked guard is now shared across every writer."""

    def test_tracked_settings_json_is_skipped_by_default(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        tracked = tmp_path / "settings.json"
        tracked.write_text("{}\n")
        monkeypatch.setattr(mod, "_is_git_tracked", lambda _path: True)

        writable, messages = mod.partition_writable([tracked])

        assert writable == []
        assert any("SKIP (git-tracked)" in m for m in messages)

    def test_redirect_to_existing_sibling(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        tracked = tmp_path / "settings.json"
        tracked.write_text("{}\n")
        sibling = tmp_path / "settings.local.json"
        sibling.write_text("{}\n")
        monkeypatch.setattr(mod, "_is_git_tracked", lambda _path: True)

        writable, messages = mod.partition_writable([tracked], redirect_tracked=True)

        assert writable == [sibling]
        assert any("REDIRECT (git-tracked)" in m for m in messages)

    def test_redirect_without_sibling_on_disk_is_skipped(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        tracked = tmp_path / "settings.json"
        tracked.write_text("{}\n")
        monkeypatch.setattr(mod, "_is_git_tracked", lambda _path: True)

        writable, messages = mod.partition_writable([tracked], redirect_tracked=True)

        assert writable == []
        assert any("no settings.local.json to redirect to" in m for m in messages)

    def test_redirect_when_sibling_already_in_input_list_is_not_duplicated(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        tracked = tmp_path / "settings.json"
        tracked.write_text("{}\n")
        sibling = tmp_path / "settings.local.json"
        sibling.write_text("{}\n")
        monkeypatch.setattr(
            mod,
            "_is_git_tracked",
            lambda path: path.name == "settings.json",
        )

        writable, messages = mod.partition_writable(
            [tracked, sibling],
            redirect_tracked=True,
        )

        assert writable == [sibling]
        assert any("sibling already targeted" in m for m in messages)

    def test_allow_tracked_returns_every_input_unchanged(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        tracked = tmp_path / "settings.json"
        tracked.write_text("{}\n")
        monkeypatch.setattr(mod, "_is_git_tracked", lambda _path: True)

        writable, messages = mod.partition_writable([tracked], allow_tracked=True)

        assert writable == [tracked]
        assert any("guard disabled" in m for m in messages)

    @pytest.mark.parametrize(
        "kwargs",
        [{}, {"redirect_tracked": True}, {"allow_tracked": True}],
        ids=["default", "redirect_tracked", "allow_tracked"],
    )
    def test_untracked_file_always_passes_through(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        kwargs: dict[str, bool],
    ) -> None:
        untracked = tmp_path / "settings.json"
        untracked.write_text("{}\n")
        monkeypatch.setattr(mod, "_is_git_tracked", lambda _path: False)

        writable, _messages = mod.partition_writable([untracked], **kwargs)
        assert writable == [untracked]
