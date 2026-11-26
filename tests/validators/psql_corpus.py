"""A corpus of real command strings for comparing DX004's two psql layers (GH-2005).

The corpus is every ``command`` parametrization in the DX004 and lexer
test modules, plus the verbatim commands recorded in the GH-271
permission-friction fixtures. Each command is judged twice: by the word
rule alone and by the command-position walk alone.
"""

from __future__ import annotations

import inspect
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

import yaml

from dev10x.core.validators.sql_safety import _direct_psql_verdict, _psql_word_anywhere
from tests.domain.common import test_bash_tokens
from tests.validators import test_sql_safety

_FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "permission-friction"
_COMMAND_ARGNAME = "command"
_SOURCE_MODULES = (test_sql_safety, test_bash_tokens)


def _never(*, command: str) -> bool:
    return False


def walk_blocks(*, command: str) -> bool:
    return _direct_psql_verdict(command=command, word_rule=_never) is not None


def word_rule_blocks(*, command: str) -> bool:
    return _psql_word_anywhere(command=command)


def _argnames(*, mark: Any) -> list[str]:
    names = mark.args[0]
    if isinstance(names, str):
        return [name.strip() for name in names.split(",")]
    return list(names)


def _parametrized_commands(*, function: Any) -> Iterator[str]:
    for mark in getattr(function, "pytestmark", []):
        if mark.name != "parametrize":
            continue
        names = _argnames(mark=mark)
        if _COMMAND_ARGNAME not in names:
            continue
        position = names.index(_COMMAND_ARGNAME)
        for value in mark.args[1]:
            values = getattr(value, "values", value)
            command = values if len(names) == 1 else values[position]
            if isinstance(command, str):
                yield command


def _test_functions(*, module: ModuleType) -> Iterator[Any]:
    for _, member in inspect.getmembers(module):
        if inspect.isclass(member) and member.__module__ == module.__name__:
            yield from (function for _, function in inspect.getmembers(member, inspect.isfunction))
        elif inspect.isfunction(member) and member.__module__ == module.__name__:
            yield member


def parametrized_commands() -> list[str]:
    return [
        command
        for module in _SOURCE_MODULES
        for function in _test_functions(module=module)
        for command in _parametrized_commands(function=function)
    ]


def fixture_commands() -> list[str]:
    commands: list[str] = []
    for path in sorted(_FIXTURE_DIR.glob("*.yaml")):
        document = yaml.safe_load(path.read_text())
        commands.extend(
            row["command"]
            for row in document.get("rows", [])
            if row.get("tool") in ("Bash", None) and isinstance(row.get("command"), str)
        )
    return commands


def corpus() -> list[str]:
    return sorted(set(parametrized_commands()) | set(fixture_commands()))


@dataclass(frozen=True)
class Comparison:
    total: int
    word_rule: frozenset[str]
    walk: frozenset[str]

    @property
    def word_rule_only(self) -> frozenset[str]:
        return self.word_rule - self.walk

    @property
    def walk_only(self) -> frozenset[str]:
        return self.walk - self.word_rule

    def report(self) -> str:
        lines = [
            f"corpus: {self.total} commands",
            f"word rule blocks: {len(self.word_rule)}",
            f"walk blocks: {len(self.walk)}",
            f"both block: {len(self.word_rule & self.walk)}",
            f"walk only: {len(self.walk_only)}",
            f"word rule only: {len(self.word_rule_only)}",
            *(f"  word rule only: {command!r}" for command in sorted(self.word_rule_only)),
        ]
        return "\n".join(lines)


def compare(*, commands: list[str]) -> Comparison:
    return Comparison(
        total=len(commands),
        word_rule=frozenset(command for command in commands if word_rule_blocks(command=command)),
        walk=frozenset(command for command in commands if walk_blocks(command=command)),
    )
