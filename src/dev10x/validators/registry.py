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
import os
import sys
import traceback
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from dev10x.domain.profile_tier import ProfileTier

if TYPE_CHECKING:
    from dev10x.domain import HookAllow, HookInput, HookResult, HookRetry
    from dev10x.validators.base import Validator

_DEBUG = os.environ.get("HOOK_DEBUG", "") != ""


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
        return spec.rule_id.upper() not in self.disabled


@dataclass(frozen=True)
class ExperimentalFilter:
    """Drop experimental specs unless experimental mode is enabled."""

    enabled: bool

    def keep(self, spec: ValidatorSpec) -> bool:
        return self.enabled or not spec.experimental


@dataclass
class ValidatorRegistry:
    """Owns validator specs, applies filters, lazy-loads instances.

    Construction is cheap: only specs are stored. The first call to
    :meth:`active` imports the surviving modules and instantiates
    validators. Subsequent calls return the cached list.
    """

    specs: list[ValidatorSpec] = field(default_factory=list)
    filters: list[ValidatorFilter] = field(default_factory=list)
    _instances: list[Validator] | None = field(default=None, init=False, repr=False)

    def register(self, spec: ValidatorSpec) -> None:
        """Append a spec; invalidates any cached instances."""
        self.specs.append(spec)
        self._instances = None

    def active_specs(self) -> list[ValidatorSpec]:
        """Return specs surviving all filters (no validators imported)."""
        return [spec for spec in self.specs if all(f.keep(spec) for f in self.filters)]

    def active(self) -> list[Validator]:
        """Return validator instances for all active specs (lazy import)."""
        if self._instances is None:
            self._instances = [self._instantiate(spec=spec) for spec in self.active_specs()]
        return self._instances

    def find_by_rule_id(self, rule_id: str) -> ValidatorSpec | None:
        """Return the spec for ``rule_id`` (regardless of filter state)."""
        rule_id_upper = rule_id.upper()
        for spec in self.specs:
            if spec.rule_id.upper() == rule_id_upper:
                return spec
        return None

    def lookup(self, rule_id: str) -> Validator | None:
        """Return the active validator instance for ``rule_id`` or None."""
        rule_id_upper = rule_id.upper()
        for validator in self.active():
            if getattr(validator, "rule_id", "").upper() == rule_id_upper:
                return validator
        return None

    def is_active(self, rule_id: str) -> bool:
        """Return True if a validator with ``rule_id`` would run now."""
        rule_id_upper = rule_id.upper()
        return any(spec.rule_id.upper() == rule_id_upper for spec in self.active_specs())

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
    declared_rule_id = getattr(instance, "rule_id", None)
    declared_profile = getattr(instance, "profile", None)
    declared_experimental = getattr(instance, "experimental", None)
    assert declared_rule_id == spec.rule_id, (
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

    Validators raising during ``should_run``/``validate``/``correct``
    are swallowed (logged when ``HOOK_DEBUG`` is set) so a single
    misbehaving validator cannot block the hook.
    """

    registry: ValidatorRegistry

    def run(self, inp: HookInput) -> list[HookResult | HookAllow]:
        """Invoke ``validate()`` on every applicable validator.

        Returns the list of non-None results in registration order;
        callers emit each in turn.
        """
        results: list[HookResult | HookAllow] = []
        for validator in self.registry.active():
            try:
                if not validator.should_run(inp=inp):
                    continue
                result = validator.validate(inp=inp)
            except Exception:
                _log_validator_error(validator=validator, method="validate")
                continue
            if result is not None:
                results.append(result)
        return results

    def correct(self, inp: HookInput) -> HookRetry | None:
        """Invoke ``correct()`` on capable validators; first hit wins."""
        for validator in self.registry.active():
            if "correct" not in getattr(validator, "capabilities", frozenset()):
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
    if not _DEBUG:
        return
    print(
        f"[HOOK_DEBUG] {validator.name} {method}() raised:",
        file=sys.stderr,
    )
    traceback.print_exc(file=sys.stderr)


__all__ = [
    "DisableListFilter",
    "ExperimentalFilter",
    "ProfileFilter",
    "ValidatorChain",
    "ValidatorFilter",
    "ValidatorRegistry",
    "ValidatorSpec",
]
