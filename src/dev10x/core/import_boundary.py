"""Cross-namespace import edges for the staged plugin split (ADR-0034, GH-1525).

Each ``src/dev10x`` module belongs to one target namespace. A namespace
may import itself and ``core`` freely; every other edge is reported so
Stage A1 can remove it, and the boundary test fails on an edge that is
not in its recorded baseline.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import yaml

NAMESPACES_PATH = Path(__file__).with_name("namespaces.yaml")
CORE = "core"


@dataclass(frozen=True)
class NamespaceMap:
    prefixes: dict[str, str]

    def namespace_of(self, *, module: str) -> str | None:
        parts = module.split(".")
        for end in range(len(parts), 0, -1):
            namespace = self.prefixes.get(".".join(parts[:end]))
            if namespace is not None:
                return namespace
        return None


@dataclass(frozen=True, order=True)
class ImportEdge:
    source: str
    target: str

    def render(self) -> str:
        return f"{self.source} -> {self.target}"


def load_namespace_map(*, path: Path = NAMESPACES_PATH) -> NamespaceMap:
    data = yaml.safe_load(path.read_text()) or {}
    return NamespaceMap(prefixes=dict(data.get("namespaces") or {}))


def module_name(*, path: Path, package_root: Path) -> str:
    relative = path.relative_to(package_root.parent).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _resolve_relative(*, source: str, is_package: bool, level: int, module: str | None) -> str:
    base = source.split(".")
    keep = len(base) - level + (1 if is_package else 0)
    anchor = base[:keep]
    return ".".join([*anchor, module] if module else anchor)


def imported_modules(*, source: str, tree: ast.Module, is_package: bool) -> list[str]:
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = (
                _resolve_relative(
                    source=source,
                    is_package=is_package,
                    level=node.level,
                    module=node.module,
                )
                if node.level
                else node.module or ""
            )
            found.extend(f"{module}.{alias.name}" for alias in node.names)
    return found


def owning_module(*, target: str, known_modules: set[str]) -> str:
    parts = target.split(".")
    for end in range(len(parts), 0, -1):
        candidate = ".".join(parts[:end])
        if candidate in known_modules:
            return candidate
    return target


def cross_namespace_edges(
    *,
    source: str,
    targets: list[str],
    namespaces: NamespaceMap,
) -> list[ImportEdge]:
    own = namespaces.namespace_of(module=source)
    edges: set[ImportEdge] = set()
    for target in targets:
        if not target.startswith("dev10x."):
            continue
        other = namespaces.namespace_of(module=target)
        if other in (own, CORE, None):
            continue
        edges.add(ImportEdge(source=source, target=target))
    return sorted(edges)


def scan_package(*, package_root: Path, namespaces: NamespaceMap) -> list[ImportEdge]:
    paths = sorted(package_root.rglob("*.py"))
    known_modules = {module_name(path=path, package_root=package_root) for path in paths}
    edges: set[ImportEdge] = set()
    for path in paths:
        source = module_name(path=path, package_root=package_root)
        raw_targets = imported_modules(
            source=source,
            tree=ast.parse(path.read_text()),
            is_package=path.name == "__init__.py",
        )
        targets = [
            owning_module(target=target, known_modules=known_modules) for target in raw_targets
        ]
        edges.update(cross_namespace_edges(source=source, targets=targets, namespaces=namespaces))
    return sorted(edges)


def unmapped_top_level(*, package_root: Path, namespaces: NamespaceMap) -> list[str]:
    names = {
        f"{package_root.name}.{entry.stem}"
        for entry in package_root.iterdir()
        if (entry.is_dir() and (entry / "__init__.py").is_file())
        or (entry.suffix == ".py" and entry.stem != "__init__")
    }
    return sorted(names - set(namespaces.prefixes))


__all__ = [
    "CORE",
    "NAMESPACES_PATH",
    "ImportEdge",
    "NamespaceMap",
    "cross_namespace_edges",
    "imported_modules",
    "load_namespace_map",
    "module_name",
    "owning_module",
    "scan_package",
    "unmapped_top_level",
]
