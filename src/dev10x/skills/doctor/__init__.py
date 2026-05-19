"""Dev10x:plugin-doctor — intent-drift diagnostic skill (GH-87).

The skill core is a strategy registry. Each strategy owns one
drift category (MCP-vs-script confusion, cluster coverage, local
skill pre-approval, monorepo uv friction). Strategies share a
common interface defined in :mod:`dev10x.skills.doctor.strategy`
and are discovered via :func:`load_strategies`.

The skill orchestration lives in ``skills/plugin-doctor/SKILL.md``;
(the Python module path remains ``dev10x.skills.doctor`` —
the directory rename is markdown-side only; GH-217 defers the
Python module rename to a follow-up.)
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
