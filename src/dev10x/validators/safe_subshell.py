"""Validator: auto-approve commands with safe read-only subshells.

Reduces permission friction for commands like:
  basename "$(git rev-parse --show-toplevel)"
  echo "$(git symbolic-ref --short HEAD)"

These commands contain $(…) subshells that prevent allow-rule matching,
but the subshells are read-only git operations that are safe to run.

When ALL subshells in a command are safe read-only operations AND the
outer command is also safe, the validator auto-approves the entire
command via HookAllow.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from dev10x.domain import HookAllow, HookInput, HookResult
from dev10x.domain.profile_tier import ProfileTier
from dev10x.validators.base import ValidatorBase

SAFE_SUBSHELL_PREFIXES = (
    "git rev-parse",
    "git symbolic-ref",
    "git branch --show-current",
    "git config --get",
    "git remote get-url",
    "git log --format",
    "git log --oneline",
    "git describe",
    "git name-rev",
    "git show-ref",
    "basename ",
    "dirname ",
)


def _extract_subshells(command: str) -> list[str]:
    subshells: list[str] = []
    i = 0
    while i < len(command) - 1:
        if command[i : i + 2] == "$(":
            depth = 1
            j = i + 2
            while j < len(command) and depth > 0:
                if command[j] == "(":
                    depth += 1
                elif command[j] == ")":
                    depth -= 1
                j += 1
            if depth == 0:
                subshells.append(command[i + 2 : j - 1])
                i = j
            else:
                i += 1
        else:
            i += 1
    return subshells


SAFE_OUTER_COMMANDS = frozenset(
    [
        "basename",
        "dirname",
        "echo",
        "printf",
        "wc",
        "sort",
        "head",
        "tail",
        "cut",
        "tr",
        "test",
        "[",
        "expr",
    ]
)


def _is_safe_subshell(content: str) -> bool:
    stripped = content.strip()
    return any(stripped.startswith(prefix) for prefix in SAFE_SUBSHELL_PREFIXES)


def _strip_subshells(command: str) -> str:
    result: list[str] = []
    i = 0
    while i < len(command):
        if i < len(command) - 1 and command[i : i + 2] == "$(":
            depth = 1
            j = i + 2
            while j < len(command) and depth > 0:
                if command[j] == "(":
                    depth += 1
                elif command[j] == ")":
                    depth -= 1
                j += 1
            result.append("__SUBSHELL__")
            i = j
        else:
            result.append(command[i])
            i += 1
    return "".join(result)


def _outer_command_token(command: str) -> str:
    stripped = _strip_subshells(command=command).strip()
    tokens = stripped.split()
    return tokens[0] if tokens else ""


@dataclass
class SafeSubshellValidator(ValidatorBase):
    name: ClassVar[str] = "safe-subshell"
    rule_id: ClassVar[str] = "DX001"
    profile: ClassVar[ProfileTier] = ProfileTier.MINIMAL

    def should_run(self, inp: HookInput) -> bool:
        return "$(" in inp.command

    def validate(self, inp: HookInput) -> HookAllow | HookResult | None:
        subshells = _extract_subshells(command=inp.command)
        if not subshells:
            return None

        if not all(_is_safe_subshell(content=s) for s in subshells):
            return None

        outer = _outer_command_token(command=inp.command)
        if outer not in SAFE_OUTER_COMMANDS:
            return None

        return HookAllow()
