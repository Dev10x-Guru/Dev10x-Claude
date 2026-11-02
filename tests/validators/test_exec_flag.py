"""Tests for ExecFlagValidator (DX018, GH-1759)."""

from __future__ import annotations

import pytest
from dev10x.validators.exec_flag import ExecFlagValidator

from dev10x.domain import HookAsk
from tests.fakers import BashHookInputFaker


@pytest.fixture()
def validator() -> ExecFlagValidator:
    return ExecFlagValidator()


@pytest.mark.parametrize(
    ("command", "flag"),
    [
        ("rg --pre=sh x", "--pre"),
        ("rg --pre sh x src", "--pre"),
        ("rg --pre-glob '*.gz' --pre zcat x", "--pre-glob"),
        ("rg --pre-glob='*.gz' x", "--pre-glob"),
        ("sort --compress-program=gzip big.txt", "--compress-program"),
        ("make --eval='$(shell id)' all", "--eval"),
        ("make -E 'x:=1' all", "-E"),
        ("make -f other.mk", "-f"),
        ("make --file=other.mk", "--file"),
        ("make --makefile other.mk", "--makefile"),
        ("make -kf x.mk", "-f"),
        ("make -sE x", "-E"),
        ("/usr/bin/rg --pre=sh x", "--pre"),
        ("timeout 5 rg --pre=sh x", "--pre"),
        ("git status && rg --pre=sh x", "--pre"),
        ("echo $(rg --pre=sh x)", "--pre"),
        ("rg '--pre=sh' x", "--pre"),
        ('rg "--pre" sh x', "--pre"),
        ("make '-f' evil.mk", "-f"),
        ("rg \\\n--pre=sh x", "--pre"),
        ("(rg --pre=sh x)", "--pre"),
        ("{ rg --pre=sh x; }", "--pre"),
        ("diff <(rg --pre=sh x) f", "--pre"),
        ("sort --compress=sh big.txt", "--compress-program"),
        ("make --ev='$(shell id)' all", "--eval"),
        ("make --mak=x.mk", "--makefile"),
        ("rg --pre=sh 'x", "--pre"),
        ("echo 'a;b' && rg --pre=sh x", "--pre"),
    ],
)
def test_asks_on_exec_flag(validator: ExecFlagValidator, command: str, flag: str) -> None:
    inp = BashHookInputFaker.build(command=command)

    result = validator.validate(inp=inp)

    assert isinstance(result, HookAsk)
    assert f" {flag}`" in result.reason


@pytest.mark.parametrize(
    "command",
    [
        "rg -n foo src",
        "sort data.txt",
        "make test",
        "make -j4 test",
        "rg 'make -f x.mk' docs",
        "echo '--pre' | rg x",
        "git merge --ff-only",
        "sort --check data.txt",
        "rg --pretty foo src",
    ],
)
def test_silent_without_exec_flag(validator: ExecFlagValidator, command: str) -> None:
    assert validator.validate(inp=BashHookInputFaker.build(command=command)) is None


@pytest.mark.parametrize(
    ("command", "expected"),
    [("rg --pre=sh x", True), ("git status", False), ("ls -la", False)],
)
def test_should_run_on_named_tools_only(
    validator: ExecFlagValidator, command: str, expected: bool
) -> None:
    assert validator.should_run(inp=BashHookInputFaker.build(command=command)) is expected
