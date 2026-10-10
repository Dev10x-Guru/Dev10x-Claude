"""Report-only import-boundary test (ADR-0034 Stage A0, GH-1525).

``tests/fixtures/import_boundary_allowlist.txt`` is today's baseline of
cross-namespace edges. Stage A1 shrinks it; nothing should grow it. A
new edge fails here — import through ``dev10x.core`` instead, or, when
the edge is genuinely intended, add the reported line to the baseline.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from dev10x.core.import_boundary import (
    ImportEdge,
    NamespaceMap,
    cross_namespace_edges,
    imported_modules,
    load_namespace_map,
    module_name,
    owning_module,
    scan_package,
    unmapped_top_level,
)
from dev10x.core.plugin_map import load_plugin_map
from dev10x.subprocess_utils import get_plugin_root

ALLOWLIST_PATH = Path(__file__).parents[1] / "fixtures" / "import_boundary_allowlist.txt"


def _package_root() -> Path:
    return get_plugin_root() / "src" / "dev10x"


def read_allowlist(*, path: Path) -> set[str]:
    return {
        line.strip()
        for line in path.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    }


@pytest.fixture(scope="module")
def namespaces() -> NamespaceMap:
    return load_namespace_map()


@pytest.fixture(scope="module")
def current_edges(namespaces: NamespaceMap) -> set[str]:
    return {
        edge.render() for edge in scan_package(package_root=_package_root(), namespaces=namespaces)
    }


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
    def test_no_edge_outside_the_baseline(self, current_edges: set[str]) -> None:
        new_edges = sorted(current_edges - read_allowlist(path=ALLOWLIST_PATH))

        assert new_edges == [], (
            "New cross-namespace import(s) (GH-1525). Route through dev10x.core, "
            f"or add the line(s) to {ALLOWLIST_PATH.name}:\n" + "\n".join(new_edges)
        )

    def test_baseline_lists_no_edge_that_is_gone(self, current_edges: set[str]) -> None:
        stale = sorted(read_allowlist(path=ALLOWLIST_PATH) - current_edges)

        assert stale == [], (
            f"Remove the resolved edge(s) from {ALLOWLIST_PATH.name}:\n" + "\n".join(stale)
        )

    def test_every_top_level_module_has_a_namespace(self, namespaces: NamespaceMap) -> None:
        assert unmapped_top_level(package_root=_package_root(), namespaces=namespaces) == []

    def test_namespaces_are_plugin_map_keys(self, namespaces: NamespaceMap) -> None:
        assert set(namespaces.prefixes.values()) <= set(load_plugin_map().plugins)


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

    def test_allowlist_skips_comments_and_blanks(self, tmp_path: Path) -> None:
        path = tmp_path / "allow.txt"
        path.write_text("# header\n\na -> b\n")

        assert read_allowlist(path=path) == {"a -> b"}
