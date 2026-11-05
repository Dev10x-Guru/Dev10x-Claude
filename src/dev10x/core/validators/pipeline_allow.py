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

Since GH-1795 the approval is real: it emits ``permissionDecision:
"allow"``. So the pipeline is read by the shared segmenter, never split on
raw ``|`` text, and anything the segmenter cannot vouch for abstains.

Out of scope (do NOT auto-approve):
  - Any operator other than a plain ``|``: ``&&``, ``||``, ``;``, ``&``,
    ``|&``, a newline, a subshell or process substitution ``<(...)``
  - ``$(...)`` or backtick command substitution anywhere in the command
  - A redirect other than to ``/dev/null`` or an fd duplicate (``2>&1``):
    a file redirect writes or reads something no allow-rule named
  - Segments leading with ``xargs`` / ``tee`` — these execute or write
    their argument, which needs the argument's allow-rule
  - A command the segmenter cannot tokenize
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import ClassVar

from dev10x.domain import HookAllow, HookInput
from dev10x.domain.common.bash_tokens import (
    CommandSegment,
    Redirect,
    UntokenizableCommandError,
    command_segments,
    substitution_bodies,
)
from dev10x.domain.profile_tier import ProfileTier
from dev10x.validators.base import ValidatorBase
from dev10x.validators.prefix_friction import (
    _load_all_allow_patterns,
    _matches_allow_rule,
)

_ARG_EXECUTORS = frozenset({"xargs", "tee"})
_HARMLESS_TARGETS = frozenset({"/dev/null"})

_AUTO_APPROVE_MSG = (
    "✓ Pipeline auto-approved — every segment matches an existing Bash allow-rule (Dev10x DX011)."
)


def _is_harmless(redirect: Redirect) -> bool:
    """True for a redirect that touches no file: ``/dev/null`` or ``2>&1``."""
    operator = redirect.operator.lstrip("0123456789")
    if operator in (">&", "<&"):
        return redirect.target.isdigit() or redirect.target == "-"
    return not redirect.feeds_inline_text and redirect.target in _HARMLESS_TARGETS


def _pipeline_segments(*, command: str) -> tuple[CommandSegment, ...] | None:
    """The segments of a plain ``a | b | c`` pipeline, else ``None``."""
    # A trailing `&` backgrounds the pipeline without opening a segment,
    # so the segment openers alone cannot see it.
    if "\n" in command or command.rstrip()[-1:] in (";", "&", "|"):
        return None
    if substitution_bodies(command, include_backticks=True):
        return None
    try:
        segments = command_segments(command=command)
    except UntokenizableCommandError:
        return None
    if len(segments) < 2:
        return None
    if segments[0].opener or any(segment.opener != "|" for segment in segments[1:]):
        return None
    if any(
        not segment.argv or not all(_is_harmless(r) for r in segment.redirects)
        for segment in segments
    ):
        return None
    return segments


@dataclass
class PipelineAllowValidator(ValidatorBase):
    """Auto-approve pipelines whose segments are all allow-rule matched."""

    name: ClassVar[str] = "pipeline-allow"
    rule_id: ClassVar[str] = "DX011"
    profile: ClassVar[ProfileTier] = ProfileTier.STANDARD
    _allow_patterns: list[str] | None = field(default=None, repr=False)

    def should_run(self, inp: HookInput) -> bool:
        return "|" in inp.command

    def validate(self, inp: HookInput) -> HookAllow | None:
        segments = _pipeline_segments(command=inp.command)
        if segments is None:
            return None

        if self._allow_patterns is None:
            self._allow_patterns = _load_all_allow_patterns()
        if not self._allow_patterns:
            return None

        for segment in segments:
            if PurePosixPath(segment.argv[0]).name in _ARG_EXECUTORS:
                return None
            if _matches_allow_rule(shlex.join(segment.argv), self._allow_patterns) is None:
                return None

        return HookAllow(message=_AUTO_APPROVE_MSG, decides=True)
