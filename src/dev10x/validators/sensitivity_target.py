"""Validator: elevate effect to ``ask`` for sensitive-target commands (DX014).

Wires ``SensitivityClassifier`` (from GH-395) into the bash validator
pipeline as a standalone rule.  This implements the deny-overrides
resolution across the three PAP axes:

    (tier) × (reversibility) × (sensitivity)

A command that is trivially reversible and in a safe-read tier still
triggers ``ask`` when its target or query matches the sensitivity
wordlist.  The sensitivity axis overrides the other two — deny-overrides
semantics apply.

This maps to the Cedar ``@sensitivity`` annotation pattern:

    @sensitivity("secret|credential|pii|infra")
    permit(principal, action, resource)
    when { resource matches sensitive_wordlist };

Deny-overrides resolution: if *any* axis emits ``ask``/``forbid``,
that effect wins.  DX014 provides the sensitivity axis; existing
validators cover tier (DX003, DX004) and reversibility (future).

Cross-references:
- GH-395: SensitivityClassifier domain model
- GH-310: Sequence/unattended gate (complements per-command sensitivity)
- GH-371: resource-classification / capability_group (horizontal MCP
  duplicate detection; ``capability_group`` annotation is the Cedar
  equivalent of the sensitivity label on the resource side)
- GH-271: Evidence corpus — fixtures #267–#273 directly drove the
  default wordlist in ``SensitivityClassifier``
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

from dev10x.domain import HookInput, HookResult
from dev10x.domain.profile_tier import ProfileTier
from dev10x.domain.sensitivity import SensitivityClassifier, SensitivityMatch, SensitivityPattern
from dev10x.validators.base import ValidatorBase

_ASK_MSG_TEMPLATE = """\
⚠️  Sensitive target detected — command requires review before execution.

Rule DX014 matched {count} sensitivity pattern(s):
{matches_detail}

This command touches sensitive infrastructure, credentials, secrets,
or PII.  Even if the operation is read-only or reversible on the tier/
reversibility axes, the sensitivity axis elevates the effective effect
to ``ask`` (deny-overrides).

Review the command carefully.  If it is intentional and safe, approve it
explicitly.  See `.claude/rules/hook-patterns.md` — DX014 / sensitivity
axis — for the full resolution rules.
"""


def _format_matches(matches: list[SensitivityMatch]) -> str:
    lines = []
    for m in matches:
        lines.append(f"  • [{m.label.value.upper()}] {m.pattern!r} — matched: {m.matched_text!r}")
    return "\n".join(lines)


@dataclass
class SensitivityTargetValidator(ValidatorBase):
    """Block commands that match the PAP sensitivity wordlist.

    Uses ``SensitivityClassifier`` to check the full command string
    against the default wordlist.  Returns a ``HookResult`` (deny with
    message) when *any* sensitivity pattern fires, implementing the
    deny-overrides rule: a sensitivity hit on the third axis elevates
    the effective effect regardless of tier and reversibility scores.

    The wordlist can be customised per test by injecting a ``classifier``
    instance; production code always uses the default wordlist.
    """

    name: ClassVar[str] = "sensitivity-target"
    rule_id: ClassVar[str] = "DX014"
    profile: ClassVar[ProfileTier] = ProfileTier.STANDARD

    classifier: SensitivityClassifier = field(
        default_factory=SensitivityClassifier,
        repr=False,
    )

    def should_run(self, inp: HookInput) -> bool:
        """Fast pre-check: skip entirely if command is very short or empty.

        The full classify() call happens only in validate(); should_run()
        intentionally errs on the side of running so no sensitive command
        is silently passed.
        """
        return bool(inp.command.strip())

    def validate(self, inp: HookInput) -> HookResult | None:
        """Return a HookResult if the command matches the sensitivity wordlist.

        Deny-overrides: any sensitivity match wins over tier/reversibility.
        """
        matches = self.classifier.classify(command=inp.command)
        if not matches:
            return None
        matches_detail = _format_matches(matches=matches)
        message = _ASK_MSG_TEMPLATE.format(
            count=len(matches),
            matches_detail=matches_detail,
        )
        return HookResult(message=message)

    def with_patterns(self, patterns: list[SensitivityPattern]) -> SensitivityTargetValidator:
        """Return a new validator instance using the supplied wordlist.

        Useful for tests and for project-local sensitivity overrides.
        """
        return SensitivityTargetValidator(
            classifier=SensitivityClassifier(patterns=patterns),
        )
