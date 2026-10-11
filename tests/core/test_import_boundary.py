"""Enforcing import-boundary test (ADR-0034 Stage A1, GH-1547).

A namespace imports only itself and ``dev10x.core``. Any other edge must
be covered by a declared exception in ``dev10x/core/import_exceptions.yaml``;
a new edge fails here — import through ``dev10x.core`` instead.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

from dev10x.core.import_boundary import (
    BoundaryException,
    ImportEdge,
    NamespaceMap,
    cross_namespace_edges,
    imported_modules,
    load_exceptions,
    load_namespace_map,
    module_name,
    owning_module,
    scan_package,
    stale_exceptions,
    undeclared_edges,
    unmapped_top_level,
)
from dev10x.core.plugin_map import load_plugin_map
from dev10x.subprocess_utils import get_plugin_root

MILESTONE_PREFIX = "PLG-M"


def _package_root() -> Path:
    return get_plugin_root() / "src" / "dev10x"


@pytest.fixture(scope="module")
def namespaces() -> NamespaceMap:
    return load_namespace_map()


@pytest.fixture(scope="module")
def exceptions() -> list[BoundaryException]:
    return load_exceptions()


@pytest.fixture(scope="module")
def current_edges(namespaces: NamespaceMap) -> list[ImportEdge]:
    return scan_package(package_root=_package_root(), namespaces=namespaces)


@pytest.fixture
def toy_namespaces() -> NamespaceMap:
    return NamespaceMap(
        prefixes={
            "dev10x": "core",
            "dev10x.github": "coding",
            "dev10x.utilities": "comm",
            "dev10x.mcp.plan_tools": "tasks",
        },
    )


class TestRepositoryBoundary:
    def test_every_cross_namespace_edge_is_declared(
        self,
        current_edges: list[ImportEdge],
        exceptions: list[BoundaryException],
    ) -> None:
        undeclared = [
            edge.render() for edge in undeclared_edges(edges=current_edges, exceptions=exceptions)
        ]

        assert undeclared == [], (
            "Undeclared cross-namespace import(s) (GH-1547). A namespace imports only "
            "itself and dev10x.core; route these through dev10x.core:\n" + "\n".join(undeclared)
        )

    def test_no_declared_exception_is_stale(
        self,
        current_edges: list[ImportEdge],
        exceptions: list[BoundaryException],
    ) -> None:
        stale = [
            exception.render()
            for exception in stale_exceptions(edges=current_edges, exceptions=exceptions)
        ]

        assert stale == [], (
            "Remove the exception(s) that no longer cover an edge from "
            "import_exceptions.yaml:\n" + "\n".join(stale)
        )

    def test_every_exception_states_reason_and_removal_milestone(
        self,
        exceptions: list[BoundaryException],
    ) -> None:
        unjustified = [
            exception.render()
            for exception in exceptions
            if not (exception.reason.strip() and exception.until.startswith(MILESTONE_PREFIX))
        ]

        assert unjustified == []

    @pytest.mark.parametrize(
        "edge",
        [
            ImportEdge(
                source="dev10x.comm.skills.bus.maildir",
                target="dev10x.coding.github.pulls",
            ),
            ImportEdge(source="dev10x.core.hooks.session", target="dev10x.teach.audit"),
            ImportEdge(
                source="dev10x.coding.skills.monitor.pr_notify",
                target="dev10x.comm.skills.notifications.gchat_notify",
            ),
        ],
        ids=["satellite-to-satellite", "core-to-satellite", "beside-a-declared-edge"],
    )
    def test_a_new_cross_namespace_import_fails(
        self,
        exceptions: list[BoundaryException],
        edge: ImportEdge,
    ) -> None:
        assert undeclared_edges(edges=[edge], exceptions=exceptions) == [edge]

    def test_every_top_level_module_has_a_namespace(self, namespaces: NamespaceMap) -> None:
        assert unmapped_top_level(package_root=_package_root(), namespaces=namespaces) == []

    def test_namespaces_are_plugin_map_keys(self, namespaces: NamespaceMap) -> None:
        assert set(namespaces.prefixes.values()) <= set(load_plugin_map().plugins)


PLUGIN_KEYS = sorted(load_plugin_map().plugins)


class TestTargetPackages:
    def test_there_are_nine_target_namespaces(self) -> None:
        assert len(PLUGIN_KEYS) == 9

    @pytest.mark.parametrize("key", PLUGIN_KEYS)
    def test_target_package_imports(self, key: str) -> None:
        assert importlib.import_module(f"dev10x.{key}").__name__ == f"dev10x.{key}"

    @pytest.mark.parametrize("key", PLUGIN_KEYS)
    def test_boundary_maps_target_package_to_itself(
        self,
        namespaces: NamespaceMap,
        key: str,
    ) -> None:
        assert namespaces.namespace_of(module=f"dev10x.{key}") == key


class TestNamespaceMap:
    @pytest.mark.parametrize(
        ("module", "expected"),
        [
            ("dev10x.github.pulls", "coding"),
            ("dev10x.mcp.plan_tools", "tasks"),
            ("dev10x.mcp.server_cli", "core"),
            ("requests", None),
        ],
    )
    def test_longest_prefix_wins(
        self,
        toy_namespaces: NamespaceMap,
        module: str,
        expected: str | None,
    ) -> None:
        assert toy_namespaces.namespace_of(module=module) == expected


class TestEdgeDetection:
    def test_reports_a_cross_namespace_edge(self, toy_namespaces: NamespaceMap) -> None:
        edges = cross_namespace_edges(
            source="dev10x.github.notify",
            targets=[
                "dev10x.utilities.slack.post",
                "dev10x.domain.result.ok",
                "dev10x.github._gateway",
                "json",
            ],
            namespaces=toy_namespaces,
        )

        assert edges == [
            ImportEdge(source="dev10x.github.notify", target="dev10x.utilities.slack.post")
        ]

    @pytest.mark.parametrize(
        ("target", "expected"),
        [
            ("dev10x.github.app_api.get_app", "dev10x.github.app_api"),
            ("dev10x.mcp.audit_tools.*", "dev10x.mcp.audit_tools"),
            ("dev10x.github.pr_detect", "dev10x.github"),
            ("elsewhere.thing", "elsewhere.thing"),
        ],
    )
    def test_owning_module_collapses_symbols(self, target: str, expected: str) -> None:
        known = {"dev10x.github", "dev10x.github.app_api", "dev10x.mcp.audit_tools"}

        assert owning_module(target=target, known_modules=known) == expected

    def test_edge_renders_as_an_allowlist_line(self) -> None:
        assert ImportEdge(source="a", target="b").render() == "a -> b"

    @pytest.mark.parametrize(
        ("source", "is_package", "code", "expected"),
        [
            ("dev10x.github.pulls", False, "import dev10x.db\n", ["dev10x.db"]),
            (
                "dev10x.github.pulls",
                False,
                "from dev10x.utilities import slack\n",
                ["dev10x.utilities.slack"],
            ),
            ("dev10x.github.pulls", False, "from . import labels\n", ["dev10x.github.labels"]),
            ("dev10x.github", True, "from .pulls import pr_get\n", ["dev10x.github.pulls.pr_get"]),
            (
                "dev10x.skills.monitor.pr_notify",
                False,
                "from ..notifications import slack_notify\n",
                ["dev10x.skills.notifications.slack_notify"],
            ),
        ],
    )
    def test_imported_modules(
        self,
        source: str,
        is_package: bool,
        code: str,
        expected: list[str],
    ) -> None:
        tree = ast.parse(code)

        assert imported_modules(source=source, tree=tree, is_package=is_package) == expected


class TestPackageScan:
    @pytest.fixture
    def package(self, tmp_path: Path) -> Path:
        root = tmp_path / "dev10x"
        (root / "github").mkdir(parents=True)
        (root / "utilities").mkdir()
        (root / "__init__.py").write_text("")
        (root / "github" / "__init__.py").write_text("")
        (root / "github" / "notify.py").write_text("from dev10x.utilities import slack\n")
        (root / "utilities" / "__init__.py").write_text("")
        (root / "utilities" / "slack.py").write_text("")
        (root / "loose.py").write_text("")
        return root

    def test_scan_finds_the_edge(self, package: Path, toy_namespaces: NamespaceMap) -> None:
        edges = scan_package(package_root=package, namespaces=toy_namespaces)

        assert [edge.render() for edge in edges] == [
            "dev10x.github.notify -> dev10x.utilities.slack"
        ]

    def test_unmapped_top_level_names_the_newcomer(
        self,
        package: Path,
        toy_namespaces: NamespaceMap,
    ) -> None:
        assert unmapped_top_level(package_root=package, namespaces=toy_namespaces) == [
            "dev10x.loose"
        ]

    def test_module_name_of_a_package_init(self, package: Path) -> None:
        path = package / "github" / "__init__.py"

        assert module_name(path=path, package_root=package) == "dev10x.github"


COMPOSITION_ROOT = BoundaryException(
    source="dev10x.commands",
    target="dev10x",
    reason="CLI root",
    until="PLG-M6",
)
SINGLE_EDGE = BoundaryException(
    source="dev10x.coding.skills.monitor.pr_notify",
    target="dev10x.comm.skills.notifications.slack_notify",
    reason="Slack post",
    until="PLG-M3",
)


class TestBoundaryException:
    @pytest.mark.parametrize(
        ("exception", "edge", "expected"),
        [
            (COMPOSITION_ROOT, ImportEdge(source="dev10x.commands", target="dev10x.qa"), True),
            (
                COMPOSITION_ROOT,
                ImportEdge(source="dev10x.commands.hook", target="dev10x.teach.audit"),
                True,
            ),
            (
                COMPOSITION_ROOT,
                ImportEdge(source="dev10x.commandsx", target="dev10x.teach.audit"),
                False,
            ),
            (
                SINGLE_EDGE,
                ImportEdge(
                    source="dev10x.coding.skills.monitor.pr_notify",
                    target="dev10x.comm.skills.notifications.slack_notify",
                ),
                True,
            ),
            (
                SINGLE_EDGE,
                ImportEdge(
                    source="dev10x.coding.skills.monitor.pr_notify",
                    target="dev10x.comm.skills.notifications",
                ),
                False,
            ),
            (
                SINGLE_EDGE,
                ImportEdge(
                    source="dev10x.coding.skills.monitor",
                    target="dev10x.comm.skills.notifications.slack_notify",
                ),
                False,
            ),
        ],
        ids=[
            "prefix-itself",
            "below-prefix",
            "sibling-name",
            "exact-edge",
            "target-parent",
            "source-parent",
        ],
    )
    def test_covers_only_edges_below_both_prefixes(
        self,
        exception: BoundaryException,
        edge: ImportEdge,
        expected: bool,
    ) -> None:
        assert exception.covers(edge=edge) is expected

    def test_renders_with_its_removal_milestone(self) -> None:
        assert SINGLE_EDGE.render() == (
            "dev10x.coding.skills.monitor.pr_notify -> "
            "dev10x.comm.skills.notifications.slack_notify (until PLG-M3)"
        )


class TestExceptionChecks:
    @pytest.fixture
    def edges(self) -> list[ImportEdge]:
        return [
            ImportEdge(source="dev10x.commands.skill", target="dev10x.comm.skills.bus"),
            ImportEdge(source="dev10x.qa.evidence", target="dev10x.coding.github"),
        ]

    def test_undeclared_edges_lists_only_uncovered(self, edges: list[ImportEdge]) -> None:
        assert undeclared_edges(edges=edges, exceptions=[COMPOSITION_ROOT, SINGLE_EDGE]) == [
            ImportEdge(source="dev10x.qa.evidence", target="dev10x.coding.github")
        ]

    def test_stale_exceptions_lists_only_unused(self, edges: list[ImportEdge]) -> None:
        assert stale_exceptions(edges=edges, exceptions=[COMPOSITION_ROOT, SINGLE_EDGE]) == [
            SINGLE_EDGE
        ]


class TestLoadExceptions:
    def test_reads_every_field(self, tmp_path: Path) -> None:
        path = tmp_path / "exceptions.yaml"
        path.write_text(
            "exceptions:\n"
            "  - source: dev10x.commands\n"
            "    target: dev10x\n"
            "    reason: CLI root\n"
            "    until: PLG-M6\n"
        )

        assert load_exceptions(path=path) == [COMPOSITION_ROOT]

    def test_empty_file_declares_nothing(self, tmp_path: Path) -> None:
        path = tmp_path / "exceptions.yaml"
        path.write_text("")

        assert load_exceptions(path=path) == []
