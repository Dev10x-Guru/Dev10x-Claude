"""Tests for the ensure-base feature of update_paths module."""

import json
from pathlib import Path

import pytest
import yaml

from dev10x.domain.common.accepted_findings import DEFAULT_ACCEPTED_FINDINGS, find_acceptance
from dev10x.domain.common.tracker_choice import Tracker
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
        settings_file.write_text(json.dumps({"permissions": {"allow": ["mcp__plugin_Dev10x_*"]}}))

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
        settings_file.write_text(json.dumps({"permissions": {"allow": ["mcp__plugin_Dev10x_*"]}}))

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
        "Edit(/tmp/Dev10x/git/**)",
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
        assert "Edit(/tmp/Dev10x/git/**)" in allow
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

    def test_creates_permissions_key_if_absent(self, no_permissions_settings: Path) -> None:
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

    @pytest.fixture
    def home_settings(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        monkeypatch.setattr(
            "dev10x.skills.permission.update_paths.Path.home",
            lambda: tmp_path / "home",
        )
        (tmp_path / "home" / ".claude").mkdir(parents=True)
        settings = tmp_path / "settings.local.json"
        settings.write_text(json.dumps({"permissions": {"allow": [], "deny": [], "ask": []}}))
        return settings

    def test_ensure_base_applies_both_allows_and_denies(self, home_settings: Path) -> None:
        """The ensure_base wrapper reads both base_permissions and base_denies
        from the config and applies them in one pass."""
        result = update_paths.ensure_base(
            config={
                "base_permissions": ["mcp__claude_ai_Linear__get_issue"],
                "base_denies": ["mcp__claude_ai_Linear__delete_customer"],
            },
            settings_files=[home_settings],
            dry_run=False,
        )

        assert result["total_added"] == 2
        assert result["files_changed"] == 1
        data = json.loads(home_settings.read_text())
        assert "mcp__claude_ai_Linear__get_issue" in data["permissions"]["allow"]
        assert "mcp__claude_ai_Linear__delete_customer" in data["permissions"]["deny"]

    def test_ensure_base_applies_all_three_tiers(self, home_settings: Path) -> None:
        result = update_paths.ensure_base(
            config={
                "base_permissions": ["mcp__claude_ai_Linear__get_issue"],
                "base_denies": ["mcp__claude_ai_Linear__delete_customer"],
                "base_asks": ["Bash(gh api -X DELETE:*)"],
            },
            settings_files=[home_settings],
            dry_run=False,
        )

        assert result["total_added"] == 3
        data = json.loads(home_settings.read_text())
        assert "Bash(gh api -X DELETE:*)" in data["permissions"]["ask"]

    def test_ask_tier_survives_an_empty_allow_list(self, home_settings: Path) -> None:
        """GH-1154 regression: the early return used to fire on an empty allow
        list and skip the deny and ask tiers with it."""
        result = update_paths.ensure_base(
            config={
                "base_permissions": [],
                "base_denies": [],
                "base_asks": ["Bash(gh api -X DELETE:*)"],
            },
            settings_files=[home_settings],
            dry_run=False,
        )

        assert result["total_added"] == 1
        data = json.loads(home_settings.read_text())
        assert data["permissions"]["ask"] == ["Bash(gh api -X DELETE:*)"]

    def test_ensure_base_emits_home_twin_for_tilde_rule(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """ensure_base renders through render_permissions, so a ~/ allow rule
        merges non-destructively AND gains its resolved /home/<user>/ twin
        (GH-47) — additive over the pre-PAP flat-shim output."""
        monkeypatch.setattr(
            "dev10x.skills.permission.update_paths.Path.home",
            lambda: tmp_path / "home",
        )
        (tmp_path / "home" / ".claude").mkdir(parents=True)

        settings = tmp_path / "settings.local.json"
        settings.write_text(
            json.dumps({"permissions": {"allow": ["Bash(git log:*)"], "deny": []}})
        )

        result = update_paths.ensure_base(
            config={"base_permissions": ["Read(~/.claude/tools/**)"], "base_denies": []},
            settings_files=[settings],
            dry_run=False,
        )

        assert result["total_added"] == 2
        allow = json.loads(settings.read_text())["permissions"]["allow"]
        assert "Bash(git log:*)" in allow  # pre-existing user rule preserved
        assert "Read(~/.claude/tools/**)" in allow
        assert f"Read({tmp_path}/home/.claude/tools/**)" in allow


class TestEnsureBaseSeedsOneTracker:
    """GH-768: only the project's tracker block reaches the settings file."""

    TRACKER_CONFIG: dict = {
        "base_permissions": ["Bash(git status:*)"],
        "base_denies": [],
        "tracker_permissions": {
            "linear": ["mcp__claude_ai_Linear__get_issue"],
            "jira": ["mcp__claude_ai_Atlassian_Rovo__getJiraIssue"],
            "github": ["mcp__plugin_Dev10x_cli__issue_get"],
        },
        "tracker_denies": {"linear": ["mcp__claude_ai_Linear__delete_comment"]},
    }

    @pytest.fixture()
    def settings(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        monkeypatch.setattr(
            "dev10x.skills.permission.update_paths.Path.home",
            lambda: tmp_path / "home",
        )
        (tmp_path / "home" / ".claude").mkdir(parents=True)
        path = tmp_path / "settings.local.json"
        path.write_text(json.dumps({"permissions": {"allow": [], "deny": []}}))
        return path

    def _run(self, settings: Path, monkeypatch: pytest.MonkeyPatch, tracker: str) -> dict:
        monkeypatch.setattr(
            "dev10x.skills.permission.tracker_resolve.resolve_tracker",
            lambda *, toplevel: Tracker(tracker),
        )
        monkeypatch.setattr(
            "dev10x.skills.permission.tracker_resolve.tracker_source",
            lambda *, toplevel: "project",
        )
        return update_paths.ensure_base(
            config=self.TRACKER_CONFIG,
            settings_files=[settings],
            dry_run=False,
            toplevel="/work/x/repo",
        )

    def test_jira_project_gets_no_linear_rules(
        self,
        settings: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The defect: a Jira user collected ~35 inert Linear allows."""
        self._run(settings, monkeypatch, "jira")
        data = json.loads(settings.read_text())
        seeded = data["permissions"]["allow"] + data["permissions"]["deny"]
        assert "mcp__claude_ai_Atlassian_Rovo__getJiraIssue" in data["permissions"]["allow"]
        assert not any("Linear" in rule for rule in seeded)

    def test_linear_project_still_gets_its_allows_and_denies(
        self,
        settings: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        self._run(settings, monkeypatch, "linear")
        data = json.loads(settings.read_text())
        assert "mcp__claude_ai_Linear__get_issue" in data["permissions"]["allow"]
        assert "mcp__claude_ai_Linear__delete_comment" in data["permissions"]["deny"]

    def test_tracker_independent_rules_seed_regardless(
        self,
        settings: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        self._run(settings, monkeypatch, "github")
        assert "Bash(git status:*)" in json.loads(settings.read_text())["permissions"]["allow"]

    def test_run_reports_which_tracker_it_seeded(
        self,
        settings: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Silently omitting a tracker's rules is indistinguishable from a bug."""
        result = self._run(settings, monkeypatch, "jira")
        assert any("Issue tracker: jira" in message for message in result["messages"])

    def test_legacy_catalog_without_tracker_blocks_is_untouched(
        self,
        settings: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        result = update_paths.ensure_base(
            config={"base_permissions": ["Bash(git status:*)"], "base_denies": []},
            settings_files=[settings],
            dry_run=False,
            toplevel="/work/x/repo",
        )
        assert not any("Issue tracker:" in message for message in result["messages"])
        assert "Bash(git status:*)" in json.loads(settings.read_text())["permissions"]["allow"]


class TestPrivilegeEscalationDenies:
    """GH-326: sudo/doas/pkexec ship as plugin-default deny rules."""

    PRIVILEGE_ESCALATION_DENIES = [
        "Bash(sudo:*)",
        "Bash(sudo *)",
        "Bash(sudo -n *)",
        "Bash(sudo -i *)",
        "Bash(sudoedit:*)",
        "Bash(doas:*)",
        "Bash(doas *)",
        "Bash(pkexec:*)",
        "Bash(pkexec *)",
    ]

    @pytest.fixture()
    def shipped_base_denies(self) -> list[str]:
        projects_yaml = (
            Path(__file__).resolve().parents[3] / "skills" / "upgrade-cleanup" / "projects.yaml"
        )
        config = yaml.safe_load(projects_yaml.read_text())
        return config.get("base_denies", [])

    @pytest.mark.parametrize("rule", PRIVILEGE_ESCALATION_DENIES)
    def test_catalog_ships_privilege_escalation_deny(
        self,
        rule: str,
        shipped_base_denies: list[str],
    ) -> None:
        assert rule in shipped_base_denies

    def test_evidence_212_sudo_rm_is_blocked(
        self,
        tmp_path: Path,
        shipped_base_denies: list[str],
    ) -> None:
        """GH-271 evidence #212: `sudo -n rm -rf <workspace>` must render a
        deny that blocks it. The non-interactive shape is the dangerous one
        because it silently bypasses the password prompt."""
        settings = tmp_path / "settings.local.json"
        settings.write_text(json.dumps({"permissions": {"allow": [], "deny": []}}))

        update_paths.ensure_base_denies(settings, shipped_base_denies)

        deny = json.loads(settings.read_text())["permissions"]["deny"]
        assert "Bash(sudo -n *)" in deny
        assert "Bash(sudo:*)" in deny


@pytest.fixture()
def shipped_base_permissions() -> list[str]:
    """The flat allow catalog `ensure-base` actually ships."""
    projects_yaml = (
        Path(__file__).resolve().parents[3] / "skills" / "upgrade-cleanup" / "projects.yaml"
    )
    config = yaml.safe_load(projects_yaml.read_text())
    return config.get("base_permissions", [])


class TestNoRuntimeClaudeWriteSeeds:
    """GH-862/ADR-0018: no runtime Write/Edit seed under .claude/.

    The GH-790 session-config exact-path seeds (session.yaml /
    config.yaml) were retired by ADR-0018 (GH-812) — durable state
    moved to ~/.config/Dev10x and is written via the `dev10x` CLI,
    not an allow rule. Runtime writes under .claude/ trip Claude
    Code's self-settings consent gate regardless of allow rules and
    are flagged by the write-guard-claude scanner, so the shipped
    base_permissions must not seed any Write/Edit rule targeting a
    .claude/ path.
    """

    def test_no_write_or_edit_seed_targets_claude_path(
        self,
        shipped_base_permissions: list[str],
    ) -> None:
        offenders = [
            rule
            for rule in shipped_base_permissions
            if rule.startswith(("Write(", "Edit(")) and ".claude/" in rule
        ]
        assert offenders == [], f"runtime .claude/ write seeds must be removed: {offenders}"

    def test_retired_session_config_seeds_absent(
        self,
        shipped_base_permissions: list[str],
    ) -> None:
        retired = {
            "Read(.claude/Dev10x/session.yaml)",
            "Edit(.claude/Dev10x/session.yaml)",
            "Read(.claude/Dev10x/config.yaml)",
            "Edit(.claude/Dev10x/config.yaml)",
        }
        assert not (retired & set(shipped_base_permissions))

    def test_memory_read_seed_retained(
        self,
        shipped_base_permissions: list[str],
    ) -> None:
        # Tier-2 playbook resolution still reads legacy overrides here.
        assert "Read(~/.claude/memory/Dev10x/**)" in shipped_base_permissions


class TestGitBranchDeleteAllowed:
    """GH-864 + GH-1067: the whole local-branch-deletion family ships as a
    pre-approved base permission so AFK/fanout worktree teardown does not
    prompt.

    GH-864 originally shipped only `-d` (git refuses it on an unmerged
    branch) and held `-D` behind a prompt as "destructive". The 2026-08-25
    ruling on GH-1067 supersedes that stratification: `-D` removes a ref,
    not history — the deleted tip stays reachable via `git log -g` — which
    is the same recoverability argument already accepted for
    `git reset --hard` and `git push --force` (GH-1053). An overnight crew
    cleaning up after killed workers cannot answer a prompt, so holding
    `-D` back bought no safety and cost a wedged run.

    `--force` stays out: it is not a spelling of the delete verb, so
    admitting it would widen the rule past what was actually ruled on."""

    @pytest.mark.parametrize(
        "rule",
        [
            "Bash(git branch -d:*)",
            "Bash(git branch --delete:*)",
            "Bash(git branch -D:*)",
        ],
    )
    def test_catalog_ships_the_deletion_family(
        self,
        rule: str,
        shipped_base_permissions: list[str],
    ) -> None:
        assert rule in shipped_base_permissions

    def test_catalog_does_not_widen_to_branch_force(
        self,
        shipped_base_permissions: list[str],
    ) -> None:
        assert "Bash(git branch --force:*)" not in shipped_base_permissions

    @pytest.mark.parametrize(
        "rule",
        [
            "Bash(git branch -d:*)",
            "Bash(git branch --delete:*)",
            "Bash(git branch -D:*)",
        ],
    )
    def test_deletion_family_is_accepted_by_design(self, rule: str) -> None:
        """GH-1067 AC2: never re-proposed for ask/deny by the auditor."""
        assert (
            find_acceptance(
                rule=rule,
                classification="REDUNDANT",
                catalog=DEFAULT_ACCEPTED_FINDINGS,
            )
            is not None
        )


GH_PROJECT_READ_RULES = [
    "Bash(gh project list:*)",
    "Bash(gh project view:*)",
    "Bash(gh project item-list:*)",
    "Bash(gh project field-list:*)",
]

# Both shipped catalogs must agree; each case runs against every one.
GH_PROJECT_CATALOGS = ["shipped_baseline_rules", "shipped_base_permissions"]

GH_PROJECT_WRITE_VERBS = [
    "create",
    "edit",
    "delete",
    "link",
    "unlink",
    "mark-template",
    "item-add",
    "item-edit",
    "item-delete",
    "item-archive",
]


class TestGhProjectReadsAllowed:
    """GH-1078: the read-only `gh project` verbs ship pre-approved, the way
    every other `gh` read surface already does.

    Before this, `baseline-permissions.yaml` carried no `gh project` entry at
    all, so a read-only `gh project item-list` prompted while `gh api:*` —
    which can issue arbitrary writes — was tier-1 allowed. The prompt's
    "don't ask again" suggestion offers `gh project *`, which would admit the
    delete verbs, so leaving the gap open actively pushed the user toward the
    over-broad rule.

    The write verbs stay out deliberately: stratified exactly like `gh run`
    and `gh workflow`, where the cost-bearing or state-flipping forms keep
    prompting. A project item-delete removes rows no reflog can recover, so
    the recoverability argument that admitted `git branch -D` (GH-1067) does
    not carry over here."""

    @pytest.fixture()
    def shipped_baseline_rules(self) -> list[str]:
        baseline_yaml = (
            Path(__file__).resolve().parents[3]
            / "src"
            / "dev10x"
            / "skills"
            / "permission"
            / "baseline-permissions.yaml"
        )
        config = yaml.safe_load(baseline_yaml.read_text())
        return [
            rule for group in config.get("groups", {}).values() for rule in group.get("rules", [])
        ]

    @pytest.mark.parametrize("shipped", GH_PROJECT_CATALOGS)
    @pytest.mark.parametrize("rule", GH_PROJECT_READ_RULES)
    def test_every_catalog_ships_the_read_verbs(
        self,
        rule: str,
        shipped: str,
        request: pytest.FixtureRequest,
    ) -> None:
        assert rule in request.getfixturevalue(shipped)

    @pytest.mark.parametrize("shipped", GH_PROJECT_CATALOGS)
    @pytest.mark.parametrize("verb", GH_PROJECT_WRITE_VERBS)
    def test_no_catalog_ships_a_write_verb(
        self,
        verb: str,
        shipped: str,
        request: pytest.FixtureRequest,
    ) -> None:
        assert f"Bash(gh project {verb}:*)" not in request.getfixturevalue(shipped)

    @pytest.mark.parametrize("shipped", GH_PROJECT_CATALOGS)
    def test_no_catalog_widens_to_bare_gh_project(
        self,
        shipped: str,
        request: pytest.FixtureRequest,
    ) -> None:
        """The over-broad shape the permission prompt itself suggests."""
        rules = request.getfixturevalue(shipped)
        assert "Bash(gh project:*)" not in rules
        assert "Bash(gh project *)" not in rules
