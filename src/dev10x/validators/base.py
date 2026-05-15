"""Validator protocol for Bash command validation.

Two hook integration points:

  PreToolUse  → should_run() + validate()  — block before execution
  PermissionDenied → should_run() + correct() — guide after auto-mode denial

The correct() method is optional. Validators that implement it can
provide retry-with-guidance responses for the PermissionDenied hook.

Validators also declare profile-tier metadata (GH-413):

  rule_id       — stable identifier (e.g., "DX001"), used for
                  DEV10X_HOOK_DISABLE filtering
  profile       — "minimal" | "standard" | "strict" — which active
                  profile this validator participates in. Validators
                  at or below the active profile run; higher-profile
                  validators are skipped.
  experimental  — True to opt out unless DEV10X_HOOK_EXPERIMENTAL=1

All three fields are optional — missing attributes default to
profile="standard", experimental=False, rule_id="" (never disabled
by ID).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from dev10x.domain import HookAllow, HookInput, HookResult, HookRetry


@runtime_checkable
class Validator(Protocol):
    name: str

    def should_run(self, inp: HookInput) -> bool:
        """Fast predicate — return False to skip this validator entirely."""
        ...

    def validate(self, inp: HookInput) -> HookResult | HookAllow | None:
        """Return HookResult to block, HookAllow to auto-approve, None for no opinion."""
        ...


@runtime_checkable
class Corrector(Protocol):
    """Optional extension for validators that support PermissionDenied corrections."""

    def correct(self, inp: HookInput) -> HookRetry | None:
        """Return HookRetry to suggest retry with corrective guidance, None otherwise."""
        ...
