"""Old-path aliases for Stage A moves (ADR-0034, GH-1533)."""

from __future__ import annotations

import importlib
import sys
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from dev10x.core.module_alias import (
    PackageAlias,
    alias_module,
    alias_package,
    alias_submodules,
)


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


@pytest.fixture
def partial_tree(toy_tree: Path) -> Path:
    old_pkg = toy_tree / "toyalias_partial"
    old_pkg.mkdir()
    (old_pkg / "__init__.py").write_text(
        "from dev10x.core.module_alias import alias_submodules\n"
        "alias_submodules(old=__name__, new='toyalias_new')\n"
    )
    (old_pkg / "stays.py").write_text("WHERE = 'old'\n")
    return toy_tree


@pytest.mark.usefixtures("partial_tree")
class TestAliasSubmodules:
    def test_moved_submodule_is_the_new_module(self) -> None:
        moved = importlib.import_module("toyalias_partial.sub.deep")

        assert moved is importlib.import_module("toyalias_new.sub.deep")

    def test_unmoved_submodule_loads_from_the_old_package(self) -> None:
        stays = importlib.import_module("toyalias_partial.stays")

        assert stays.WHERE == "old"
        assert stays.__name__ == "toyalias_partial.stays"

    def test_old_package_stays_its_own_package(self) -> None:
        old = importlib.import_module("toyalias_partial")

        assert old is not importlib.import_module("toyalias_new")

    def test_from_import_binds_the_moved_module(self) -> None:
        from toyalias_partial import leaf  # type: ignore[import-not-found]

        assert leaf is importlib.import_module("toyalias_new.leaf")

    def test_installs_one_finder_per_old_name(self) -> None:
        importlib.import_module("toyalias_partial")
        alias_submodules(old="toyalias_partial", new="toyalias_new")

        finders = [
            finder
            for finder in sys.meta_path
            if isinstance(finder, PackageAlias) and finder.old == "toyalias_partial"
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
            ("dev10x.hooks.session", "dev10x.core.hooks.session"),
            ("dev10x.hooks.edit_validator", "dev10x.core.hooks.edit_validator"),
            ("dev10x.hooks.stop_verdict", "dev10x.core.hooks.stop_verdict"),
            ("dev10x.permission", "dev10x.core.permission"),
            ("dev10x.permission.service", "dev10x.core.permission.service"),
            ("dev10x.session.service", "dev10x.core.session.service"),
            ("dev10x.session.preset_pin", "dev10x.core.session.preset_pin"),
            ("dev10x.session.tracker_pin", "dev10x.core.session.tracker_pin"),
            ("dev10x.mcp._app", "dev10x.core.mcp._app"),
            ("dev10x.mcp.transport", "dev10x.core.mcp.transport"),
            ("dev10x.mcp.daemon", "dev10x.core.mcp.daemon"),
            ("dev10x.mcp.wiring", "dev10x.core.mcp.wiring"),
            ("dev10x.mcp.strict_args", "dev10x.core.mcp.strict_args"),
            ("dev10x.mcp.gate_tools", "dev10x.core.mcp.gate_tools"),
            ("dev10x.mcp.gate_query", "dev10x.core.mcp.gate_query"),
            ("dev10x.skills.playbook", "dev10x.core.skills.playbook"),
            ("dev10x.skills.playbook.discovery", "dev10x.core.skills.playbook.discovery"),
            ("dev10x.skills.doctor", "dev10x.core.skills.doctor"),
            (
                "dev10x.skills.doctor.strategies.ask_shadows_allow",
                "dev10x.core.skills.doctor.strategies.ask_shadows_allow",
            ),
            ("dev10x.skills.permission", "dev10x.core.skills.permission"),
            (
                "dev10x.skills.permission.update_paths",
                "dev10x.core.skills.permission.update_paths",
            ),
            (
                "dev10x.skills.permission_investigator",
                "dev10x.core.skills.permission_investigator",
            ),
            (
                "dev10x.skills.permission_investigator.matrix",
                "dev10x.core.skills.permission_investigator.matrix",
            ),
            ("dev10x.plan", "dev10x.tasks.plan"),
            ("dev10x.plan.service", "dev10x.tasks.plan.service"),
            ("dev10x.session.task_index", "dev10x.tasks.session.task_index"),
            ("dev10x.hooks.task_plan_sync", "dev10x.tasks.hooks.task_plan_sync"),
            ("dev10x.mcp.plan_tools", "dev10x.tasks.mcp.plan_tools"),
            ("dev10x.mcp.task_index_tools", "dev10x.tasks.mcp.task_index_tools"),
            ("dev10x.skills.bus", "dev10x.comm.skills.bus"),
            ("dev10x.skills.bus.maildir", "dev10x.comm.skills.bus.maildir"),
            ("dev10x.skills.notifications", "dev10x.comm.skills.notifications"),
            (
                "dev10x.skills.notifications.slack_notify",
                "dev10x.comm.skills.notifications.slack_notify",
            ),
            (
                "dev10x.skills.notifications.gchat_notify",
                "dev10x.comm.skills.notifications.gchat_notify",
            ),
            ("dev10x.mcp.server_db", "dev10x.db.mcp.server_db"),
            ("dev10x.skills.database", "dev10x.db.skills.database"),
            ("dev10x.audit", "dev10x.teach.audit"),
            ("dev10x.audit.log_reader", "dev10x.teach.audit.log_reader"),
            ("dev10x.skill_index", "dev10x.teach.skill_index"),
            ("dev10x.skill_index.catalog", "dev10x.teach.skill_index.catalog"),
            ("dev10x.skills.audit", "dev10x.teach.skills.audit"),
            ("dev10x.skills.audit.privacy", "dev10x.teach.skills.audit.privacy"),
            ("dev10x.mcp.audit_tools", "dev10x.teach.mcp.audit_tools"),
            ("dev10x.scope", "dev10x.scoping.scope"),
            ("dev10x.scope.norms_renderer", "dev10x.scoping.scope.norms_renderer"),
            ("dev10x.git", "dev10x.coding.git"),
            ("dev10x.github", "dev10x.coding.github"),
            ("dev10x.github.pulls", "dev10x.coding.github.pulls"),
            ("dev10x.github._gateway", "dev10x.core.github._gateway"),
            ("dev10x.github.app_api", "dev10x.core.github.app_api"),
            ("dev10x.github.app_auth", "dev10x.core.github.app_auth"),
            ("dev10x.coding.github._gateway", "dev10x.core.github._gateway"),
            ("dev10x.monitor", "dev10x.coding.monitor"),
            ("dev10x.runner", "dev10x.coding.runner"),
            ("dev10x.release", "dev10x.coding.release"),
            ("dev10x.skills.merge", "dev10x.coding.skills.merge"),
            ("dev10x.skills.merge.fixes_scope", "dev10x.coding.skills.merge.fixes_scope"),
            ("dev10x.skills.monitor.pr_notify", "dev10x.coding.skills.monitor.pr_notify"),
            (
                "dev10x.skills.monitor.ci_check_status",
                "dev10x.coding.skills.monitor.ci_check_status",
            ),
            (
                "dev10x.skills.git_fixup.find_fixup_target",
                "dev10x.coding.skills.git_fixup.find_fixup_target",
            ),
            ("dev10x.skills.release.collect_prs", "dev10x.coding.skills.release.collect_prs"),
            (
                "dev10x.skills.orchestration.subagent_protocol",
                "dev10x.coding.skills.orchestration.subagent_protocol",
            ),
            ("dev10x.skills.foreman.watch", "dev10x.coding.skills.foreman.watch"),
            ("dev10x.skills.common.jtbd", "dev10x.coding.skills.common.jtbd"),
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
