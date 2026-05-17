"""Tests for the ensure-base feature of update_paths module."""

import json
from pathlib import Path

import pytest

from dev10x.skills.permission import update_paths
from dev10x.skills.permission.update_paths import (
    _is_nonfunctional_mcp_wildcard,
    _load_global_allow_rules,
)


class TestIsNonfunctionalMcpWildcard:
    @pytest.mark.parametrize(
        "rule",
        [
            "mcp__plugin_Dev10x_*",
            "mcp__plugin_SomePlugin_*",
        ],
    )
    def test_detects_wildcard_patterns(self, rule: str) -> None:
        assert _is_nonfunctional_mcp_wildcard(rule) is True

    @pytest.mark.parametrize(
        "rule",
        [
            "mcp__plugin_Dev10x_cli__mktmp",
            "mcp__plugin_Dev10x_cli__detect_tracker",
            "Bash(gh pr view:*)",
            "Skill(Dev10x:*)",
            "mcp__plugin_Dev10x_cli__*",
        ],
    )
    def test_ignores_non_wildcard_patterns(self, rule: str) -> None:
        assert _is_nonfunctional_mcp_wildcard(rule) is False


class TestLoadGlobalAllowRules:
    @pytest.fixture()
    def global_settings(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        settings = tmp_path / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True)
        monkeypatch.setattr(
            "dev10x.skills.permission.update_paths.Path.home",
            lambda: tmp_path,
        )
        return settings

    def test_filters_out_mcp_wildcards(self, global_settings: Path) -> None:
        global_settings.write_text(
            json.dumps(
                {
                    "permissions": {
                        "allow": [
                            "mcp__plugin_Dev10x_*",
                            "mcp__plugin_Dev10x_cli__mktmp",
                            "Bash(gh pr view:*)",
                        ]
                    }
                }
            )
        )

        effective, wildcards = _load_global_allow_rules()

        assert "mcp__plugin_Dev10x_*" not in effective
        assert "mcp__plugin_Dev10x_cli__mktmp" in effective
        assert "Bash(gh pr view:*)" in effective
        assert wildcards == ["mcp__plugin_Dev10x_*"]

    def test_returns_empty_when_no_wildcards(self, global_settings: Path) -> None:
        global_settings.write_text(
            json.dumps({"permissions": {"allow": ["mcp__plugin_Dev10x_cli__mktmp"]}})
        )

        effective, wildcards = _load_global_allow_rules()

        assert "mcp__plugin_Dev10x_cli__mktmp" in effective
        assert wildcards == []

    def test_returns_empty_sets_when_file_missing(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "dev10x.skills.permission.update_paths.Path.home",
            lambda: tmp_path,
        )

        effective, wildcards = _load_global_allow_rules()

        assert effective == set()
        assert wildcards == []


class TestEnsureBasePermissionsWithWildcard:
    """Legacy wildcard-only behaviour with expansion disabled."""

    @pytest.fixture()
    def settings_file(self, tmp_path: Path) -> Path:
        return tmp_path / "settings.local.json"

    def test_wildcard_does_not_mask_individual_entries(
        self,
        settings_file: Path,
    ) -> None:
        settings_file.write_text(
            json.dumps(
                {
                    "permissions": {
                        "allow": [
                            "mcp__plugin_Dev10x_*",
                        ]
                    }
                }
            )
        )

        count, _ = update_paths.ensure_base_permissions(
            settings_file,
            ["mcp__plugin_Dev10x_cli__mktmp", "mcp__plugin_Dev10x_cli__push_safe"],
            expand_mcp=False,
        )

        assert count == 3
        data = json.loads(settings_file.read_text())
        allow = data["permissions"]["allow"]
        assert "mcp__plugin_Dev10x_cli__mktmp" in allow
        assert "mcp__plugin_Dev10x_cli__push_safe" in allow
        assert "mcp__plugin_Dev10x_*" not in allow

    def test_removes_wildcard_even_when_no_missing_permissions(
        self,
        settings_file: Path,
    ) -> None:
        settings_file.write_text(
            json.dumps(
                {
                    "permissions": {
                        "allow": [
                            "mcp__plugin_Dev10x_*",
                            "mcp__plugin_Dev10x_cli__mktmp",
                        ]
                    }
                }
            )
        )

        count, messages = update_paths.ensure_base_permissions(
            settings_file,
            ["mcp__plugin_Dev10x_cli__mktmp"],
            expand_mcp=False,
        )

        assert count == 1
        data = json.loads(settings_file.read_text())
        allow = data["permissions"]["allow"]
        assert "mcp__plugin_Dev10x_*" not in allow
        assert "mcp__plugin_Dev10x_cli__mktmp" in allow
        assert any("non-functional" in m for m in messages)


