"""ValidatorRegistry, filters, and chain for Bash command validation.

Separates three concerns previously tangled in ``validators/__init__.py``:

  ValidatorSpec        — typed discovery record (replaces 5-tuple)
  ValidatorFilter      — composable predicate over specs
  ValidatorRegistry    — owns specs, applies filters, lazy-imports
                         validator instances, supports lookup by rule_id
  ValidatorChain       — iterates active validators for a HookInput,
                         catches per-validator failures, short-circuits
                         ``correct()`` at first non-None HookRetry

Specs carry ``rule_id``/``profile``/``experimental`` so filtering can
happen before any validator module is imported. Each validator class
declares the same metadata via :class:`ValidatorBase` class attributes;
the registry verifies the two agree at registration time.
"""

from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from dev10x.domain.common.rule_id import RuleId
from dev10x.domain.profile_tier import ProfileTier

if TYPE_CHECKING:
    from dev10x.domain import HookAllow, HookInput, HookResult, HookRetry
    from dev10x.validators.base import Validator

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ValidatorSpec:
    """Typed discovery record for a validator class.

    Carries enough metadata for the registry to filter validators by
    profile/disable-list/experimental flags before importing the
    backing module — preserving the lazy-import behavior of the old
    tuple-based registry.
    """

    module_path: str
    class_name: str
    rule_id: str
    profile: ProfileTier
    experimental: bool = False

    def __post_init__(self) -> None:
        # Validate format and normalise case once, at registry-build time,
        # so a malformed rule_id fails fast instead of silently mismatching.
        object.__setattr__(self, "rule_id", str(RuleId.parse(self.rule_id)))


class ValidatorFilter(Protocol):
    """Composable predicate applied to specs at registry-build time."""

    def keep(self, spec: ValidatorSpec) -> bool:
        """Return True to retain ``spec`` in the active set."""
        ...


@dataclass(frozen=True)
class ProfileFilter:
    """Keep specs at or below the active profile tier."""

    active: ProfileTier

    def keep(self, spec: ValidatorSpec) -> bool:
        return self.active.includes(validator_tier=spec.profile)


@dataclass(frozen=True)
class DisableListFilter:
    """Drop specs whose rule_id appears in the disabled set (case-insensitive)."""

    disabled: frozenset[str]

    def keep(self, spec: ValidatorSpec) -> bool:
        # spec.rule_id is already canonical (uppercased in __post_init__);
        # the disabled set is uppercased by the caller.
        return spec.rule_id not in self.disabled


@dataclass(frozen=True)
class ExperimentalFilter:
    """Drop experimental specs unless experimental mode is enabled."""

    enabled: bool

    def keep(self, spec: ValidatorSpec) -> bool:
        return self.enabled or not spec.experimental


class ValidatorRegistry:
    """Owns validator specs, applies filters, lazy-loads instances.

    Construction is cheap: only specs are stored. The first call to
    :meth:`active` imports the surviving modules and instantiates
    validators. Subsequent calls return the cached list.

    The spec list is private (``_specs``): callers seed it through the
    ``specs=`` constructor argument and mutate it only via
    :meth:`register`. Read access goes through :meth:`active_specs` /
    :meth:`find_by_rule_id` — nothing reaches into the backing list.
    """

    def __init__(
        self,
        *,
        specs: list[ValidatorSpec] | None = None,
        filters: list[ValidatorFilter] | None = None,
    ) -> None:
        self._specs: list[ValidatorSpec] = list(specs) if specs is not None else []
        self.filters: list[ValidatorFilter] = list(filters) if filters is not None else []
        self._instances: list[Validator] | None = None

    def register(self, spec: ValidatorSpec) -> None:
        """Append a spec; invalidates any cached instances."""
        self._specs.append(spec)
        self._instances = None

    def active_specs(self) -> list[ValidatorSpec]:
        """Return specs surviving all filters (no validators imported)."""
        return [spec for spec in self._specs if all(f.keep(spec) for f in self.filters)]

    def active(self) -> list[Validator]:
        """Return validator instances for all active specs (lazy import)."""
        if self._instances is None:
            self._instances = [self._instantiate(spec=spec) for spec in self.active_specs()]
        return self._instances

    def find_by_rule_id(self, rule_id: str) -> ValidatorSpec | None:
        """Return the spec for ``rule_id`` (regardless of filter state)."""
        target = RuleId.try_parse(rule_id)
        if target is None:
            return None
        for spec in self._specs:
            if spec.rule_id == str(target):
                return spec
        return None

    def lookup(self, rule_id: str) -> Validator | None:
        """Return the active validator instance for ``rule_id`` or None."""
        target = RuleId.try_parse(rule_id)
        if target is None:
            return None
        for validator in self.active():
            declared = RuleId.try_parse(getattr(validator, "rule_id", ""))
            if declared == target:
                return validator
        return None

    def is_active(self, rule_id: str) -> bool:
        """Return True if a validator with ``rule_id`` would run now."""
        target = RuleId.try_parse(rule_id)
        if target is None:
            return False
        return any(spec.rule_id == str(target) for spec in self.active_specs())

    def reset(self) -> None:
        """Drop cached instances; next :meth:`active` re-imports."""
        self._instances = None

    @staticmethod
    def _instantiate(spec: ValidatorSpec) -> Validator:
        from dev10x.validators.base import Validator as V

        module = importlib.import_module(spec.module_path)
        cls = getattr(module, spec.class_name)
        instance = cls()
        assert isinstance(instance, V), f"{spec.class_name} does not implement Validator"
        _assert_metadata_matches(instance=instance, spec=spec)
        return instance


