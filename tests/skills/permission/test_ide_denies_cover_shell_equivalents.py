"""The shipped IDE denies and the doctor's detector must agree (GH-1403).

The `jetbrains` -> `pycharm` server rename dropped two of five execution
surfaces from `ide_denies`, and nothing failed: a deny keys on a tool
NAME, so removing a name narrows coverage while every rule that remains
still looks correct. The detector that is supposed to catch an allowed
shell-equivalent tool was blind to the same two names, because its
markers never matched `execute_run_configuration` or `run_notebook_cell`
— the gap existed twice and neither copy could reveal the other.

These tests tie the two together. `_looks_shell_equivalent` becomes the
single definition of the category, and the catalog must be expressible in
it: a deny the detector cannot see is a deny that will be silently
dropped by the next rename, and a detector whose markers narrow breaks
these tests rather than a user's machine.
"""

from __future__ import annotations

import pytest
import yaml

from dev10x.skills.doctor.strategies.shell_equivalent_mcp_tools import (
    _looks_shell_equivalent,
)
from dev10x.skills.permission.catalog_paths import shipped_projects_catalog

_TOOL_PREFIX_SEPARATOR = "__"


def _catalog() -> dict:
    return yaml.safe_load(shipped_projects_catalog().read_text())


def _tool_name(rule: str) -> str:
    """Strip the `mcp__<server>__` prefix, leaving the bare tool name."""
    return rule.split(_TOOL_PREFIX_SEPARATOR)[-1]


def _ide_deny_rules() -> list[str]:
    return [rule for rules in _catalog().get("ide_denies", {}).values() for rule in rules]


def test_catalog_ships_ide_denies() -> None:
    # Guards the two tests below against passing vacuously if the key is
    # ever renamed or emptied.
    assert _ide_deny_rules()


@pytest.mark.parametrize("rule", _ide_deny_rules())
def test_every_ide_deny_is_detectable(rule: str) -> None:
    assert _looks_shell_equivalent(_tool_name(rule)), (
        f"{rule} is denied as shell-equivalent but the doctor's markers do "
        "not match it, so an allowed copy of this tool would go unreported."
    )


@pytest.mark.parametrize("rule", _ide_deny_rules())
def test_every_ide_deny_is_unconditional(rule: str) -> None:
    # GH-1261: the hazard does not depend on which IDE was pinned, so the
    # rule belongs in base_denies too — not only under the IDE's own key.
    assert rule in _catalog().get("base_denies", []), (
        f"{rule} is denied only under its IDE key, so a checkout that pinned "
        "no IDE (or a different one) allows it."
    )


@pytest.mark.parametrize(
    "tool",
    [
        "execute_terminal_command",
        "execute_code_on_kernel",
        "execute_tool",
        "execute_run_configuration",
        "run_notebook_cell",
        "build_project",
    ],
)
def test_known_pycharm_execution_surfaces_are_denied(tool: str) -> None:
    # The five surfaces GH-1403 enumerated, plus build_project. Pinning the
    # inventory is what makes a future rename fail here instead of silently.
    assert f"mcp__pycharm__{tool}" in _catalog().get("base_denies", [])


@pytest.mark.parametrize(
    "tool",
    [
        "get_evaluation_report",
        "get_run_configurations",
        "read_notebook_cell",
        "configure_python_interpreter",
        "get_build_status",
    ],
)
def test_reads_and_config_are_not_flagged(tool: str) -> None:
    # Over-firing is what turns this strategy into noise: a critical
    # finding against a harmless read teaches the reader to skim past it.
    # `configure_python_interpreter` mutates IDE config and executes
    # nothing itself, so it stays out deliberately (GH-1403).
    assert not _looks_shell_equivalent(tool)
