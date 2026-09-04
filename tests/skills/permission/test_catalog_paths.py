"""GH-1190: the shipped catalog is located by resolver, not by parents[4]."""

from __future__ import annotations

from pathlib import Path

import pytest

from dev10x.skills.permission import (
    catalog_paths,
    clean_project_files,
    doctor,
    merge_worktree_permissions,
    update_paths,
)
from dev10x.skills.permission.catalog_paths import shipped_projects_catalog


class TestShippedProjectsCatalog:
    def test_appends_the_catalog_relpath_to_the_given_root(self, tmp_path: Path) -> None:
        resolved = shipped_projects_catalog(plugin_root=tmp_path)
        assert resolved == tmp_path / "skills" / "upgrade-cleanup" / "projects.yaml"

    def test_resolves_against_this_checkout_by_default(self) -> None:
        resolved = shipped_projects_catalog()
        assert resolved is not None
        assert resolved.is_file()

    def test_returns_none_when_no_plugin_root_exists(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # An installed wheel with no plugin cache and no
        # $CLAUDE_PLUGIN_ROOT. `None` must surface as "absent", never as
        # a plausible-looking wrong path — that is the GH-1190 defect.
        monkeypatch.setattr(catalog_paths, "resolve_plugin_root", lambda: None)
        assert shipped_projects_catalog() is None

    def test_no_call_site_hardcodes_a_parents_hop(self) -> None:
        # The whole point of GH-1190: a fixed parents[N] walk is correct
        # from a checkout and wrong from an installed wheel, silently.
        modules = (
            clean_project_files,
            doctor,
            merge_worktree_permissions,
            update_paths,
        )
        for module in modules:
            source = Path(module.__file__).read_text()
            assert "parents[4]" not in source, module.__name__


class TestCallSitesAgree:
    def test_every_call_site_resolves_to_the_same_catalog(self) -> None:
        expected = shipped_projects_catalog()
        assert update_paths.PLUGIN_CONFIG == expected
        assert clean_project_files.PLUGIN_CONFIG == expected
        assert merge_worktree_permissions.PLUGIN_CONFIG == expected
        assert doctor.PROJECTS_CATALOG_PATH == expected
