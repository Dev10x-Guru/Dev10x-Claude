"""Tests for dev10x.skills.permission.doctor (GH-99)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

doctor = pytest.importorskip("dev10x.skills.permission.doctor")


class TestCanonicalizeRule:
    def test_rewrites_resolved_username_and_version(self) -> None:
        rule = (
            "Bash(/home/janusz/.claude/plugins/cache/Dev10x-Guru/Dev10x/0.71.0"
            "/skills/foo/scripts/bar.sh:*)"
        )
        assert doctor.canonicalize_rule(rule) == (
            "Bash(~/.claude/plugins/cache/Dev10x-Guru/Dev10x/**/skills/foo/scripts/bar.sh:*)"
        )

    def test_rewrites_tilde_version(self) -> None:
        rule = "Bash(~/.claude/plugins/cache/Dev10x-Guru/Dev10x/0.5.0/bin/release.sh:*)"
        assert doctor.canonicalize_rule(rule) == (
            "Bash(~/.claude/plugins/cache/Dev10x-Guru/Dev10x/**/bin/release.sh:*)"
        )

    def test_rewrites_dev10x_claude_plugin_name(self) -> None:
        rule = "Bash(/home/u/.claude/plugins/cache/Other/dev10x-claude/1.2.3/skills/x/y.sh:*)"
        assert doctor.canonicalize_rule(rule) == (
            "Bash(~/.claude/plugins/cache/Other/dev10x-claude/**/skills/x/y.sh:*)"
        )

    def test_returns_none_when_already_canonical(self) -> None:
        rule = "Bash(~/.claude/plugins/cache/Dev10x-Guru/Dev10x/**/bin/release.sh:*)"
        assert doctor.canonicalize_rule(rule) is None

    def test_returns_none_when_unrelated(self) -> None:
        assert doctor.canonicalize_rule("Bash(git status:*)") is None
        assert doctor.canonicalize_rule("Read(/tmp/Dev10x/**)") is None

    def test_collapses_double_slash_and_version_pins(self) -> None:
        # GH-704: ${CLAUDE_PLUGIN_ROOT} trailing-slash pollution bakes a `//`
        # into the rule; collapse it AND version-pin in one pass.
        rule = (
            "Bash(/home/janusz/.claude/plugins/cache/Dev10x-Guru/Dev10x/0.79.0"
            "//skills/foo/scripts/bar.sh:*)"
        )
        assert doctor.canonicalize_rule(rule) == (
            "Bash(~/.claude/plugins/cache/Dev10x-Guru/Dev10x/**/skills/foo/scripts/bar.sh:*)"
        )

    def test_collapses_double_slash_without_version(self) -> None:
        rule = "Bash(~/.claude/plugins/marketplaces/Dev10x-Guru//skills/x/scripts/y.py:*)"
        assert doctor.canonicalize_rule(rule) == (
            "Bash(~/.claude/plugins/marketplaces/Dev10x-Guru/skills/x/scripts/y.py:*)"
        )

    def test_preserves_scheme_double_slash(self) -> None:
        assert doctor.canonicalize_rule("WebFetch(domain:https://example.com)") is None


class TestCanonicalizeRulesIterable:
    def test_collects_rewrites(self) -> None:
        result = doctor.canonicalize_rules(
            [
                "Bash(/home/a/.claude/plugins/cache/Dev10x-Guru/Dev10x/0.1.0/x.sh:*)",
                "Bash(git status:*)",
                "Bash(~/.claude/plugins/cache/Dev10x-Guru/Dev10x/0.2.0/y.sh:*)",
            ]
        )
        assert result.changed == 2
        assert result.unchanged == 1

    def test_handles_empty_iterable(self) -> None:
        result = doctor.canonicalize_rules([])
        assert result.changed == 0
        assert result.unchanged == 0


class TestCanonicalizeSettingsFile:
    def test_rewrites_allow_and_deny_blocks(self, tmp_path: Path) -> None:
        settings = tmp_path / "settings.local.json"
        settings.write_text(
            json.dumps(
                {
                    "permissions": {
                        "allow": [
                            "Bash(/home/u/.claude/plugins/cache/Dev10x-Guru/Dev10x/0.71.0/skills/a.sh:*)",
                            "Bash(git status:*)",
                        ],
                        "deny": [
                            "Bash(~/.claude/plugins/cache/Dev10x-Guru/Dev10x/0.5.0/dangerous.sh:*)",
                        ],
                    }
                }
            )
        )
        result = doctor.canonicalize_settings_file(settings)
        assert result.changed == 2
        data = json.loads(settings.read_text())
        assert (
            "Bash(~/.claude/plugins/cache/Dev10x-Guru/Dev10x/**/skills/a.sh:*)"
            in data["permissions"]["allow"]
        )
        assert (
            "Bash(~/.claude/plugins/cache/Dev10x-Guru/Dev10x/**/dangerous.sh:*)"
            in data["permissions"]["deny"]
        )

    def test_dry_run_does_not_write(self, tmp_path: Path) -> None:
        settings = tmp_path / "settings.local.json"
        original = {
            "permissions": {
                "allow": [
                    "Bash(/home/u/.claude/plugins/cache/Dev10x-Guru/Dev10x/0.71.0/x.sh:*)",
                ]
            }
        }
        settings.write_text(json.dumps(original))
        result = doctor.canonicalize_settings_file(settings, dry_run=True)
        assert result.changed == 1
        assert json.loads(settings.read_text()) == original

    def test_dedupes_collisions(self, tmp_path: Path) -> None:
        settings = tmp_path / "settings.local.json"
        settings.write_text(
            json.dumps(
                {
                    "permissions": {
                        "allow": [
                            "Bash(/home/u/.claude/plugins/cache/Dev10x-Guru/Dev10x/0.71.0/x.sh:*)",
                            "Bash(~/.claude/plugins/cache/Dev10x-Guru/Dev10x/**/x.sh:*)",
                        ]
                    }
                }
            )
        )
        doctor.canonicalize_settings_file(settings)
        data = json.loads(settings.read_text())
        assert data["permissions"]["allow"] == [
            "Bash(~/.claude/plugins/cache/Dev10x-Guru/Dev10x/**/x.sh:*)"
        ]

    def test_dedupes_double_slash_polluted_against_clean(self, tmp_path: Path) -> None:
        # GH-704: a `//`-polluted literal collapses onto its clean twin.
        settings = tmp_path / "settings.local.json"
        settings.write_text(
            json.dumps(
                {
                    "permissions": {
                        "allow": [
                            "Bash(~/.claude/plugins/cache/Dev10x-Guru/Dev10x/**//x.sh:*)",
                            "Bash(~/.claude/plugins/cache/Dev10x-Guru/Dev10x/**/x.sh:*)",
                        ]
                    }
                }
            )
        )
        doctor.canonicalize_settings_file(settings)
        data = json.loads(settings.read_text())
        assert data["permissions"]["allow"] == [
            "Bash(~/.claude/plugins/cache/Dev10x-Guru/Dev10x/**/x.sh:*)"
        ]


class TestCrossContamination:
    def test_flags_foreign_project_path(self, tmp_path: Path) -> None:
        project = tmp_path / "my-project"
        project.mkdir()
        workspace = doctor.WorkspaceContext(project_root=project)
        rule = "Bash(/work/other-project/script.sh:*)"
        findings = doctor.detect_cross_contamination([rule], workspace=workspace)
        assert len(findings) == 1
        assert "outside this project root" in findings[0].reason

    def test_flags_source_repo_path_from_worktree(self, tmp_path: Path) -> None:
        source = tmp_path / "source-repo"
        source.mkdir()
        worktree = tmp_path / "wt-1"
        worktree.mkdir()
        common = source / ".git"
        common.mkdir()
        workspace = doctor.WorkspaceContext(
            project_root=worktree,
            git_common_dir=common,
        )
        assert workspace.is_worktree
        rule = f"Bash({source}/script.sh:*)"
        findings = doctor.detect_cross_contamination([rule], workspace=workspace)
        assert len(findings) == 1
        assert "worktree" in findings[0].reason.lower()

    def test_skips_paths_under_project_root(self, tmp_path: Path) -> None:
        project = tmp_path / "p"
        project.mkdir()
        (project / "script.sh").write_text("")
        workspace = doctor.WorkspaceContext(project_root=project)
        rule = f"Bash({project}/script.sh:*)"
        findings = doctor.detect_cross_contamination([rule], workspace=workspace)
        assert findings == []

    def test_skips_tmp_and_system_paths(self, tmp_path: Path) -> None:
        project = tmp_path / "p"
        project.mkdir()
        workspace = doctor.WorkspaceContext(project_root=project)
        rules = [
            "Bash(/tmp/Dev10x/x.sh:*)",
            "Bash(/usr/bin/jq:*)",
        ]
        assert doctor.detect_cross_contamination(rules, workspace=workspace) == []


class TestCatalogAndDeprecations:
    def test_catalog_path_is_package_data(self) -> None:
        # GH-264: catalog YAML must ship inside the wheel — co-located
        # with doctor.py — so `uv tool install Dev10x` users can run
        # `permission doctor apply-deprecations` without FileNotFoundError.
        module_dir = Path(doctor.__file__).resolve().parent
        assert doctor.CATALOG_PATH == module_dir / "baseline-permissions.yaml"
        assert doctor.CATALOG_PATH.is_file()

    def test_load_catalog_finds_yaml(self) -> None:
        catalog = doctor.load_catalog()
        assert catalog.version >= 1
        assert "git-core" in catalog.groups
        assert any(d.get("action") == "canonicalize" for d in catalog.deprecations)

    def test_tier_rules_filters_by_tier(self) -> None:
        catalog = doctor.load_catalog()
        tier1 = catalog.tier_rules(tiers=[1])
        assert any("git status" in r for r in tier1)
        tier3 = catalog.tier_rules(tiers=[3])
        assert any("kubectl" in r for r in tier3)

    def test_apply_deprecations_canonicalizes(self) -> None:
        catalog = doctor.load_catalog()
        rules = [
            "Bash(/home/u/.claude/plugins/cache/Dev10x-Guru/Dev10x/0.71.0/x.sh:*)",
        ]
        new_rules, outcomes = doctor.apply_deprecations(rules, catalog=catalog)
        assert len(outcomes) == 1
        assert outcomes[0].action == "canonicalize"
        assert new_rules == ["Bash(~/.claude/plugins/cache/Dev10x-Guru/Dev10x/**/x.sh:*)"]

    def test_apply_deprecations_removes(self) -> None:
        catalog = doctor.load_catalog()
        new_rules, outcomes = doctor.apply_deprecations(
            ["Bash(/tmp/claude/bin/mktmp.sh:*)"],
            catalog=catalog,
        )
        assert new_rules == []
        assert outcomes[0].action == "remove"


class TestExpandFlagOverrides:
    @pytest.mark.parametrize(
        "flag_overrides, expected",
        [
            ({}, []),
            (
                {"git clean": ["-n", "--dry-run"]},
                ["Bash(git clean -n:*)", "Bash(git clean --dry-run:*)"],
            ),
            (
                {"git branch": ["-d"], "git reset": ["--dry-run"]},
                ["Bash(git branch -d:*)", "Bash(git reset --dry-run:*)"],
            ),
            (
                {"git clean": ["-n", "-n", "--dry-run"]},
                ["Bash(git clean -n:*)", "Bash(git clean --dry-run:*)"],
            ),
        ],
    )
    def test_expansion(
        self,
        flag_overrides: dict[str, list[str]],
        expected: list[str],
    ) -> None:
        assert doctor.expand_flag_overrides(flag_overrides) == expected

    def test_deterministic_ordering_follows_mapping_then_list(self) -> None:
        flag_overrides = {
            "git clean": ["-n", "--dry-run"],
            "git branch": ["-d", "--delete"],
        }
        assert doctor.expand_flag_overrides(flag_overrides) == [
            "Bash(git clean -n:*)",
            "Bash(git clean --dry-run:*)",
            "Bash(git branch -d:*)",
            "Bash(git branch --delete:*)",
        ]


class TestGroupRulesWithFlagOverrides:
    def test_group_rules_includes_explicit_then_expanded(self) -> None:
        catalog = doctor.Catalog(
            version=1,
            last_audited="",
            groups={
                "mixed": {
                    "tier": 2,
                    "rules": ["Bash(git status:*)"],
                    "flag_overrides": {"git clean": ["-n"]},
                }
            },
            deprecations=[],
            invariants=[],
        )
        assert catalog.group_rules("mixed") == [
            "Bash(git status:*)",
            "Bash(git clean -n:*)",
        ]

    def test_group_rules_dedupes_explicit_and_expanded(self) -> None:
        catalog = doctor.Catalog(
            version=1,
            last_audited="",
            groups={
                "dup": {
                    "tier": 2,
                    "rules": ["Bash(git clean -n:*)"],
                    "flag_overrides": {"git clean": ["-n"]},
                }
            },
            deprecations=[],
            invariants=[],
        )
        assert catalog.group_rules("dup") == ["Bash(git clean -n:*)"]

    def test_group_without_flag_overrides_unchanged(self) -> None:
        catalog = doctor.Catalog(
            version=1,
            last_audited="",
            groups={"plain": {"tier": 1, "rules": ["Bash(git status:*)"]}},
            deprecations=[],
            invariants=[],
        )
        assert catalog.group_rules("plain") == ["Bash(git status:*)"]

    def test_tier_rules_includes_expanded_overrides(self) -> None:
        catalog = doctor.Catalog(
            version=1,
            last_audited="",
            groups={
                "plain": {"tier": 1, "rules": ["Bash(git status:*)"]},
                "flagged": {
                    "tier": 2,
                    "flag_overrides": {"git branch": ["-d"]},
                },
            },
            deprecations=[],
            invariants=[],
        )
        tier12 = catalog.tier_rules(tiers=[1, 2])
        assert "Bash(git status:*)" in tier12
        assert "Bash(git branch -d:*)" in tier12


class TestRealCatalogFlagOverrides:
    def test_expanded_safe_flags_present_in_tier12(self) -> None:
        catalog = doctor.load_catalog()
        tier12 = catalog.tier_rules(tiers=[1, 2])
        assert "Bash(git clean -n:*)" in tier12
        assert "Bash(git branch -d:*)" in tier12


class TestAdditionalDirectoriesDiagnosis:
    def test_returns_diagnostic_for_out_of_scope_path(self, tmp_path: Path) -> None:
        in_scope = tmp_path / "in-scope"
        in_scope.mkdir()
        out_of_scope = tmp_path / "out"
        out_of_scope.mkdir()
        target = out_of_scope / "file.txt"
        target.write_text("x")
        msg = doctor.diagnose_additional_directories(
            "Bash(cat:*)",
            path_arguments=[str(target)],
            additional_directories=[str(in_scope)],
        )
        assert msg is not None
        assert "additionalDirectories" in msg

    def test_returns_none_when_path_in_scope(self, tmp_path: Path) -> None:
        in_scope = tmp_path / "in-scope"
        in_scope.mkdir()
        target = in_scope / "file.txt"
        target.write_text("x")
        msg = doctor.diagnose_additional_directories(
            "Bash(cat:*)",
            path_arguments=[str(target)],
            additional_directories=[str(in_scope)],
        )
        assert msg is None


class TestDiscoverWorktreesParents:
    def test_finds_project_with_worktrees_dir(self, tmp_path: Path) -> None:
        project = tmp_path / "my-project"
        (project / ".worktrees").mkdir(parents=True)
        parents = doctor.discover_worktrees_parents([str(tmp_path)])
        assert project in parents

    def test_skips_projects_without_worktrees(self, tmp_path: Path) -> None:
        no_wt = tmp_path / "no-worktrees"
        no_wt.mkdir()
        parents = doctor.discover_worktrees_parents([str(tmp_path)])
        assert no_wt not in parents

    def test_deduplicates_same_parent(self, tmp_path: Path) -> None:
        project = tmp_path / "proj"
        (project / ".worktrees").mkdir(parents=True)
        # Pass root twice — should deduplicate
        parents = doctor.discover_worktrees_parents([str(tmp_path), str(tmp_path)])
        assert parents.count(project) == 1

    def test_returns_empty_for_nonexistent_root(self, tmp_path: Path) -> None:
        parents = doctor.discover_worktrees_parents([str(tmp_path / "does-not-exist")])
        assert parents == []

    def test_root_itself_is_checked(self, tmp_path: Path) -> None:
        # If the root itself has a .worktrees dir, it is returned
        (tmp_path / ".worktrees").mkdir()
        parents = doctor.discover_worktrees_parents([str(tmp_path)])
        assert tmp_path in parents


class TestAnchorWorktreeRoots:
    def _make_settings(self, path: Path, allow: list[str] | None = None) -> Path:
        settings = path / ".claude" / "settings.local.json"
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text(
            __import__("json").dumps(
                {"permissions": {"allow": allow or [], "additionalDirectories": []}}
            )
        )
        return settings

    def test_anchors_parent_in_additional_directories(self, tmp_path: Path) -> None:
        project = tmp_path / "proj"
        (project / ".worktrees").mkdir(parents=True)
        settings = self._make_settings(tmp_path)

        result = doctor.anchor_worktree_roots(
            [settings],
            roots=[str(tmp_path)],
            dry_run=False,
        )

        import json

        data = json.loads(settings.read_text())
        assert str(project) in data["permissions"]["additionalDirectories"]
        assert result.total_changes > 0

    def test_dry_run_does_not_write(self, tmp_path: Path) -> None:
        project = tmp_path / "proj"
        (project / ".worktrees").mkdir(parents=True)
        settings = self._make_settings(tmp_path)
        original = settings.read_text()

        result = doctor.anchor_worktree_roots(
            [settings],
            roots=[str(tmp_path)],
            dry_run=True,
        )

        assert settings.read_text() == original
        # dry_run still reports findings
        assert len(result.findings) > 0

    def test_no_changes_when_parent_already_registered(self, tmp_path: Path) -> None:
        project = tmp_path / "proj"
        (project / ".worktrees").mkdir(parents=True)
        settings = project / ".claude" / "settings.local.json"
        settings.parent.mkdir(parents=True, exist_ok=True)
        import json

        settings.write_text(
            json.dumps(
                {
                    "permissions": {
                        "allow": [],
                        "additionalDirectories": [str(project)],
                    }
                }
            )
        )

        result = doctor.anchor_worktree_roots(
            [settings],
            roots=[str(tmp_path)],
            dry_run=False,
        )
        assert result.total_changes == 0

    def test_flags_relative_skill_script_rule(self, tmp_path: Path) -> None:
        settings = self._make_settings(
            tmp_path,
            allow=["Bash(.claude/skills/git-commit/scripts/git-commit.py:*)"],
        )

        result = doctor.anchor_worktree_roots(
            [settings],
            roots=[str(tmp_path)],
            dry_run=False,
        )

        skill_script_findings = [f for f in result.findings if f.scope == "skill-script"]
        assert len(skill_script_findings) == 1
        assert skill_script_findings[0].rule is not None
        assert ".claude/skills/" in skill_script_findings[0].rule

    def test_stable_absolute_rule_not_flagged(self, tmp_path: Path) -> None:
        settings = self._make_settings(
            tmp_path,
            allow=["Bash(~/.claude/plugins/cache/Dev10x-Guru/Dev10x/**/git-commit.py:*)"],
        )

        result = doctor.anchor_worktree_roots(
            [settings],
            roots=[str(tmp_path)],
            dry_run=False,
        )

        skill_script_findings = [f for f in result.findings if f.scope == "skill-script"]
        assert len(skill_script_findings) == 0


def _write_settings(path: Path, *, allow: list[str]) -> Path:
    settings = path / ".claude" / "settings.local.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps({"permissions": {"allow": allow}}))
    return settings


class TestCrossContaminationForRoot:
    def test_reports_missing_settings_file(self, tmp_path: Path) -> None:
        result = doctor.cross_contamination_for_root(root=tmp_path)

        assert result["exit_code"] == 0
        assert "No settings file at" in result["messages"][0]

    def test_reports_no_findings(self, tmp_path: Path) -> None:
        _write_settings(tmp_path, allow=["Bash(git status:*)"])

        result = doctor.cross_contamination_for_root(root=tmp_path)

        assert result["exit_code"] == 0
        assert "no cross-contamination findings" in result["messages"][0]

    def test_reports_findings_with_detail(self, tmp_path: Path) -> None:
        _write_settings(tmp_path, allow=["Bash(/work/other-project/script.sh:*)"])

        result = doctor.cross_contamination_for_root(root=tmp_path)

        joined = "\n".join(result["messages"])
        assert "1 findings" in joined
        assert "! Bash(/work/other-project/script.sh:*)" in joined
        assert "reason:" in joined

    def test_quiet_suppresses_detail(self, tmp_path: Path) -> None:
        _write_settings(tmp_path, allow=["Bash(/work/other-project/script.sh:*)"])

        result = doctor.cross_contamination_for_root(root=tmp_path, quiet=True)

        joined = "\n".join(result["messages"])
        assert "! Bash(/work/other-project/script.sh:*)" in joined
        assert "reason:" not in joined


class TestApplyDeprecationsToFiles:
    def _catalog(self, deprecations: list[dict]) -> object:
        return doctor.Catalog(
            version=1,
            last_audited="",
            groups={},
            deprecations=deprecations,
            invariants=[],
        )

    def test_removes_and_writes(self, tmp_path: Path) -> None:
        settings = _write_settings(
            tmp_path,
            allow=["Bash(/tmp/claude/bin/mktmp.sh:*)", "Bash(git status:*)"],
        )
        catalog = self._catalog([{"pattern": "mktmp", "action": "remove", "reason": "retired"}])

        result = doctor.apply_deprecations_to_files([settings], catalog=catalog)

        assert result["exit_code"] == 0
        joined = "\n".join(result["messages"])
        assert "REMOVE" in joined
        assert "Applied 1 deprecation actions." in joined
        data = json.loads(settings.read_text())
        assert data["permissions"]["allow"] == ["Bash(git status:*)"]

    def test_canonicalize_action(self, tmp_path: Path) -> None:
        pinned = "Bash(/home/u/.claude/plugins/cache/Dev10x-Guru/Dev10x/0.71.0/x.sh:*)"
        settings = _write_settings(tmp_path, allow=[pinned])
        catalog = self._catalog(
            [{"pattern": r"cache/.+/\d+\.\d+\.\d+/", "action": "canonicalize", "reason": "pin"}]
        )

        result = doctor.apply_deprecations_to_files([settings], catalog=catalog)

        joined = "\n".join(result["messages"])
        assert "CANON" in joined
        data = json.loads(settings.read_text())
        assert data["permissions"]["allow"] == [
            "Bash(~/.claude/plugins/cache/Dev10x-Guru/Dev10x/**/x.sh:*)"
        ]

    def test_unknown_action_keeps_rule(self, tmp_path: Path) -> None:
        settings = _write_settings(tmp_path, allow=["Bash(flagged:*)"])
        catalog = self._catalog([{"pattern": "flagged", "action": "flag", "reason": "review"}])

        result = doctor.apply_deprecations_to_files([settings], catalog=catalog)

        joined = "\n".join(result["messages"])
        assert "? FLAG:" in joined
        data = json.loads(settings.read_text())
        assert data["permissions"]["allow"] == ["Bash(flagged:*)"]

    def test_dry_run_does_not_write(self, tmp_path: Path) -> None:
        settings = _write_settings(tmp_path, allow=["Bash(/tmp/claude/bin/mktmp.sh:*)"])
        catalog = self._catalog([{"pattern": "mktmp", "action": "remove", "reason": "retired"}])
        original = settings.read_text()

        result = doctor.apply_deprecations_to_files([settings], catalog=catalog, dry_run=True)

        assert "Would apply 1 deprecation actions." in "\n".join(result["messages"])
        assert settings.read_text() == original


class TestEnableGroupInFiles:
    def test_adds_rules_and_writes(self, tmp_path: Path) -> None:
        settings = _write_settings(tmp_path, allow=[])

        result = doctor.enable_group_in_files(
            [settings],
            rules=["Bash(foo:*)"],
            group_name="g",
        )

        assert result["exit_code"] == 0
        joined = "\n".join(result["messages"])
        assert "adding 1 rules from 'g'" in joined
        assert "Added 1 rules from group 'g'." in joined
        data = json.loads(settings.read_text())
        assert data["permissions"]["allow"] == ["Bash(foo:*)"]

    def test_skips_rules_already_present(self, tmp_path: Path) -> None:
        settings = _write_settings(tmp_path, allow=["Bash(foo:*)"])
        original = settings.read_text()

        result = doctor.enable_group_in_files(
            [settings],
            rules=["Bash(foo:*)"],
            group_name="g",
        )

        assert "Added 0 rules from group 'g'." in "\n".join(result["messages"])
        assert settings.read_text() == original

    def test_dry_run_does_not_write(self, tmp_path: Path) -> None:
        settings = _write_settings(tmp_path, allow=[])
        original = settings.read_text()

        result = doctor.enable_group_in_files(
            [settings],
            rules=["Bash(foo:*)"],
            group_name="g",
            dry_run=True,
        )

        assert "Would add 1 rules from group 'g'." in "\n".join(result["messages"])
        assert settings.read_text() == original
