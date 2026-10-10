"""Validator protocol and base class for Bash command validation.

Two hook integration points:

  PreToolUse        → should_run() + validate()  — block before execution
  PermissionDenied  → should_run() + correct()   — guide after auto-mode denial

Correction support is structural, not declared: a validator opts into
the PermissionDenied path simply by implementing :meth:`Corrector.correct`.
The dispatcher discovers this via ``isinstance(validator, Corrector)``
against the ``@runtime_checkable`` :class:`Corrector` protocol — no
separate capability set to keep in sync with the actual methods.

Validators also declare profile-tier metadata as class attributes:

  rule_id       — stable identifier (e.g., ``"DX001"``)
  profile       — which :class:`ProfileTier` this validator participates in
  experimental  — opt-in flag for DEV10X_HOOK_EXPERIMENTAL=1

The :class:`ValidatorRegistry` verifies these match the corresponding
:class:`ValidatorSpec` at registration time, replacing the previous
post-instantiation monkey-patching.
"""

from __future__ import annotations

from typing import ClassVar, Protocol, runtime_checkable

from dev10x.domain import HookAllow, HookAsk, HookInput, HookResult, HookRetry
from dev10x.domain.profile_tier import ProfileTier


@runtime_checkable
class Validator(Protocol):
    name: str

    def should_run(self, inp: HookInput) -> bool:
        """Fast predicate — return False to skip this validator entirely."""
        ...

    def validate(self, inp: HookInput) -> HookResult | HookAllow | HookAsk | None:
        """Return HookResult to block, HookAllow to auto-approve, None for no opinion."""
        ...


@runtime_checkable
class Corrector(Protocol):
    """Optional extension for validators that support PermissionDenied corrections."""

    def correct(self, inp: HookInput) -> HookRetry | None:
        """Return HookRetry to suggest retry with corrective guidance, None otherwise."""
        ...


class ValidatorBase:
    """Mixin declaring registry metadata as class attributes.

    Inherit from this and override the class attributes:

        class FooValidator(ValidatorBase):
            name = "foo"
            rule_id = "DX042"
            profile = ProfileTier.STANDARD

    A validator that also implements :meth:`Corrector.correct` is
    automatically eligible for the PermissionDenied path — no capability
    flag to declare.

    Removing the previous ``hasattr`` guarded monkey-patching in
    :func:`get_validators` — the metadata now lives on the class itself.
    """

    name: ClassVar[str] = ""
    rule_id: ClassVar[str] = ""
    profile: ClassVar[ProfileTier] = ProfileTier.STANDARD
    experimental: ClassVar[bool] = False

    def should_run(self, inp: HookInput) -> bool:
        """Fast skip predicate — overridden by concrete validators."""
        raise NotImplementedError  # pragma: no cover

    def validate(self, inp: HookInput) -> HookResult | HookAllow | HookAsk | None:
        """Block/allow/abstain decision — overridden by concrete validators."""
        raise NotImplementedError  # pragma: no cover
