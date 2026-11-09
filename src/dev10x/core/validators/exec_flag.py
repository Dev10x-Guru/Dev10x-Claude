"""Validator: ask before a flag that makes a read-only tool run a program (DX018).

``permission_grant`` refuses a rule that names an exec-capable flag
(GH-1723), but that only stops new grants. A prefix rule covers every
trailing flag, and the shipped catalog itself carries ``Bash(rg:*)`` and
``Bash(sort:*)``, so ``rg --pre=sh x`` already runs with no prompt. No
allow-rule shape can exclude one flag, so the gap closes here, where the
command is visible (GH-1759).

The effect is ``ask``, not ``deny``, after DX014: the command may be
legitimate, and a hard deny drops the user to a manual ``!`` shell. A
hook ``ask`` prompts even when an allow rule matched, which is exactly
the case being closed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from dev10x.core.name_boundary import name_pattern
from dev10x.domain import HookAsk, HookInput
from dev10x.domain.common.bash_tokens import (
    UntokenizableCommandError,
    command_segments,
    command_units,
    split_tokens,
    strip_command_wrappers,
    strip_line_continuations,
)
from dev10x.domain.common.exec_capable import EXEC_FLAGS, exec_flag
from dev10x.domain.profile_tier import ProfileTier
from dev10x.validators.base import ValidatorBase

# Fallback split for a unit the shared segmenter cannot tokenize
# (unbalanced quote): asking on a guess beats skipping the check.
_SEPARATOR_RE = re.compile(r"&&|\|\||[;|&\n()<>]")
# Cheap prefilter on the hot path: a listed tool as a whole word, so `rg`
# inside `merge` or `target` does not wake the tokenizer.
_TOOL_WORD_RE = name_pattern(names=EXEC_FLAGS)

_ASK_MESSAGE = (
    "⚠️  `{tool} {flag}` runs another program — a prefix allow rule for "
    "`{tool}` does not make that safe.\n\n"
    "Rule DX018: an allow rule like `Bash({tool}:*)` covers every trailing "
    "flag, including the ones that execute code. Approve only if the program "
    "it runs is intended."
)


def _segments(*, unit: str) -> list[list[str]]:
    """Argv of each simple command in ``unit``, quotes honoured.

    The shared segmenter (GH-1773) removes quotes the way bash does, so
    `rg '--pre=sh' x` yields the word `--pre=sh` rather than hiding it
    (GH-1759 review), and keeps a quoted operator inside its argument.
    """
    try:
        return [list(segment.argv) for segment in command_segments(command=unit)]
    except UntokenizableCommandError:
        text = strip_line_continuations(command=unit)
        return [split_tokens(command=part) for part in _SEPARATOR_RE.split(text)]


def _simple_commands(*, command: str) -> list[list[str]]:
    commands: list[list[str]] = []
    for unit in command_units(command=command):
        for segment in _segments(unit=unit):
            words = strip_command_wrappers(parts=segment)
            if words:
                commands.append(words)
    return commands


@dataclass
class ExecFlagValidator(ValidatorBase):
    name: ClassVar[str] = "exec-flag"
    rule_id: ClassVar[str] = "DX018"
    profile: ClassVar[ProfileTier] = ProfileTier.STANDARD

    def should_run(self, inp: HookInput) -> bool:
        return _TOOL_WORD_RE.search(inp.command) is not None

    def validate(self, inp: HookInput) -> HookAsk | None:
        for words in _simple_commands(command=inp.command):
            flag = exec_flag(words=words)
            if flag:
                tool = Path(words[0]).name
                return HookAsk(
                    message=_ASK_MESSAGE.format(tool=tool, flag=flag),
                    reason=f"DX018: `{tool} {flag}` executes another program.",
                )
        return None
