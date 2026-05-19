"""Validator: block shell-aggregation shapes; steer agents to serialized commands.

Agents reach for shell aggregation when probing a codebase — for/while/until
loops, nested $(...) substitution, and 3+ ;-chained statements packed into a
single Bash call. These shapes shift the effective allow-rule prefix so no
pre-approved rule fires, then trigger per-call permission prompts. The intent
is almost always "inspect N files / N directories", which Glob + Read +
one-simple-command-per-call accomplishes without friction.

Patterns blocked:
  - for/while/until loops:   for d in src/*/; do ... done
  - nested $(...) substitution: $(... $(...) ...)
  - 3+ statement chains:     cmd1; cmd2; cmd3

False-positive guard: single-quoted strings are stripped before scanning so
`grep 'for x in y'` does not match the for-loop pattern.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import ClassVar

from dev10x.domain import HookInput, HookResult
from dev10x.domain.profile_tier import ProfileTier
from dev10x.validators.base import ValidatorBase

SINGLE_QUOTED_RE = re.compile(r"'[^']*'")

FOR_LOOP_RE = re.compile(r"\bfor\s+\w+\s+in\b.*\bdo\b", re.DOTALL)
WHILE_LOOP_RE = re.compile(r"\bwhile\b.+?\bdo\b", re.DOTALL)
UNTIL_LOOP_RE = re.compile(r"\buntil\b.+?\bdo\b", re.DOTALL)

CONTROL_FLOW_SEPARATOR_RE = re.compile(r";\s*(?:then|do|else|elif|fi|done)\b")

GUIDANCE_MSG = """\
⛔  Shell aggregation detected — use serialized commands instead.

Shell aggregation (for/while/until loops, nested $(...), 3+ ;-chained
statements) shifts the effective Bash prefix so no allow-rule fires,
then triggers per-call permission prompts.

The intent is almost always "inspect N files / N directories" — use:

  - `Glob` for path enumeration (instead of `for d in src/*/; do ...`)
  - `Read` for known file paths (instead of `cat`/`wc` inside loops)
  - One simple command per Bash call (no `;` chaining, no subshells)

For aggregation/summarization, pre-read the inputs via Glob + Read and
let the model aggregate in-context — no shell loop required.

If a dedicated skill exists for your intent (e.g., `Dev10x:project-audit`
for codebase context detection), delegate to that skill instead."""


def _strip_single_quoted(command: str) -> str:
    """Remove single-quoted string contents so quoted keywords don't match."""
    return SINGLE_QUOTED_RE.sub("''", command)


def _count_nested_substitutions(command: str) -> int:
    """Return the maximum $(...) nesting depth.

    Depth 0 = no command substitution; depth 1 = a single $(...) at
    top level (safe — covered by DX001/DX002 where appropriate);
    depth 2+ = nested substitution like $(... $(...) ...), which is
    the aggregation shape this validator blocks.
    """
    max_depth = 0
    depth = 0
    i = 0
    while i < len(command) - 1:
        if command[i : i + 2] == "$(":
            depth += 1
            max_depth = max(max_depth, depth)
            i += 2
            continue
        if command[i] == ")" and depth > 0:
            depth -= 1
        i += 1
    return max_depth


def _count_chained_statements(command: str) -> int:
    """Count statement separators that are NOT control-flow continuations."""
    cleaned = CONTROL_FLOW_SEPARATOR_RE.sub("", command)
    return cleaned.count(";")


@dataclass
class BashAggregationValidator(ValidatorBase):
    name: ClassVar[str] = "bash-aggregation"
    rule_id: ClassVar[str] = "DX010"
    profile: ClassVar[ProfileTier] = ProfileTier.STANDARD

    def should_run(self, inp: HookInput) -> bool:
        cmd = inp.command
        return "for " in cmd or "while " in cmd or "until " in cmd or ";" in cmd or "$(" in cmd

    def validate(self, inp: HookInput) -> HookResult | None:
        scan = _strip_single_quoted(command=inp.command)

        if FOR_LOOP_RE.search(scan):
            return HookResult(message=GUIDANCE_MSG)
        if WHILE_LOOP_RE.search(scan):
            return HookResult(message=GUIDANCE_MSG)
        if UNTIL_LOOP_RE.search(scan):
            return HookResult(message=GUIDANCE_MSG)
        # Depth >= 2 means a $() nested inside another $() — the
        # aggregation shape. A single top-level $() is allowed.
        if _count_nested_substitutions(command=scan) >= 2:
            return HookResult(message=GUIDANCE_MSG)
        if _count_chained_statements(command=scan) >= 2:
            return HookResult(message=GUIDANCE_MSG)
        return None
