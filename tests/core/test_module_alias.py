"""Old-path aliases for Stage A moves (ADR-0034, GH-1533)."""

from __future__ import annotations

import importlib
import sys
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from dev10x.core.module_alias import PackageAlias, alias_module, alias_package


@pytest.fixture
def toy_tree(tmp_path: Path) -> Iterator[Path]:
    new_pkg = tmp_path / "toyalias_new"
    (new_pkg / "sub").mkdir(parents=True)
    (new_pkg / "__init__.py").write_text("VALUE = 'pkg'\n")
    (new_pkg / "leaf.py").write_text("STATE = []\n")
    (new_pkg / "sub" / "__init__.py").write_text("")
    (new_pkg / "sub" / "deep.py").write_text("def answer() -> int:\n    return 42\n")
    (tmp_path / "toyalias_single.py").write_text("NAME = 'single'\n")
    sys.path.insert(0, str(tmp_path))
    meta_path = list(sys.meta_path)
    yield tmp_path
    sys.path.remove(str(tmp_path))
    sys.meta_path[:] = meta_path
    for name in [name for name in sys.modules if name.startswith("toyalias")]:
        del sys.modules[name]


@pytest.mark.usefixtures("toy_tree")
class TestAliasPackage:
    def test_old_name_is_the_new_package(self) -> None:
        package = alias_package(old="toyalias_old", new="toyalias_new")

        assert sys.modules["toyalias_old"] is package is importlib.import_module("toyalias_new")

    def test_submodule_is_one_object_under_both_names(self) -> None:
        alias_package(old="toyalias_old", new="toyalias_new")

        old = importlib.import_module("toyalias_old.sub.deep")

        assert old is importlib.import_module("toyalias_new.sub.deep")

    def test_patching_the_old_path_reaches_the_new_module(self) -> None:
        alias_package(old="toyalias_old", new="toyalias_new")
        new = importlib.import_module("toyalias_new.sub.deep")

        with patch("toyalias_old.sub.deep.answer", return_value=7):
            assert new.answer() == 7

    def test_module_keeps_its_own_spec(self) -> None:
        alias_package(old="toyalias_old", new="toyalias_new")

        leaf = importlib.import_module("toyalias_old.leaf")

        assert leaf.__spec__ is not None
        assert leaf.__spec__.name == "toyalias_new.leaf"

    def test_missing_submodule_still_raises(self) -> None:
        alias_package(old="toyalias_old", new="toyalias_new")

        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("toyalias_old.absent")

    def test_installs_one_finder_per_old_name(self) -> None:
        alias_package(old="toyalias_old", new="toyalias_new")
        alias_package(old="toyalias_old", new="toyalias_new")

        finders = [
            finder
            for finder in sys.meta_path
            if isinstance(finder, PackageAlias) and finder.old == "toyalias_old"
        ]

        assert len(finders) == 1


class TestPackageAliasTarget:
    @pytest.mark.parametrize(
        ("fullname", "expected"),
        [
            ("old.pkg.leaf", "new.place.leaf"),
            ("old.pkg", None),
            ("old.pkgother.leaf", None),
            ("unrelated", None),
        ],
    )
    def test_maps_only_names_below_the_old_package(
        self,
        fullname: str,
        expected: str | None,
    ) -> None:
        finder = PackageAlias(old="old.pkg", new="new.place")

        assert finder.target_of(fullname=fullname) == expected


class TestMovedPackages:
    @pytest.mark.parametrize(
        ("old", "new"),
        [
            ("dev10x.domain", "dev10x.core.domain"),
            ("dev10x.domain.cwd_resolver", "dev10x.core.domain.cwd_resolver"),
            ("dev10x.domain.common.result", "dev10x.core.domain.common.result"),
            ("dev10x.domain.events.hook_input", "dev10x.core.domain.events.hook_input"),
            ("dev10x.subprocess_utils", "dev10x.core.subprocess_utils"),
            ("dev10x.subprocess_timeouts", "dev10x.core.subprocess_timeouts"),
            ("dev10x.config", "dev10x.core.config"),
            ("dev10x.config.friction_presets", "dev10x.core.config.friction_presets"),
            ("dev10x.platform", "dev10x.core.platform"),
            ("dev10x.platform.registry", "dev10x.core.platform.registry"),
            ("dev10x.utilities", "dev10x.core.utilities"),
            ("dev10x.utilities.slack", "dev10x.core.utilities.slack"),
            ("dev10x.github._gateway", "dev10x.core.github._gateway"),
            ("dev10x.github.app_auth", "dev10x.core.github.app_auth"),
            ("dev10x.github.app_api", "dev10x.core.github.app_api"),
            ("dev10x.spec", "dev10x.core.spec"),
            ("dev10x.spec.drift_detector", "dev10x.core.spec.drift_detector"),
            ("dev10x.validators", "dev10x.core.validators"),
            ("dev10x.validators.registry", "dev10x.core.validators.registry"),
            ("dev10x.validators.skill_redirect", "dev10x.core.validators.skill_redirect"),
        ],
    )
    def test_old_path_is_the_moved_module(self, old: str, new: str) -> None:
        assert importlib.import_module(old) is importlib.import_module(new)


@pytest.mark.usefixtures("toy_tree")
class TestAliasModule:
    def test_old_name_is_the_new_module(self) -> None:
        module = alias_module(old="toyalias_single_old", new="toyalias_single")

        assert sys.modules["toyalias_single_old"] is module
        assert module.NAME == "single"
