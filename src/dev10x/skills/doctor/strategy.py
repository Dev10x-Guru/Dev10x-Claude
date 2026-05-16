"""Shared types for Dev10x:doctor strategies (GH-87).

Each strategy is a thin module exporting a :class:`Strategy`
constant. The doctor skill iterates registered strategies in
Phase 2, invoking ``detect`` to surface findings and
``remediate`` to materialize the proposed edit.

Strategies must treat the :class:`Context` as read-only — the
doctor's Phase 4 owns all writes. This separation lets the user
review every finding via ``AskUserQuestion`` before any state
changes.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

Severity = Literal["critical", "drift", "suggestion"]

RemediationKind = Literal[
    "edit_memory",
    "edit_settings",
    "file_issue",
    "delegate_skill",
]


@dataclass(frozen=True)
class Context:
    """Read-only view of the user's environment a strategy may inspect."""

    settings_paths: tuple[Path, ...] = ()
    memory_roots: tuple[Path, ...] = ()
    plugin_cache_root: Path | None = None
    audit_log_records: tuple[dict, ...] = ()


@dataclass
class Finding:
    """One drift instance detected by a strategy."""

    strategy_id: str
    severity: Severity
    location: str
    evidence: str
    proposed_fix: str
    metadata: dict = field(default_factory=dict)


@dataclass
class Remediation:
    """Concrete action that resolves a :class:`Finding`."""

    kind: RemediationKind
    target: str
    action: dict = field(default_factory=dict)


DetectFn = Callable[[Context], list[Finding]]
RemediateFn = Callable[[Finding], Remediation]


@dataclass
class Strategy:
    """A pluggable drift detector + remediator."""

    id: str
    description: str
    detect: DetectFn
    remediate: RemediateFn
