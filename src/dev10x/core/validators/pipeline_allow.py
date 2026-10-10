"""Validator: auto-approve pipelines when every segment matches an allow-rule.

Claude Code's allow-rule matcher operates on the whole command string, not
on individual pipeline segments. So `cmd | tail -20` is not covered by
``Bash(cmd:*)`` + ``Bash(tail:*)`` independently — neither rule matches
the full pipeline string, and the agent's only escape is to broaden one
of the rules.

This validator restores narrow-rule coverage for the trimmer pattern
(``cmd | tail``, ``cmd | head``, ``cmd | wc -l``) by approving when
every segment is independently allowed. A pipeline is no more dangerous
than the union of its segments — if each segment is independently
pre-approved, the composition is too.

Out of scope (do NOT auto-approve):
  - Process substitution ``<(...)`` / ``>(...)`` — effectively subshells
  - Backgrounding ``&`` — different execution semantics
  - Logical operators ``&&`` / ``||`` — handled by the chaining hook
  - ``;`` chains — handled by the chaining hook
  - ``$(...)`` command substitution inside the pipeline
  - Segments leading with ``xargs`` / ``tee`` — these execute their
    argument, which needs the argument's allow-rule, not the wrapper's
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import ClassVar

from dev10x.domain import HookAllow, HookInput
from dev10x.domain.profile_tier import ProfileTier
from dev10x.validators.base import ValidatorBase
from dev10x.validators.prefix_friction import (
    _load_all_allow_patterns,
    _matches_allow_rule,
)

_TRAILING_REDIRECT_RE = re.compile(r"\s+\d?>{1,2}(?:&\d+|\s*\S+)(?=\s|$)")

_PROCESS_SUBSTITUTION_RE = re.compile(r"[<>]\(")

_TRAILING_BACKGROUND_RE = re.compile(r"(?<!&)&\s*$")

_ARG_EXECUTORS = frozenset({"xargs", "tee"})

_AUTO_APPROVE_MSG = (
    "✓ Pipeline auto-approved — every segment matches an existing Bash allow-rule (Dev10x DX011)."
)


def _strip_trailing_redirects(segment: str) -> str:
    """Strip trailing stderr/stdout redirects so the underlying command matches."""
    prev = ""
    out = segment
    while prev != out:
        prev = out
        out = _TRAILING_REDIRECT_RE.sub("", out).rstrip()
    return out


def _split_pipeline(command: str) -> list[str]:
    """Split on ``|`` (single pipe) into trimmed, non-empty segments."""
    return [s.strip() for s in command.split("|") if s.strip()]


def _first_token(segment: str) -> str:
    tokens = segment.split()
    return tokens[0] if tokens else ""


@dataclass
class PipelineAllowValidator(ValidatorBase):
    """Auto-approve pipelines whose segments are all allow-rule matched."""

    name: ClassVar[str] = "pipeline-allow"
    rule_id: ClassVar[str] = "DX011"
    profile: ClassVar[ProfileTier] = ProfileTier.STANDARD
    _allow_patterns: list[str] | None = field(default=None, repr=False)

    def should_run(self, inp: HookInput) -> bool:
        cmd = inp.command
        if "|" not in cmd or "||" in cmd:
            return False
        if "&&" in cmd or ";" in cmd:
            return False
        if "$(" in cmd or "`" in cmd:
            return False
        if _PROCESS_SUBSTITUTION_RE.search(cmd):
            return False
        if _TRAILING_BACKGROUND_RE.search(cmd):
            return False
        return True

    def validate(self, inp: HookInput) -> HookAllow | None:
        segments = _split_pipeline(command=inp.command)
        if len(segments) < 2:
            return None

        if self._allow_patterns is None:
            self._allow_patterns = _load_all_allow_patterns()
        if not self._allow_patterns:
            return None

        for segment in segments:
            stripped = _strip_trailing_redirects(segment=segment)
            if _first_token(stripped) in _ARG_EXECUTORS:
                return None
            if _matches_allow_rule(stripped, self._allow_patterns) is None:
                return None

        return HookAllow(message=_AUTO_APPROVE_MSG)
