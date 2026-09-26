"""session_yaml's three documents live in their own modules (GH-1431)."""

from __future__ import annotations

import ast
from types import ModuleType

import pytest

from dev10x.domain.documents import config_yaml, friction_yaml, session_yaml

MOVED = [
    *(("friction_yaml", name) for name in friction_yaml.__all__),
    *(("config_yaml", name) for name in config_yaml.__all__),
]


@pytest.mark.parametrize(("module", "name"), MOVED)
def test_old_path_re_exports_the_moved_object(module: str, name: str) -> None:
    owner = {"friction_yaml": friction_yaml, "config_yaml": config_yaml}[module]

    assert getattr(session_yaml, name) is getattr(owner, name)


def test_session_yaml_defines_only_the_session_document() -> None:
    tree = ast.parse(open(session_yaml.__file__, encoding="utf-8").read())

    classes = [node.name for node in tree.body if isinstance(node, ast.ClassDef)]

    assert classes == ["SessionYamlDocument"]


@pytest.mark.parametrize("module", [friction_yaml, config_yaml])
def test_split_module_does_not_import_the_facade(module: ModuleType) -> None:
    tree = ast.parse(open(module.__file__ or "", encoding="utf-8").read())

    imported = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]

    assert session_yaml.__name__ not in imported
