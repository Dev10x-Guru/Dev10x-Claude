"""GH-1190: the shipped catalog is located by resolver, not by parents[4]."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from dev10x.skills.permission.catalog_paths import shipped_projects_catalog
from dev10x.skills.permission.config import parse_config

from dev10x.skills.permission import (
    catalog_load,
    catalog_paths,
    clean_project_files,
    doctor,
    merge_worktree_permissions,
    update_paths,
)


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
            catalog_load,
            clean_project_files,
            doctor,
            merge_worktree_permissions,
            update_paths,
        )
        for module in modules:
            source = Path(module.__file__).read_text()
            assert "parents[4]" not in source, module.__name__


@pytest.fixture
def fragmented_catalog(tmp_path: Path) -> Path:
    catalog = tmp_path / "projects.yaml"
    catalog.write_text("roots: []\nbase_permissions:\n  - core-rule\n")
    fragments = tmp_path / catalog_paths.FRAGMENTS_DIRNAME
    fragments.mkdir()
    (fragments / "scoping.yaml").write_text("tracker_permissions:\n  linear:\n    - lin\n")
    (fragments / "coding.yaml").write_text("base_permissions:\n  - coding-rule\n")
    return catalog


@pytest.fixture
def plain_catalog(tmp_path: Path) -> Path:
    catalog = tmp_path / "projects.yaml"
    catalog.write_text("# header\nbase_permissions:\n  - only\n")
    return catalog


class TestCatalogFragments:
    def test_fragment_dir_sits_beside_the_catalog(self, plain_catalog: Path) -> None:
        dirs = catalog_paths.catalog_fragment_dirs(catalog_path=plain_catalog)
        assert dirs == (plain_catalog.parent / "projects.d",)

    def test_files_list_the_catalog_then_fragments_in_plugin_order(
        self, fragmented_catalog: Path
    ) -> None:
        fragments = fragmented_catalog.parent / "projects.d"
        files = catalog_paths.catalog_files(catalog_path=fragmented_catalog)
        assert files == [fragmented_catalog, fragments / "scoping.yaml", fragments / "coding.yaml"]

    def test_merges_fragments_into_the_catalog(self, fragmented_catalog: Path) -> None:
        document = catalog_paths.load_catalog_document(catalog_path=fragmented_catalog)
        assert document == {
            "roots": [],
            "base_permissions": ["core-rule", "coding-rule"],
            "tracker_permissions": {"linear": ["lin"]},
        }

    def test_a_catalog_without_fragments_loads_unchanged(self, plain_catalog: Path) -> None:
        document = catalog_paths.load_catalog_document(catalog_path=plain_catalog)
        assert document == {"base_permissions": ["only"]}

    def test_explicit_fragment_dirs_override_the_default(
        self, fragmented_catalog: Path, tmp_path: Path
    ) -> None:
        other = tmp_path / "plugins" / "qa"
        other.mkdir(parents=True)
        (other / "qa.yaml").write_text("base_permissions:\n  - qa-rule\n")
        document = catalog_paths.load_catalog_document(
            catalog_path=fragmented_catalog,
            fragment_dirs=[fragmented_catalog.parent / "projects.d", other],
        )
        assert document["base_permissions"] == ["core-rule", "qa-rule", "coding-rule"]

    def test_text_of_a_plain_catalog_is_the_file_verbatim(self, plain_catalog: Path) -> None:
        text = catalog_paths.catalog_text(catalog_path=plain_catalog)
        assert text == plain_catalog.read_text()

    def test_text_of_a_fragmented_catalog_parses_to_the_merge(
        self, fragmented_catalog: Path
    ) -> None:
        """GH-1589: concatenating files that repeat `base_permissions` kept
        only the last copy of the key, dropping every core rule."""
        text = catalog_paths.catalog_text(catalog_path=fragmented_catalog)

        assert yaml.safe_load(text) == catalog_paths.load_catalog_document(
            catalog_path=fragmented_catalog
        )

    def test_text_of_a_fragmented_catalog_keeps_the_base_header(self, tmp_path: Path) -> None:
        catalog = tmp_path / "projects.yaml"
        catalog.write_text("# header line\n\n# second\nroots: []\n# body comment\n")
        fragments = tmp_path / catalog_paths.FRAGMENTS_DIRNAME
        fragments.mkdir()
        (fragments / "qa.yaml").write_text("base_permissions:\n  - qa-rule\n")

        text = catalog_paths.catalog_text(catalog_path=catalog)

        assert text == "# header line\n\n# second\nroots: []\nbase_permissions:\n- qa-rule\n"


class TestParseConfigReadsFragments:
    def test_every_parse_config_caller_sees_the_merged_catalog(
        self, fragmented_catalog: Path
    ) -> None:
        config = parse_config(fragmented_catalog)
        assert config["tracker_permissions"] == {"linear": ["lin"]}


class TestCallSitesAgree:
    def test_every_call_site_resolves_to_the_same_catalog(self) -> None:
        expected = shipped_projects_catalog()
        assert update_paths.PLUGIN_CONFIG == expected
        assert clean_project_files.PLUGIN_CONFIG == expected
        assert merge_worktree_permissions.PLUGIN_CONFIG == expected
        assert doctor.PROJECTS_CATALOG_PATH == expected