class TestEnsureBaseExpandsStaleWildcards:
    """When `expand_mcp=True` (default), stale wildcards are
    replaced with the enumerated tool catalog so a follow-up
    `enumerate-mcp` pass finds nothing left to do."""

    @pytest.fixture()
    def settings_file(self, tmp_path: Path) -> Path:
        return tmp_path / "settings.local.json"

    @pytest.fixture()
    def fake_catalog(self, monkeypatch: pytest.MonkeyPatch) -> dict:
        catalog = {
            "Dev10x_cli": [
                "mcp__plugin_Dev10x_cli__alpha",
                "mcp__plugin_Dev10x_cli__beta",
            ],
            "Dev10x_db": ["mcp__plugin_Dev10x_db__query"],
        }
        monkeypatch.setattr(
            "dev10x.skills.permission.enumerate_mcp.discover_mcp_tools",
            lambda: catalog,
        )
        return catalog

    def test_expands_wildcard_into_catalog(
        self,
        settings_file: Path,
        fake_catalog: dict,
    ) -> None:
        settings_file.write_text(
            json.dumps({"permissions": {"allow": ["mcp__plugin_Dev10x_*"]}})
        )

        count, messages = update_paths.ensure_base_permissions(
            settings_file,
            base_permissions=[],
        )

        data = json.loads(settings_file.read_text())
        allow = data["permissions"]["allow"]
        assert "mcp__plugin_Dev10x_*" not in allow
        assert "mcp__plugin_Dev10x_cli__alpha" in allow
        assert "mcp__plugin_Dev10x_cli__beta" in allow
        assert "mcp__plugin_Dev10x_db__query" in allow
        # 1 wildcard removed + 3 tools added
        assert count == 4
        assert any("expanded from MCP wildcard" in m for m in messages)

    def test_expansion_deduplicates_against_existing(
        self,
        settings_file: Path,
        fake_catalog: dict,
    ) -> None:
        settings_file.write_text(
            json.dumps(
                {
                    "permissions": {
                        "allow": [
                            "mcp__plugin_Dev10x_*",
                            "mcp__plugin_Dev10x_cli__alpha",
                        ]
                    }
                }
            )
        )

        count, _ = update_paths.ensure_base_permissions(
            settings_file,
            base_permissions=[],
        )

        data = json.loads(settings_file.read_text())
        allow = data["permissions"]["allow"]
        # alpha kept once, beta + query added, wildcard removed
        assert allow.count("mcp__plugin_Dev10x_cli__alpha") == 1
        assert "mcp__plugin_Dev10x_cli__beta" in allow
        assert "mcp__plugin_Dev10x_db__query" in allow
        assert "mcp__plugin_Dev10x_*" not in allow
        # 1 removed + 2 expanded (alpha already present)
        assert count == 3

    def test_no_expansion_when_no_wildcards(
        self,
        settings_file: Path,
        fake_catalog: dict,
    ) -> None:
        settings_file.write_text(
            json.dumps({"permissions": {"allow": ["mcp__plugin_Dev10x_cli__alpha"]}})
        )

        count, _ = update_paths.ensure_base_permissions(
            settings_file,
            base_permissions=["mcp__plugin_Dev10x_cli__alpha"],
        )

        assert count == 0

    def test_disabled_expand_mcp_only_strips_wildcards(
        self,
        settings_file: Path,
        fake_catalog: dict,
    ) -> None:
        settings_file.write_text(
            json.dumps({"permissions": {"allow": ["mcp__plugin_Dev10x_*"]}})
        )

        count, _ = update_paths.ensure_base_permissions(
            settings_file,
            base_permissions=[],
            expand_mcp=False,
        )

        data = json.loads(settings_file.read_text())
        allow = data["permissions"]["allow"]
        assert allow == []
        assert count == 1


