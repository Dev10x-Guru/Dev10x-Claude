"""No shipped catalog carries a Bash rule with a `*` before `:*` (GH-1472).

Such a rule is a literal prefix: it never matches and Claude Code flags it
at every startup. Every string in both catalogs is walked, not just
`base_permissions`, so a rule parked in a tracker block or an opt-in group
cannot slip past.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import dev10x.skills.permission as permission_pkg
from dev10x.domain.common.allow_rule import AllowRule
from dev10x.skills.permission.catalog_paths import CATALOG_RELPATH

PERMISSION_DIR = Path(permission_pkg.__file__).resolve().parent
REPO_ROOT = PERMISSION_DIR.parents[3]
CATALOGS = (
    REPO_ROOT / CATALOG_RELPATH,
    PERMISSION_DIR / "baseline-permissions.yaml",
)


def _bash_rules(*, source: Path) -> list[str]:
    found: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, str) and node.startswith("Bash(") and node.endswith(")"):
            found.append(node)
        elif isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(yaml.safe_load(source.read_text(encoding="utf-8")))
    return found


@pytest.mark.parametrize("catalog", CATALOGS, ids=lambda path: path.name)
def test_catalog_has_bash_rules_to_check(catalog: Path) -> None:
    assert _bash_rules(source=catalog)


@pytest.mark.parametrize("catalog", CATALOGS, ids=lambda path: path.name)
def test_no_bash_rule_puts_a_star_before_the_colon_star(catalog: Path) -> None:
    unmatchable = [
        rule
        for rule in _bash_rules(source=catalog)
        if AllowRule.parse(rule).has_literal_star_prefix
    ]

    assert unmatchable == []
