"""GH-1261: resolve the IDE pin, and seed against the shipped catalog."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from dev10x.domain.common.ide_choice import Ide, apply_ide_selection, ide_inventory
from dev10x.skills.permission.ide_resolve import ide_source, resolve_ide


def _write(path: Path, payload: dict) -> None:
    path.write_text(yaml.safe_dump(payload))


@pytest.fixture
def friction(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "friction.yaml"
    monkeypatch.setattr(
        "dev10x.domain.documents.friction_yaml.Dev10xConfigDir.friction_yaml",
        classmethod(lambda cls: path),
    )
    return path


class TestResolveIde:
    def test_an_unpinned_project_has_no_ide(self, friction: Path, tmp_path: Path) -> None:
        root = str(tmp_path / "repo")

        assert resolve_ide(toplevel=root) is Ide.NONE
        assert ide_source(toplevel=root) == "default"

    def test_a_project_entry_wins(self, friction: Path, tmp_path: Path) -> None:
        root = str(tmp_path / "repo")
        _write(friction, {"projects": [{"match": [root], "ide": "pycharm"}]})

        assert resolve_ide(toplevel=root) is Ide.PYCHARM
        assert ide_source(toplevel=root) == "project"

    def test_the_defaults_block_applies_when_no_entry_matches(
        self, friction: Path, tmp_path: Path
    ) -> None:
        _write(friction, {"defaults": {"ide": "pycharm"}})
        root = str(tmp_path / "repo")

        assert resolve_ide(toplevel=root) is Ide.PYCHARM
        assert ide_source(toplevel=root) == "defaults"

    def test_an_unrecognised_value_degrades_to_none(self, friction: Path, tmp_path: Path) -> None:
        # A typo must not blow up a seeding run mid-flight, and must not
        # seed some other IDE's rules either.
        root = str(tmp_path / "repo")
        _write(friction, {"projects": [{"match": [root], "ide": "emacs"}]})

        assert resolve_ide(toplevel=root) is Ide.NONE


class TestShippedCatalog:
    @pytest.fixture
    def catalog(self, projects_yaml: Path) -> dict:
        return yaml.safe_load(projects_yaml.read_text())

    def test_pycharm_has_a_block(self, catalog: dict) -> None:
        assert ide_inventory(config=catalog)[Ide.PYCHARM]

    def test_selecting_pycharm_seeds_its_read_tools(self, catalog: dict) -> None:
        merged = apply_ide_selection(config=catalog, ide=Ide.PYCHARM)

        assert "mcp__pycharm__read_file" in merged["base_permissions"]

    def test_selecting_pycharm_seeds_its_edit_tools(self, catalog: dict) -> None:
        # Tier 3 is deliberate: an equivalent Edit sequence is already
        # auto-approved under defaultMode acceptEdits, so refusing the
        # IDE path is the GH-1215 anti-pattern.
        merged = apply_ide_selection(config=catalog, ide=Ide.PYCHARM)

        assert "mcp__pycharm__rename_refactoring" in merged["base_permissions"]

    @pytest.mark.parametrize(
        "tool",
        [
            "mcp__pycharm__execute_terminal_command",
            "mcp__pycharm__execute_code_on_kernel",
            "mcp__pycharm__execute_tool",
        ],
    )
    def test_the_shell_equivalents_are_never_seeded_as_allows(
        self, catalog: dict, tool: str
    ) -> None:
        for ide in Ide:
            merged = apply_ide_selection(config=catalog, ide=ide)
            assert tool not in merged["base_permissions"]

    @pytest.mark.parametrize(
        "tool",
        [
            "mcp__pycharm__execute_terminal_command",
            "mcp__pycharm__execute_code_on_kernel",
            "mcp__pycharm__execute_tool",
        ],
    )
    def test_the_shell_equivalents_are_denied_without_pinning_an_ide(
        self, catalog: dict, tool: str
    ) -> None:
        # The hazard depends on the server being installed, not on the
        # user having chosen it — so the deny cannot live behind the pin.
        merged = apply_ide_selection(config=catalog, ide=Ide.NONE)

        assert tool in merged["base_denies"]

    def test_no_ide_selection_seeds_no_pycharm_allow(self, catalog: dict) -> None:
        merged = apply_ide_selection(config=catalog, ide=Ide.NONE)

        assert not any("pycharm" in rule for rule in merged["base_permissions"])
