"""Validator: block $(cat ...) where a file flag should be used.

Commands like `gh api -f body="$(cat /tmp/file)"` should use
`gh api -F body=@/tmp/file` instead. Command substitution with cat
breaks allow-rule prefix matching and is always replaceable with a
file flag in Claude Code workflows.

Common replacements:
  $(cat file) in gh api -f  → -F field=@file
  $(cat file) in git commit -m → git commit -F file
  $(cat file) in gh pr create --body → --body-file file
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import ClassVar

from dev10x.domain import HookInput, HookResult
from dev10x.domain.profile_tier import ProfileTier
from dev10x.validators._quote_strip import quote_strip
from dev10x.validators.base import ValidatorBase

CAT_SUBSHELL_RE = re.compile(r"\$\(cat\s+\S+\)")

BLOCK_MSG = """\
BLOCKED: $(cat ...) command substitution detected.

Use a file flag instead of command substitution:
  gh api -f body="$(cat file)"  →  gh api -F body=@file
  git commit -m "$(cat file)"   →  git commit -F file
  gh pr create --body "$(cat …)" →  gh pr create --body-file file

Why: $(…) breaks allow-rule prefix matching and is unnecessary
when the tool supports reading from a file directly."""


@dataclass
class CommandSubstitutionValidator(ValidatorBase):
    name: ClassVar[str] = "command-substitution"
    rule_id: ClassVar[str] = "DX002"
    profile: ClassVar[ProfileTier] = ProfileTier.MINIMAL

    def should_run(self, inp: HookInput) -> bool:
        return "$(cat " in quote_strip(command=inp.command)

    def validate(self, inp: HookInput) -> HookResult | None:
        if CAT_SUBSHELL_RE.search(quote_strip(command=inp.command)):
            return HookResult(message=BLOCK_MSG)
        return None
