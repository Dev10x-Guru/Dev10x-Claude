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

from dev10x.domain import HookAllow, HookAsk, HookInput
from dev10x.domain.profile_tier import ProfileTier
from dev10x.domain.sensitivity import (
    ExceptionEffect,
    SensitivityClassifier,
    SensitivityException,
    SensitivityMatch,
    SensitivityPattern,
    resolve_exception_effect,
)
from dev10x.validators.base import ValidatorBase
from dev10x.validators.sensitivity_exceptions import load_sensitivity_exceptions

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


def _ask_reason(matches: list[SensitivityMatch]) -> str:
    """One-line ``permissionDecisionReason`` for the approval dialog."""
    labels = ", ".join(sorted({m.label.value.upper() for m in matches}))
    return f"DX014 sensitivity axis: {labels} target — approve only if intentional and safe."


@dataclass
class SensitivityTargetValidator(ValidatorBase):
    """Elevate commands matching the PAP sensitivity wordlist to ``ask``.

    Uses ``SensitivityClassifier`` to check the full command string
    against the default wordlist. When *any* sensitivity pattern fires,
    the sensitivity axis elevates the effective effect to ``ask``
    (``HookAsk``) — a prompt the user can approve in-session — rather
    than a hard ``deny`` that drops them to a manual ``!`` shell (GH-604,
    evidence #3). Genuine destructive writes are still hard-denied by the
    safety-tier validators (DX001–DX005/DX012), which run *before* DX014
    in the chain and short-circuit on a ``deny``.

    A user-owned, synced exception catalog (Tier 2,
    ``~/.config/Dev10x/sensitivity-exceptions.yaml``) can downgrade a
    blessed read-only probe from ``ask`` to ``allow`` — see
    ``with_exceptions`` and :func:`resolve_exception_effect`.

    The wordlist can be customised per test by injecting a ``classifier``
    instance; the exception catalog can be injected via ``exceptions``
    (``None`` = lazy-load from the user config; production default).
    """

    name: ClassVar[str] = "sensitivity-target"
    rule_id: ClassVar[str] = "DX014"
    profile: ClassVar[ProfileTier] = ProfileTier.STANDARD

    classifier: SensitivityClassifier = field(
        default_factory=SensitivityClassifier,
        repr=False,
    )
    exceptions: list[SensitivityException] | None = field(default=None, repr=False)
    _loaded_exceptions: list[SensitivityException] | None = field(
        default=None,
        init=False,
        repr=False,
        compare=False,
    )

    def should_run(self, inp: HookInput) -> bool:
        """Fast pre-check: skip entirely if command is very short or empty.

        The full classify() call happens only in validate(); should_run()
        intentionally errs on the side of running so no sensitive command
        is silently passed.
        """
        return bool(inp.command.strip())

    def validate(self, inp: HookInput) -> HookAsk | HookAllow | None:
        """Elevate a sensitive command to ``ask``, or ``allow`` if blessed.

        Any sensitivity match wins over tier/reversibility (deny-overrides
        on the sensitivity axis). A matching exception-catalog entry with
        effect ``allow`` downgrades the hit to a silent ``HookAllow``; an
        explicit ``ask`` entry — or no matching entry — keeps the ``ask``
        prompt. The catalog is consulted only after a match, so benign
        commands never touch the filesystem.
        """
        matches = self.classifier.classify(command=inp.command)
        if not matches:
            return None
        effect = resolve_exception_effect(
            matches=matches,
            command=inp.command,
            exceptions=self._resolved_exceptions(),
        )
        if effect is ExceptionEffect.ALLOW:
            return HookAllow()
        message = _ASK_MSG_TEMPLATE.format(
            count=len(matches),
            matches_detail=_format_matches(matches=matches),
        )
        return HookAsk(message=message, reason=_ask_reason(matches=matches))

    def _resolved_exceptions(self) -> list[SensitivityException]:
        """Return injected exceptions, else lazily load (and cache) the catalog."""
        if self.exceptions is not None:
            return self.exceptions
        if self._loaded_exceptions is None:
            self._loaded_exceptions = load_sensitivity_exceptions()
        return self._loaded_exceptions

    def with_patterns(self, patterns: list[SensitivityPattern]) -> SensitivityTargetValidator:
        """Return a new validator instance using the supplied wordlist.

        Useful for tests and for project-local sensitivity overrides.
        Preserves any injected exception catalog.
        """
        return SensitivityTargetValidator(
            classifier=SensitivityClassifier(patterns=patterns),
            exceptions=self.exceptions,
        )

    def with_exceptions(
        self, exceptions: list[SensitivityException]
    ) -> SensitivityTargetValidator:
        """Return a new validator using the supplied exception catalog.

        Mirrors ``with_patterns`` — the seam GH-604 uses to inject the
        user-owned, synced sensitivity-exception catalog.
        """
        return SensitivityTargetValidator(
            classifier=self.classifier,
            exceptions=exceptions,
        )