class TestEnsureBasePermissions:
    BASE_PERMISSIONS = [
        "Bash(/tmp/Dev10x/bin/mktmp.sh:*)",
        "Bash(gh pr view:*)",
        "Write(/tmp/Dev10x/git/**)",
    ]

    @pytest.fixture()
    def settings_file(self, tmp_path: Path) -> Path:
        return tmp_path / "settings.local.json"

    @pytest.fixture()
    def empty_settings(self, settings_file: Path) -> Path:
        settings_file.write_text(json.dumps({"permissions": {"allow": []}}) + "\n")
        return settings_file

    @pytest.fixture()
    def partial_settings(self, settings_file: Path) -> Path:
        settings_file.write_text(
            json.dumps(
                {
                    "permissions": {
                        "allow": [
                            "Bash(/tmp/Dev10x/bin/mktmp.sh:*)",
                            "Bash(git log:*)",
                        ]
                    }
                }
            )
            + "\n"
        )
        return settings_file

    @pytest.fixture()
    def full_settings(self, settings_file: Path) -> Path:
        settings_file.write_text(
            json.dumps({"permissions": {"allow": list(self.BASE_PERMISSIONS)}}) + "\n"
        )
        return settings_file

    @pytest.fixture()
    def no_permissions_settings(self, settings_file: Path) -> Path:
        settings_file.write_text(json.dumps({"hooks": {}}) + "\n")
        return settings_file

    def test_adds_all_missing_to_empty(self, empty_settings: Path) -> None:
        count, messages = update_paths.ensure_base_permissions(
            empty_settings,
            self.BASE_PERMISSIONS,
        )

        assert count == 3
        data = json.loads(empty_settings.read_text())
        assert set(data["permissions"]["allow"]) == set(self.BASE_PERMISSIONS)

    def test_adds_only_missing_to_partial(self, partial_settings: Path) -> None:
        count, messages = update_paths.ensure_base_permissions(
            partial_settings,
            self.BASE_PERMISSIONS,
        )

        assert count == 2
        data = json.loads(partial_settings.read_text())
        allow = data["permissions"]["allow"]
        assert "Bash(gh pr view:*)" in allow
        assert "Write(/tmp/Dev10x/git/**)" in allow
        assert "Bash(git log:*)" in allow  # pre-existing preserved

    def test_no_changes_when_complete(self, full_settings: Path) -> None:
        count, messages = update_paths.ensure_base_permissions(
            full_settings,
            self.BASE_PERMISSIONS,
        )

        assert count == 0
        assert messages == []

    def test_dry_run_does_not_write(self, empty_settings: Path) -> None:
        original = empty_settings.read_text()

        count, messages = update_paths.ensure_base_permissions(
            empty_settings,
            self.BASE_PERMISSIONS,
            dry_run=True,
        )

        assert count == 3
        assert len(messages) == 3
        assert empty_settings.read_text() == original

    def test_creates_permissions_key_if_absent(
        self, no_permissions_settings: Path
    ) -> None:
        count, _ = update_paths.ensure_base_permissions(
            no_permissions_settings,
            self.BASE_PERMISSIONS,
        )

        assert count == 3
        data = json.loads(no_permissions_settings.read_text())
        assert "permissions" in data
        assert set(data["permissions"]["allow"]) == set(self.BASE_PERMISSIONS)

    def test_skips_invalid_json(self, settings_file: Path) -> None:
        settings_file.write_text("{invalid json}")

        count, messages = update_paths.ensure_base_permissions(
            settings_file,
            self.BASE_PERMISSIONS,
        )

        assert count == 0
        assert any("SKIP" in m for m in messages)

    def test_messages_show_added_rules(self, empty_settings: Path) -> None:
        _, messages = update_paths.ensure_base_permissions(
            empty_settings,
            self.BASE_PERMISSIONS,
        )

        assert len(messages) == 3
        assert all(m.startswith("  + ") for m in messages)

    def test_preserves_other_settings_keys(self, settings_file: Path) -> None:
        settings_file.write_text(
            json.dumps(
                {
                    "permissions": {"allow": [], "deny": ["something"]},
                    "hooks": {"PreToolUse": []},
                }
            )
            + "\n"
        )

        update_paths.ensure_base_permissions(
            settings_file,
            self.BASE_PERMISSIONS,
        )

        data = json.loads(settings_file.read_text())
        assert data["permissions"]["deny"] == ["something"]
        assert data["hooks"] == {"PreToolUse": []}


