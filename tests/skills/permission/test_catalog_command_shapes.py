"""A command family must be catalogued in the shape users actually type.

GH-1248: ``Bash(uv run pytest:*)`` and ``Bash(uv run ruff:*)`` were
catalogued, but the ``uv run --directory <path> <cmd>`` forms were not.
Allow-rule matching keys on the literal command string, so the
catalogued rule never matches the ``--directory`` shape — and that is
the shape used in the multi-worktree setups Dev10x itself encourages
via ``Dev10x:git-worktree``.

``catalog-gap`` cannot catch this: it compares settings files against
the catalog, so a shape absent from *both* reads as full coverage. The
same failure mode produced GH-1189 (``uv add`` / ``uv remove``) and
GH-1149 (bare ``pre-commit run``). This module pins the shapes so a
future catalog edit cannot drop one half of a family and still pass.

The pager denies are the deny-side counterpart: ``git -P`` and
``git --no-pager`` prefix a git verb and shift the effective command
prefix, defeating every ``Bash(git <verb>:*)`` allow in the catalog —
the same prefix-shift problem documented for env-var prefixes and
``git -C``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

# Every catalogued command that also has a `--directory` form in use.
DIRECTORY_FORM_COMMANDS = ("pytest", "mypy", "ruff")

PAGER_DENIES = (
    "Bash(git -P:*)",
    "Bash(git --no-pager:*)",
)


def _catalog(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


@pytest.mark.parametrize("command", DIRECTORY_FORM_COMMANDS)
def test_uv_run_directory_form_is_catalogued(projects_yaml: Path, command: str) -> None:
    allows = _catalog(projects_yaml)["base_permissions"]
    assert f"Bash(uv run --directory * {command}:*)" in allows


@pytest.mark.parametrize("rule", PAGER_DENIES)
def test_git_pager_prefix_is_denied(projects_yaml: Path, rule: str) -> None:
    assert rule in _catalog(projects_yaml)["base_denies"]


@pytest.mark.parametrize("rule", PAGER_DENIES)
def test_git_pager_prefix_is_not_also_allowed(projects_yaml: Path, rule: str) -> None:
    """A deny paired with an allow of the same shape is a contradiction.

    Denies win, so the allow would be a dead rule inviting false
    confidence in a later audit that does not check both lists.
    """
    assert rule not in _catalog(projects_yaml)["base_permissions"]


def test_plain_uv_run_forms_remain_catalogued(projects_yaml: Path) -> None:
    """The `--directory` forms are additive, not a replacement.

    Both shapes are in real use; dropping the plain form while adding
    the directory form would move the prompt rather than remove it.
    """
    allows = _catalog(projects_yaml)["base_permissions"]
    assert "Bash(uv run pytest:*)" in allows
    assert "Bash(uv run ruff:*)" in allows