def _assert_metadata_matches(*, instance: Validator, spec: ValidatorSpec) -> None:
    """Verify class-declared metadata matches the spec — fail fast on drift."""
    declared_rule_id = getattr(instance, "rule_id", "")
    declared_profile = getattr(instance, "profile", None)
    declared_experimental = getattr(instance, "experimental", None)
    declared_parsed = RuleId.try_parse(declared_rule_id)
    assert declared_parsed is not None and str(declared_parsed) == spec.rule_id, (
        f"{spec.class_name}.rule_id={declared_rule_id!r} disagrees with "
        f"spec rule_id={spec.rule_id!r}"
    )
    assert declared_profile == spec.profile, (
        f"{spec.class_name}.profile={declared_profile!r} disagrees with "
        f"spec profile={spec.profile!r}"
    )
    assert declared_experimental == spec.experimental, (
        f"{spec.class_name}.experimental={declared_experimental!r} disagrees with "
        f"spec experimental={spec.experimental!r}"
    )


@dataclass
class ValidatorChain:
    """Iterates active validators for a single :class:`HookInput`.

    Two entry points:

      :meth:`run` — for PreToolUse: emits every non-None ``validate()``
        result; iteration continues so multiple validators may speak.

      :meth:`correct` — for PermissionDenied: short-circuits at the
        first validator returning a :class:`HookRetry`.

    A validator raising during ``should_run``/``validate``/``correct``
    is always logged (GH-494 — previously silent unless ``HOOK_DEBUG``).
    For non-safety tiers the exception is then swallowed so one
    misbehaving validator cannot block the hook. A **safety-critical**
    (``ProfileTier.MINIMAL``) validator instead fails CLOSED: ``run``
    emits a blocking :class:`HookResult` rather than letting the command
    through unchecked.
    """

    registry: ValidatorRegistry

    def run(self, inp: HookInput) -> list[HookResult | HookAllow]:
        """Invoke ``validate()`` on every applicable validator.

        Returns the list of non-None results in registration order;
        callers emit each in turn. When a safety-critical validator
        raises, a fail-closed block is appended in its place (GH-494).
        """
        results: list[HookResult | HookAllow] = []
        for validator in self.registry.active():
            try:
                result = validator.run(inp=inp)
            except Exception:
                _log_validator_error(validator=validator, method="validate")
                blocked = _safety_fail_closed(validator=validator)
                if blocked is not None:
                    results.append(blocked)
                continue
            if result is not None:
                results.append(result)
        return results

    def correct(self, inp: HookInput) -> HookRetry | None:
        """Invoke ``correct()`` on capable validators; first hit wins."""
        from dev10x.validators.base import Corrector

        for validator in self.registry.active():
            if not isinstance(validator, Corrector):
                continue
            try:
                if not validator.should_run(inp=inp):
                    continue
                result = validator.correct(inp=inp)  # type: ignore[attr-defined]
            except Exception:
                _log_validator_error(validator=validator, method="correct")
                continue
            if result is not None:
                return result
        return None


def _log_validator_error(*, validator: Validator, method: str) -> None:
    """Always surface a validator failure (GH-494).

    Previously gated on ``HOOK_DEBUG``, which silenced exceptions in
    production and let the chain fail open with no diagnostic. Emitting
    at ERROR keeps the traceback visible on stderr even when no logging
    handler is configured (the stdlib last-resort handler covers it).
    """
    log.error(
        "validator %s %s() raised",
        getattr(validator, "name", "?"),
        method,
        exc_info=True,
    )


def _safety_fail_closed(*, validator: Validator) -> HookResult | None:
    """Return a blocking result when a safety-critical validator raised.

    Safety-critical validators (``ProfileTier.MINIMAL`` — DX001–DX005,
    DX012) guard against destructive or unsafe commands. If one raises
    we cannot know whether the command is safe, so we fail CLOSED and
    block rather than letting it through (GH-494). Non-safety tiers
    return None here and remain fail-open.
    """
    if getattr(validator, "profile", None) is not ProfileTier.MINIMAL:
        return None
    from dev10x.domain import HookResult

    rule_id = getattr(validator, "rule_id", "?")
    name = getattr(validator, "name", "?")
    return HookResult(
        message=(
            f"🛡️ Safety validator {name} ({rule_id}) raised an exception and "
            "could not evaluate this command. Blocking as a precaution "
            "(fail-closed). Re-run with HOOK_DEBUG=1 for the traceback, or set "
            f"DEV10X_HOOK_DISABLE={rule_id} if this validator is misbehaving."
        )
    )


__all__ = [
    "DisableListFilter",
    "ExperimentalFilter",
    "ProfileFilter",
    "ValidatorChain",
    "ValidatorFilter",
    "ValidatorRegistry",
    "ValidatorSpec",
]
