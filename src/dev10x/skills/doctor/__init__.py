"""Dev10x:doctor — intent-drift diagnostic skill (GH-87).

The skill core is a strategy registry. Each strategy owns one
drift category (MCP-vs-script confusion, cluster coverage, local
skill pre-approval, monorepo uv friction). Strategies share a
common interface defined in :mod:`dev10x.skills.doctor.strategy`
and are discovered via :func:`load_strategies`.

The skill orchestration lives in ``skills/doctor/SKILL.md``;
this package supplies the building blocks the orchestration
delegates to.
"""

from __future__ import annotations

from dev10x.skills.doctor.strategy import (
    Context,
    Finding,
    Remediation,
    Severity,
    Strategy,
)

__all__ = [
    "Context",
    "Finding",
    "Remediation",
    "Severity",
    "Strategy",
]
