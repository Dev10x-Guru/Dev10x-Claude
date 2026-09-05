"""Validator: PR base branch targeting.

Rewritten from validate-pr-base.sh to Python.

Validates that `gh pr create` includes `--base <detected_branch>`.
Detects the base branch dynamically (develop > development >
main > master > trunk). Allows --force to bypass.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import ClassVar

from dev10x import subprocess_utils
from dev10x.domain import HookInput, HookResult
from dev10x.domain.common.branch_name import BASE_BRANCH_PRIORITY
from dev10x.domain.profile_tier import ProfileTier
from dev10x.domain.rules.validation_rule import is_search_command
from dev10x.validators.base import ValidatorBase

GH_PR_CREATE_RE = re.compile(r"gh\s+pr\s+create")


def _detect_base_branch() -> str | None:
    for candidate in BASE_BRANCH_PRIORITY:
        result = subprocess_utils.run(
            ["git", "rev-parse", "--verify", f"origin/{candidate}"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return candidate
    return None


@dataclass
class PrBaseValidator(ValidatorBase):
    name: ClassVar[str] = "pr-base"
    rule_id: ClassVar[str] = "DX005"
    profile: ClassVar[ProfileTier] = ProfileTier.MINIMAL

    def should_run(self, inp: HookInput) -> bool:
        # A search tool naming `gh pr create` in its pattern is looking
        # for the command, not running it — demanding a --base flag of
        # `rg -n 'gh pr create --body-file' skills/` blocks the audit
        # rather than the mistake (GH-1214 finding 6).
        #
        # That shape was observed, not hypothesised: it is the second of
        # two live denials behind finding 6. DX005 needs this call of its
        # own because it matches the raw command string here, never
        # reaching `MatchingRule.matches_command` where the same
        # exemption already lived — which is why `is_search_command` was
        # promoted out of the rule engine rather than fixed in place.
        if is_search_command(command=inp.command):
            return False
        return GH_PR_CREATE_RE.search(inp.command) is not None

    def validate(self, inp: HookInput) -> HookResult | None:
        command = inp.command

        if "--force" in command:
            return None

        base_branch = _detect_base_branch()
        if base_branch is None:
            return HookResult(
                message=(
                    "BLOCKED: Cannot detect base branch \u2014 no develop, main, "
                    "master, or trunk found on origin.\n"
                    "Fetch remotes with 'git fetch' and retry."
                )
            )

        pattern = re.compile(rf"--base\s+{re.escape(base_branch)}")
        if not pattern.search(command):
            return HookResult(
                message=(
                    f"BLOCKED: gh pr create must include '--base {base_branch}'.\n"
                    f"Add '--base {base_branch}' to the command, or use --force to override."
                )
            )

        return None
