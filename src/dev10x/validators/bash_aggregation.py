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
  - 2+ statement chains:     cmd1; cmd2   (GH-1316: was 3+, a 2-statement
    chain of already-allowed commands still shifted the matched prefix
    and slipped through undetected)
  - 2+ statements on bare newlines: cmd1\ncmd2   (GH-1350: two commands on
    separate lines with no `;` at all were invisible to the chain count)

False-positive guard: single-quoted strings are stripped before scanning so
`grep 'for x in y'` does not match the for-loop pattern. Statement-separator
counting additionally strips double-quoted spans (GH-1350) so an embedded
literal `;` or newline inside a quoted string — a multi-line `-m` commit
message, inline JSON/YAML — is never mistaken for a chain boundary. That
extra stripping is scoped to separator counting only: `$(...)` still
executes inside double quotes in bash, so nested-substitution detection
keeps scanning the single-quote-only text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import ClassVar

from dev10x.domain import HookInput, HookResult
from dev10x.domain.common.bash_tokens import strip_line_continuations, strip_quoted_spans
from dev10x.domain.profile_tier import ProfileTier
from dev10x.validators.base import ValidatorBase

SINGLE_QUOTED_RE = re.compile(r"'[^']*'")

FOR_LOOP_RE = re.compile(r"\bfor\s+\w+\s+in\b.*\bdo\b", re.DOTALL)
WHILE_LOOP_RE = re.compile(r"\bwhile\b.+?\bdo\b", re.DOTALL)
UNTIL_LOOP_RE = re.compile(r"\buntil\b.+?\bdo\b", re.DOTALL)

# GH-1350: also matches a bare newline before the keyword, so a
# multi-line `if …\nthen …\nfi` (or `while …\ndo …\ndone`) is not
# miscounted as a bare-newline statement chain — the same protection
# `;\s*then` already gave the single-line form.
CONTROL_FLOW_SEPARATOR_RE = re.compile(r"(?:;|\n)\s*(?:then|do|else|elif|fi|done)\b")

# GH-1350: a newline immediately AFTER `then`/`do`/`else` opens that
# clause's body — it plays the same role the single space in
# `then echo yes` plays on one line, not a chain boundary. Applied
# BEFORE CONTROL_FLOW_SEPARATOR_RE (which deletes the keyword along
# with a separator immediately before it), so the keyword is still
# present here to anchor on. `elif`/`fi`/`done` are excluded: `elif`
# opens a new condition (not a body), and a newline after `fi`/`done`
# is a genuine separator — code after the block is a new command.
CONTROL_FLOW_BODY_START_RE = re.compile(r"\b(then|do|else)\b\s*\n")

GUIDANCE_MSG = """\
⛔  Shell aggregation detected — use serialized commands instead.

Shell aggregation (for/while/until loops, nested $(...), 2+ ;-chained
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
    """Count statement separators that are NOT control-flow continuations.

    GH-1316: a single remaining `;` is already a 2-statement chain
    (`cmd1; cmd2`) — the threshold used to require 2 separators (3
    statements), so a 2-statement chain of already-allowed commands
    shifted the matched prefix and slipped through undetected.

    GH-1350: a bare newline is the same shape as `;` — `cmd1\\ncmd2`
    shifts the matched prefix identically, just with no separator
    character at all. Callers pass a ``command`` that has already been
    quote-stripped (``strip_quoted_spans``) so an embedded literal `;`
    or newline inside a quoted string is not counted. A backslash-newline
    line continuation is joined first so a single command wrapped across
    lines never counts as a chain.
    """
    cleaned = strip_line_continuations(command=command)
    cleaned = CONTROL_FLOW_BODY_START_RE.sub(r"\1 ", cleaned)
    cleaned = CONTROL_FLOW_SEPARATOR_RE.sub("", cleaned)
    segments = [seg for seg in re.split(r"[;\n]", cleaned) if seg.strip()]
    return max(len(segments) - 1, 0)


@dataclass
class BashAggregationValidator(ValidatorBase):
    name: ClassVar[str] = "bash-aggregation"
    rule_id: ClassVar[str] = "DX010"
    profile: ClassVar[ProfileTier] = ProfileTier.STANDARD

    def should_run(self, inp: HookInput) -> bool:
        cmd = inp.command
        return (
            "for " in cmd
            or "while " in cmd
            or "until " in cmd
            or ";" in cmd
            or "$(" in cmd
            # GH-1350: a bare-newline chain has none of the shapes above.
            or "\n" in cmd
        )

    def validate(self, inp: HookInput) -> HookResult | None:
        scan = _strip_single_quoted(command=inp.command)

        if FOR_LOOP_RE.search(scan):
            return HookResult(message=GUIDANCE_MSG)
        if WHILE_LOOP_RE.search(scan):
            return HookResult(message=GUIDANCE_MSG)
        if UNTIL_LOOP_RE.search(scan):
            return HookResult(message=GUIDANCE_MSG)
        # Depth >= 2 means a $() nested inside another $() — the
        # aggregation shape. A single top-level $() is allowed. Scanned
        # against `scan` (single-quote-stripped only): $(...) still
        # executes inside double quotes, so double-quoted spans must stay
        # visible here.
        if _count_nested_substitutions(command=scan) >= 2:
            return HookResult(message=GUIDANCE_MSG)
        # GH-1350: statement-separator counting uses a separately
        # quote-stripped scan (both quote types) so an embedded literal
        # `;`/newline inside a quoted string is never counted as a chain
        # boundary.
        chain_scan = strip_quoted_spans(command=inp.command)
        if _count_chained_statements(command=chain_scan) >= 1:
            return HookResult(message=GUIDANCE_MSG)
        return None
