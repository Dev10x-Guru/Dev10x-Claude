"""Permission Pattern Investigator (GH-47).

Materializes a controlled fixture, applies candidate rule shapes
to target settings files, and aggregates per-shape results into a
matrix that records whether the engine auto-approved or prompted.

This package owns the deterministic, non-Claude pieces. The
subagent dispatch loop that actually exercises each rule shape
lives in ``skills/permission-investigator/SKILL.md`` because the
Agent tool is only callable from Claude tool-use protocol.

## Public Facade

Top-level callers (e.g. ``commands/permission.py:investigate_delta``)
should import from this package, not from internal submodules. The
``PermissionDeltaQuery`` query object encapsulates state loading,
matrix reconstruction, and delta computation in one entry point.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dev10x.skills.permission_investigator.matrix import (
    Matrix,
    MatrixCell,
    MatrixResult,
    RuleShape,
)
from dev10x.skills.permission_investigator.report import Delta, compute_delta

__all__ = [
    "Delta",
    "Matrix",
    "PermissionDeltaQuery",
    "load_matrix_from_state",
]


def load_matrix_from_state(state: dict[str, Any]) -> Matrix:
    """Reconstruct a Matrix from the persisted investigator state dict."""
    matrix = Matrix()
    for cell_data in state.get("cells", []):
        matrix.cells.append(
            MatrixCell(
                shape=RuleShape(**cell_data["shape"]),
                location=cell_data["location"],
                cell_id=cell_data["cell_id"],
            )
        )
    for _, result_data in state.get("results", {}).items():
        matrix.add_result(MatrixResult(**result_data))
    return matrix


@dataclass(frozen=True)
class PermissionDeltaQuery:
    """Compute the delta between investigator results and shipped rules.

    Reads the persisted matrix state from ``state_path`` and compares
    against ``base_permissions``. Returns a :class:`Delta` with
    ineffective and suggested rules.
    """

    state_path: Path
    base_permissions: list[str]

    def state_exists(self) -> bool:
        return self.state_path.is_file()

    def execute(self) -> Delta:
        state = json.loads(self.state_path.read_text())
        matrix = load_matrix_from_state(state)
        return compute_delta(matrix=matrix, base_permissions=self.base_permissions)
