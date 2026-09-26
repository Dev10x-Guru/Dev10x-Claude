"""Tests for the Tier-2 `projects:` list scan (GH-1375, ADR-0026)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from dev10x.domain.common.result import err, ok
from dev10x.domain.dev10x_paths import Dev10xConfigDir
from dev10x.domain.project_match import MatchScheme, ProjectsStatus
from dev10x.session.preset_pin import RepoIdentity
from dev10x.session.projects_scan import (
    NO_REPO_ROOT_REASON,
    scan_projects_lists,
)


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


@pytest.fixture
def in_repo(tmp_path: Path):
    """Resolve both targets: a checkout at tmp_path owned by `org/repo`."""
    identity = RepoIdentity(name="repo", root=str(tmp_path), source="git-common-dir")
    with (
        patch("dev10x.session.projects_scan.resolve_repo_identity", return_value=ok(identity)),
        patch(
            "dev10x.session.projects_scan.resolve_name_with_owner",
            return_value=ok("org/repo"),
        ),
    ):
        yield tmp_path


def _report_for(reports, *, name: str):
    return next(report for report in reports if report.source.endswith(name))


class TestScanProjectsLists:
    def test_absent_files_produce_no_reports(self, in_repo: Path) -> None:
        assert scan_projects_lists() == []

    def test_friction_is_scanned_under_the_path_scheme(self, in_repo: Path) -> None:
        _write(
            Dev10xConfigDir.friction_yaml(),
            f"projects:\n  - match: ['{in_repo}']\n    supervisor_review: none\n",
        )
        report = _report_for(scan_projects_lists(), name="friction.yaml")
        assert report.scheme is MatchScheme.PATH
        assert report.status is ProjectsStatus.MATCHED

    def test_an_org_glob_in_friction_is_reported_as_no_match(self, in_repo: Path) -> None:
        _write(
            Dev10xConfigDir.friction_yaml(),
            "projects:\n  - match: ['Dev10x-Guru/*']\n    supervisor_review: none\n",
        )
        report = _report_for(scan_projects_lists(), name="friction.yaml")
        assert report.status is ProjectsStatus.NO_MATCH
        assert report.shape_warnings

    def test_settings_and_gitmoji_are_scanned_under_the_repo_scheme(self, in_repo: Path) -> None:
        _write(
            Dev10xConfigDir.settings_pr_merge_yaml(),
            "projects:\n  - match_repo: ['org/*']\n    strategy: rebase\n",
        )
        _write(
            Dev10xConfigDir.gitmoji_yaml(),
            "projects:\n  - match_repo: ['other/*']\n    strategy: x\n",
        )
        reports = scan_projects_lists()
        assert _report_for(reports, name="settings-pr-merge.yaml").status is ProjectsStatus.MATCHED
        assert _report_for(reports, name="gitmoji.yaml").status is ProjectsStatus.NO_MATCH

    def test_playbook_overrides_are_scanned(self, in_repo: Path) -> None:
        _write(
            Dev10xConfigDir.playbooks_dir() / "work-on.yaml",
            "projects:\n  - match: ['org/*']\n",
        )
        report = _report_for(scan_projects_lists(), name="work-on.yaml")
        assert report.scheme is MatchScheme.REPO
        assert report.deprecated_alias_indexes == (0,)

    def test_no_origin_remote_reports_unresolved_not_no_match(self, tmp_path: Path) -> None:
        """A repo-addressed list that was never evaluated says so (ADR-0026)."""
        _write(
            Dev10xConfigDir.settings_pr_merge_yaml(),
            "projects:\n  - match_repo: ['org/*']\n",
        )
        identity = RepoIdentity(name="repo", root=str(tmp_path), source="git-common-dir")
        with (
            patch("dev10x.session.projects_scan.resolve_repo_identity", return_value=ok(identity)),
            patch(
                "dev10x.session.projects_scan.resolve_name_with_owner",
                return_value=err("no `origin` remote"),
            ),
        ):
            report = _report_for(scan_projects_lists(), name="settings-pr-merge.yaml")
        assert report.status is ProjectsStatus.UNRESOLVED
        assert report.unresolved_reason == "no `origin` remote"

    def test_outside_a_git_repo_the_path_list_is_unresolved(self, tmp_path: Path) -> None:
        _write(Dev10xConfigDir.friction_yaml(), "projects:\n  - match: ['*/repo']\n")
        with (
            patch(
                "dev10x.session.projects_scan.resolve_repo_identity",
                return_value=err("Not in a git repository"),
            ),
            patch(
                "dev10x.session.projects_scan.resolve_name_with_owner",
                return_value=err("no origin"),
            ),
        ):
            report = _report_for(scan_projects_lists(), name="friction.yaml")
        assert report.status is ProjectsStatus.UNRESOLVED
        assert report.unresolved_reason == NO_REPO_ROOT_REASON


class TestMalformedFriction:
    def test_malformed_friction_degrades_to_absent(self, in_repo: Path) -> None:
        """GH-1450: routed through config_io.load_yaml, a present but
        malformed friction.yaml degrades to an empty mapping (ABSENT
        status) rather than raising or being silently dropped."""
        _write(Dev10xConfigDir.friction_yaml(), "projects: [\n")
        report = _report_for(scan_projects_lists(), name="friction.yaml")
        assert report.status is ProjectsStatus.ABSENT

    def test_non_mapping_friction_degrades_to_absent(self, in_repo: Path) -> None:
        _write(Dev10xConfigDir.friction_yaml(), "- a\n- b\n")
        report = _report_for(scan_projects_lists(), name="friction.yaml")
        assert report.status is ProjectsStatus.ABSENT
