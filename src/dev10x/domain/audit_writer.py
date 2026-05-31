"""AuditWriter — domain-owned contract for the hook audit log surface.

The hooks layer (``dev10x.hooks.audit_emit``) needs to mint span ids,
classify outcomes, and append audit records, but it must not import the
``audit/`` adapter's internals directly (audit memo Finding I6 — the
``hooks → audit`` inversion). This Protocol declares the surface in the
core; ``dev10x.audit.log_reader`` provides the concrete implementation,
and the hooks layer depends on the Protocol and receives the concrete
writer through a single injection seam.

See ADR-0008 (context boundary protocol) for the dependency-direction
rule this enforces.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from dev10x.domain.hook_telemetry import HookOutcome


@runtime_checkable
class AuditWriter(Protocol):
    """The audit-log surface consumed by the hooks layer."""

    def audit_enabled(self) -> bool:
        """Return True when audit logging is enabled for this process."""
        ...

    def append_record(self, *, record: dict[str, Any]) -> None:
        """Append a single audit record. Failures never propagate."""
        ...

    def new_span_id(self) -> str:
        """Mint a fresh span id correlating wrap and body phases."""
        ...

    def current_span_id(self) -> str:
        """Return the inherited span id, or a fresh one when unset."""
        ...

    def classify_outcome(self, *, exit_code: int) -> HookOutcome:
        """Map a process exit code to a :class:`HookOutcome`."""
        ...


__all__ = ["AuditWriter"]
