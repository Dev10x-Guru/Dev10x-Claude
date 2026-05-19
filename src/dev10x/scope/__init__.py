"""Scope-document autopopulator (GH-170).

Renders Norms and Safeguards sections inline into ticket-scope
documents by walking ``.claude/rules/INDEX.md`` and path-matching
discovered rule files against the scope's affected files.

Per ADR 0005: render at generation time, not at scope-save time —
re-render whenever the spec is fed into a generation prompt so
stale rule text never lies.
"""

from __future__ import annotations

from dev10x.scope.index_parser import RuleEntry, parse_index
from dev10x.scope.norms_renderer import render_norms
from dev10x.scope.safeguards_renderer import render_safeguards

__all__ = [
    "RuleEntry",
    "parse_index",
    "render_norms",
    "render_safeguards",
]