class TestEnsureBaseDenies:
    """Tests for ensure_base_denies (GH-204)."""

    BASE_DENIES = [
        "mcp__claude_ai_Linear__delete_customer",
        "mcp__claude_ai_Linear__delete_comment",
    ]

    @pytest.fixture()
    def settings_file(self, tmp_path: Path) -> Path:
        path = tmp_path / "settings.local.json"
        path.write_text(json.dumps({"permissions": {"allow": [], "deny": []}}))
        return path

    def test_adds_missing_denies(self, settings_file: Path) -> None:
        count, messages = update_paths.ensure_base_denies(
            settings_file,
            self.BASE_DENIES,
        )

        assert count == 2
        assert all("(deny)" in m for m in messages)
        data = json.loads(settings_file.read_text())
        assert set(data["permissions"]["deny"]) == set(self.BASE_DENIES)

    def test_skips_already_present(self, settings_file: Path) -> None:
        settings_file.write_text(
            json.dumps(
                {
                    "permissions": {
                        "allow": [],
                        "deny": ["mcp__claude_ai_Linear__delete_customer"],
                    }
                }
            )
        )

        count, _ = update_paths.ensure_base_denies(
            settings_file,
            self.BASE_DENIES,
        )

        assert count == 1
        data = json.loads(settings_file.read_text())
        deny = data["permissions"]["deny"]
        assert deny.count("mcp__claude_ai_Linear__delete_customer") == 1
        assert "mcp__claude_ai_Linear__delete_comment" in deny

    def test_creates_deny_key_if_absent(self, tmp_path: Path) -> None:
        path = tmp_path / "settings.local.json"
        path.write_text(json.dumps({"permissions": {"allow": []}}))

        count, _ = update_paths.ensure_base_denies(path, self.BASE_DENIES)

        assert count == 2
        data = json.loads(path.read_text())
        assert set(data["permissions"]["deny"]) == set(self.BASE_DENIES)

    def test_creates_permissions_key_if_absent(self, tmp_path: Path) -> None:
        path = tmp_path / "settings.local.json"
        path.write_text(json.dumps({}))

        count, _ = update_paths.ensure_base_denies(path, self.BASE_DENIES)

        assert count == 2
        data = json.loads(path.read_text())
        assert set(data["permissions"]["deny"]) == set(self.BASE_DENIES)

    def test_dry_run_does_not_write(self, settings_file: Path) -> None:
        update_paths.ensure_base_denies(
            settings_file,
            self.BASE_DENIES,
            dry_run=True,
        )

        data = json.loads(settings_file.read_text())
        assert data["permissions"]["deny"] == []

    def test_skips_invalid_json(self, settings_file: Path) -> None:
        settings_file.write_text("{invalid json}")

        count, messages = update_paths.ensure_base_denies(
            settings_file,
            self.BASE_DENIES,
        )

        assert count == 0
        assert any("SKIP" in m for m in messages)

    def test_ensure_base_applies_both_allows_and_denies(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The ensure_base wrapper reads both base_permissions and base_denies
        from the config and applies them in one pass."""
        monkeypatch.setattr(
            "dev10x.skills.permission.update_paths.Path.home",
            lambda: tmp_path / "home",
        )
        (tmp_path / "home" / ".claude").mkdir(parents=True)

        settings = tmp_path / "settings.local.json"
        settings.write_text(json.dumps({"permissions": {"allow": [], "deny": []}}))

        result = update_paths.ensure_base(
            config={
                "base_permissions": ["mcp__claude_ai_Linear__get_issue"],
                "base_denies": ["mcp__claude_ai_Linear__delete_customer"],
            },
            settings_files=[settings],
            dry_run=False,
        )

        assert result["total_added"] == 2
        assert result["files_changed"] == 1
        data = json.loads(settings.read_text())
        assert "mcp__claude_ai_Linear__get_issue" in data["permissions"]["allow"]
        assert "mcp__claude_ai_Linear__delete_customer" in data["permissions"]["deny"]
