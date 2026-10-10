from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from dev10x.core.paths import skill_script
from dev10x.subprocess_utils import get_plugin_root

SCRIPT_LITERAL = re.compile(r"^skills/[A-Za-z0-9_-]+/scripts/")
RESOLVER = Path("core") / "paths.py"


def _src_root() -> Path:
    return get_plugin_root() / "src" / "dev10x"


def script_literals(*, source: str) -> list[tuple[int, str]]:
    return [
        (node.lineno, node.value)
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and SCRIPT_LITERAL.match(node.value)
    ]


def test_skill_script_builds_the_plugin_relative_path() -> None:
    assert skill_script(skill="gh-context", rel="gh-pr-get.sh") == (
        "skills/gh-context/scripts/gh-pr-get.sh"
    )


def test_src_resolves_scripts_through_the_resolver() -> None:
    offenders = [
        f"{path.relative_to(_src_root())}:{lineno} {value}"
        for path in sorted(_src_root().rglob("*.py"))
        if path.relative_to(_src_root()) != RESOLVER
        for lineno, value in script_literals(source=path.read_text())
    ]

    assert offenders == [], (
        "Use dev10x.core.paths.skill_script instead of a skills/<name>/scripts/ "
        "literal (GH-1526):\n  - " + "\n  - ".join(offenders)
    )


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            'run("skills/git/scripts/git-push-safe.sh")\n',
            [(1, "skills/git/scripts/git-push-safe.sh")],
        ),
        ('note = "see skills/git/scripts/ in prose"\n', []),
        ('GLOB = "skills/*/scripts/*.py"\n', []),
    ],
)
def test_detector(source: str, expected: list[tuple[int, str]]) -> None:
    assert script_literals(source=source) == expected
