"""Validator: block MCP tool names pasted as Bash commands.

MCP tool identifiers (``mcp__<server>__<tool>``) are Claude tool-call
primitives. They cannot be executed as shell commands. Agents sometimes
paste them into Bash with arguments appended, e.g.::

    mcp__plugin_Dev10x_cli__check_top_level_comments pr_number=357

This validator detects that anti-pattern — the command's first executable
token IS an MCP identifier — and hard-blocks it with a steering message
pointing back to the tool-call protocol (see .claude/rules/mcp-tools.md).

It deliberately does NOT flag commands that merely contain ``mcp__`` in an
argument or substring (e.g. ``grep mcp__ tests/``); only the command name
position matters.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from typing import ClassVar

from dev10x.domain import HookInput, HookResult
from dev10x.domain.profile_tier import ProfileTier
from dev10x.validators.base import ValidatorBase

ENV_VAR_RE = re.compile(r"^[A-Z_][A-Z0-9_]*=\S*$")

MCP_TOOL_RE = re.compile(r"^mcp__[a-zA-Z0-9_]+__[a-zA-Z0-9_]+")

MCP_PREFIX_MSG = """\
⛔  MCP tool name used as a shell command — blocked.

`{tool}` is a Claude tool-call primitive, NOT a shell command. It
cannot be run via Bash. Invoke it directly through the tool-call
protocol instead:

  Tool: `{tool}`

Pass parameters as named tool-call arguments (e.g. `pr_number=357`),
not as shell tokens. See `.claude/rules/mcp-tools.md` — MCP tool names
belong only in `allowed-tools:` declarations and Claude tool-call
invocations, never in bash blocks or shell scripts."""


def _strip_env_prefix(parts: list[str]) -> list[str]:
    i = 0
    while i < len(parts) and ENV_VAR_RE.match(parts[i]):
        i += 1
    return parts[i:]


@dataclass
class McpPrefixValidator(ValidatorBase):
    name: ClassVar[str] = "mcp-prefix"
    rule_id: ClassVar[str] = "DX013"
    profile: ClassVar[ProfileTier] = ProfileTier.STANDARD

    def should_run(self, inp: HookInput) -> bool:
        return "mcp__" in inp.command

    def validate(self, inp: HookInput) -> HookResult | None:
        try:
            parts = shlex.split(inp.command)
        except ValueError:
            return None

        parts = _strip_env_prefix(parts)

        if not parts:
            return None

        if not MCP_TOOL_RE.match(parts[0]):
            return None

        return HookResult(message=MCP_PREFIX_MSG.format(tool=parts[0]))
