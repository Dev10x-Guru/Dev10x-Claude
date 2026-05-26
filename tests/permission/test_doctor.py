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
