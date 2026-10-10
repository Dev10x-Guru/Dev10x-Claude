"""Advisory validator: surface likely-redundant content fetches (GH-206).

Two signals catch the patterns where an agent re-fetches file content
that is already available in a prior tool result:

1. ``gh api .../contents/<path>?ref=<branch>`` — the GitHub Contents API
   shape. If a ``gh pr diff`` ran earlier in the session, the file is
   already in the cached diff output (Claude Code persists oversized
   tool results to ``tool-results/*.txt``).
2. ``python3 -c "...base64.b64decode..."`` piped to or from another
   command — strong hint that the agent is unwrapping a Contents API
   JSON envelope. The ``-c`` body itself is gated by other validators,
   but this validator surfaces the *intent* (redundant fetch) rather
   than the symptom (inline python).

Output is always :class:`HookAllow` with a ``systemMessage`` — the
call proceeds, but the supervisor sees the hint at decision time.
Hard ``deny`` would be wrong here because a fresh fetch is sometimes
legitimate (file outside diff paths, branch tip moved, full file
content needed around a hunk).

This validator is **experimental** (rule_id DX009). Opt in with
``DEV10X_HOOK_EXPERIMENTAL=1`` until session-cache-aware path
matching lands.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import ClassVar

from dev10x.domain import HookAllow, HookInput
from dev10x.domain.profile_tier import ProfileTier
from dev10x.validators.base import ValidatorBase

_CONTENTS_FETCH_RE = re.compile(
    r"gh\s+api\s+(?:-X\s+GET\s+)?(?:/?repos/)?[^\s|<>]+/contents/(?P<path>[^\s?]+)"
)

_BASE64_PIPE_RE = re.compile(r"python3?\s+-c\s+['\"][^'\"]*base64\s*\.\s*b64decode[^'\"]*['\"]")


def _contents_advisory(*, path: str) -> str:
    return (
        f"💡 Possibly redundant fetch (GH-206).\n\n"
        f"Fetching `{path}` via the GitHub Contents API. If a `gh pr diff` "
        f"ran earlier in this session, the file's content is already in "
        f"the cached diff output — grep there before re-fetching.\n\n"
        f"This is an advisory signal only; the call will proceed. "
        f"Re-fetch is fine when the file is outside the diff path filters, "
        f"the branch tip moved, or you need full file context around a hunk."
    )


_BASE64_ADVISORY = (
    "💡 Possibly redundant fetch (GH-206).\n\n"
    "This pipe unwraps a base64-encoded GitHub Contents API payload — a "
    "strong hint that the same file content was just fetched. The cached "
    "`gh pr diff` output from earlier in the session usually has it "
    "already; grep there first.\n\n"
    "This is an advisory signal only; the call will proceed."
)


@dataclass
class RedundantFetchValidator(ValidatorBase):
    name: ClassVar[str] = "redundant-fetch"
    rule_id: ClassVar[str] = "DX009"
    profile: ClassVar[ProfileTier] = ProfileTier.STANDARD
    experimental: ClassVar[bool] = True

    def should_run(self, inp: HookInput) -> bool:
        cmd = inp.command
        if "base64" in cmd and "b64decode" in cmd:
            return True
        return "contents/" in cmd and "gh" in cmd and "api" in cmd

    def validate(self, inp: HookInput) -> HookAllow | None:
        cmd = inp.command

        if _BASE64_PIPE_RE.search(cmd):
            return HookAllow(message=_BASE64_ADVISORY)

        match = _CONTENTS_FETCH_RE.search(cmd)
        if match:
            path = match.group("path").split("?")[0]
            return HookAllow(message=_contents_advisory(path=path))

        return None
