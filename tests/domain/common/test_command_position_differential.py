"""Differential test: the reworked command_position_re matches whatever the old one did.

GH-2005 review rewrote `_WRAPPER_OPTIONS` / `_WRAPPER_PREFIX` to stop 2^n
backtracking. The old fragments below are copied verbatim from
origin/develop f11c3ebe. Every string the old regex matches must still
match, with the program at the same position, because DX003 and DX004
both fail closed on this regex.
"""

from __future__ import annotations

import itertools
import re
import time
from collections.abc import Iterator

import pytest

from dev10x.core.domain.common.bash_tokens import _WRAPPER_NAMES, command_position_re
from tests.validators.psql_corpus import corpus

_OLD_COMMAND_BOUNDARY = r"(?:^|[|;&(\n{]|\s['\"])\s*"
_OLD_ENV_ASSIGNMENTS = r"(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)*"
_OLD_LEADING_REDIRECTS = r"(?:(?:\d+|&)?[<>][<>&|]*(?:\S+|\s+\S+)\s+)*"
_OLD_DIRECTORY = r"(?:[\w./~-]*/)?"
_OLD_WRAPPER_OPTIONS = r"(?:(?:-\S*|\d\S*)\s+(?:[^\s|;&-]\S*\s+)?)*"
_OLD_WRAPPER_PREFIX = (
    rf"(?:{_OLD_DIRECTORY}(?:{_WRAPPER_NAMES})\s+{_OLD_WRAPPER_OPTIONS}"
    rf"|{_OLD_DIRECTORY}ssh\s+{_OLD_WRAPPER_OPTIONS}[^\s|;&-]\S*\s+{_OLD_WRAPPER_OPTIONS})*"
)

_PROGRAMS = ("psql", "python", "dropdb|createdb", "screen|tmux")


def _old_command_position_re(*, program: str) -> re.Pattern[str]:
    return re.compile(
        _OLD_COMMAND_BOUNDARY
        + _OLD_LEADING_REDIRECTS
        + _OLD_ENV_ASSIGNMENTS
        + _OLD_WRAPPER_PREFIX
        + _OLD_DIRECTORY
        + r"(?:"
        + program
        + r")\b"
    )


_WRAPPERS = ("sudo", "env", "timeout", "nice", "nohup", "/usr/bin/sudo", "xargs")
_OPTION_RUNS = (
    "",
    "-u ",
    "-u app ",
    "-u 5 ",
    "5 ",
    "30s ",
    "-x sudo ",
    "-o ssh ",
    "-u sudo -E ",
    "-n 5 -u ",
    "-x ./sudo ",
    "-1 1 ",
)
_SSH_OPTION_RUNS = ("", "-p 22 ", "-o x ", "-t ", "-o ssh ", "-i 5 ")
_SSH_HOSTS = ("", "db01 ", "10.0.0.1 ", "sudo ", "ssh ", "user@host ", "./ssh ")
_LEADS = ("", "A=1 ", "> out ", "2>/dev/null ", "; ", "x '", 'x "', "( ", "{ ")
_TARGETS = ("psql", "/usr/bin/psql", "psql -d x")


def _items() -> list[str]:
    plain = [f"{wrapper} {options}" for wrapper in _WRAPPERS for options in _OPTION_RUNS]
    remote = [
        f"ssh {before}{host}{after}"
        for before in _SSH_OPTION_RUNS
        for host in _SSH_HOSTS
        for after in ("", "-t ")
    ]
    return [*plain, *remote]


def _generated() -> Iterator[str]:
    items = _items()
    short = items[:: max(1, len(items) // 12)]
    for lead in _LEADS:
        for target in _TARGETS:
            yield lead + target
            for item in items:
                yield lead + item + target
    for first, second in itertools.product(items, repeat=2):
        yield first + second + "psql"
    for chain in itertools.product(short, repeat=3):
        yield "".join(chain) + "psql"


_GENERATED = list(dict.fromkeys(_generated()))


def _existing_commands() -> list[str]:
    return corpus()


def test_generates_a_broad_case_set() -> None:
    assert len(_GENERATED) > 30_000


def test_new_matches_wherever_old_matches_on_generated_cases() -> None:
    old = _old_command_position_re(program="psql")
    new = command_position_re(program="psql")
    start = time.perf_counter()
    old_matched = 0
    misses: list[str] = []
    for text in _GENERATED:
        old_match = old.search(text)
        if old_match is None:
            continue
        old_matched += 1
        new_match = new.search(text)
        if new_match is None or new_match.end() != old_match.end():
            misses.append(text)
    elapsed = time.perf_counter() - start
    print(f"generated={len(_GENERATED)} old_matched={old_matched} misses={len(misses)}")

    assert misses == []
    assert old_matched > len(_GENERATED) * 0.9
    assert elapsed < 2.0


@pytest.mark.parametrize("program", _PROGRAMS)
def test_new_matches_wherever_old_matches_on_existing_commands(program: str) -> None:
    old = _old_command_position_re(program=program)
    new = command_position_re(program=program)
    misses = [
        text
        for text in _existing_commands()
        if (old_match := old.search(text))
        and ((new_match := new.search(text)) is None or new_match.end() > old_match.end())
    ]

    assert misses == []
