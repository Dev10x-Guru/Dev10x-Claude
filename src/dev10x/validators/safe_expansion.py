"""Validator: auto-approve commands whose shell metacharacters are inert.

Claude Code's permission layer flags commands containing variable
expansions, ANSI-C strings, brace expressions inside single quotes, or
route-group parens in paths even though those characters are either
literal (inside single quotes / ANSI-C / known-safe env vars) or do
not expand to anything the user has not approved.

This validator pre-approves commands when every "scary" pattern is
accounted for by one of:

  - A literal single-quoted span (already inert in POSIX shell)
  - A fixed ANSI-C escape (``$'\\t'``, ``$'\\n'``, ``$'\\0'``,
    ``$'\\\\'``)
  - An expansion of a known-safe env var (``$CLAUDE_PLUGIN_ROOT``,
    ``$HOME``, ``$USER``, ``$PWD``, ``$PATH``, both ``$NAME`` and
    ``${NAME}`` forms)
  - A path-like token containing ``(group)`` segments, such as
    SvelteKit route groups (``apps/web/routes/(app)/...``)

Genuine threats remain blocked because they are NOT covered by any of
the above. Command substitutions ``$(...)``, backticks, and unquoted
``${var:-$(...)}`` injections still drop through to deny-validators.

Source: GH-309 (evidence #13, #20, #49, #63, #69, #88 from GH-271).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import ClassVar

from dev10x.domain import HookAllow, HookInput, HookResult
from dev10x.domain.profile_tier import ProfileTier
from dev10x.validators._quote_strip import quote_strip
from dev10x.validators.base import ValidatorBase

SAFE_ENV_VARS = frozenset(
    [
        "CLAUDE_PLUGIN_ROOT",
        "HOME",
        "USER",
        "PWD",
        "PATH",
        "TMPDIR",
        "OLDPWD",
        "SHELL",
        "LANG",
    ]
)

_SAFE_ENV_NAMES = "|".join(sorted(SAFE_ENV_VARS))
_SAFE_ENV_RE = re.compile(r"\$(?:(" + _SAFE_ENV_NAMES + r")\b|\{(" + _SAFE_ENV_NAMES + r")\})")
_ROUTE_GROUP_RE = re.compile(r"(?<=[A-Za-z0-9_./-])\([A-Za-z0-9_-]+\)(?=[/])")
_DOLLAR_RE = re.compile(r"\$")
_OPEN_PAREN_RE = re.compile(r"\(")
_CLOSE_PAREN_RE = re.compile(r"\)")
_OPEN_BRACE_RE = re.compile(r"\{")
_CLOSE_BRACE_RE = re.compile(r"\}")
_BACKTICK_RE = re.compile(r"`")


def _has_dangerous_residue(stripped: str) -> bool:
    """True if anything in the quote-stripped command still looks risky.

    Called after the safe-env-var and route-group patterns are removed
    from the stripped command. Any remaining ``$``, parens, braces, or
    backticks indicates a substitution or expansion the validator is
    not confident enough to auto-approve.
    """
    residue = _SAFE_ENV_RE.sub("", stripped)
    residue = _ROUTE_GROUP_RE.sub("", residue)
    if _DOLLAR_RE.search(residue):
        return True
    if _BACKTICK_RE.search(residue):
        return True
    if _OPEN_PAREN_RE.search(residue) or _CLOSE_PAREN_RE.search(residue):
        return True
    if _OPEN_BRACE_RE.search(residue) or _CLOSE_BRACE_RE.search(residue):
        return True
    return False


def _has_only_inert_metacharacters(command: str) -> bool:
    """True iff every metacharacter in ``command`` is inert or known-safe."""
    stripped = quote_strip(command=command)
    return not _has_dangerous_residue(stripped=stripped)


@dataclass
class SafeExpansionValidator(ValidatorBase):
    name: ClassVar[str] = "safe-expansion"
    rule_id: ClassVar[str] = "DX012"
    profile: ClassVar[ProfileTier] = ProfileTier.MINIMAL

    def should_run(self, inp: HookInput) -> bool:
        command = inp.command
        if "$" in command or "`" in command:
            return True
        if "(" in command or "{" in command:
            return True
        return False

    def validate(self, inp: HookInput) -> HookAllow | HookResult | None:
        if _has_only_inert_metacharacters(command=inp.command):
            return HookAllow()
        return None
