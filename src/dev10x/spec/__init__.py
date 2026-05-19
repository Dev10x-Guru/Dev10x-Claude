"""Spec drift detection for the SPDD pipeline (GH-172).

Shared module between Dev10x:spec-update (behaviour-first) and
Dev10x:spec-sync (refactor-first). One canonical drift detector,
two entry points — per ADR 0005 risk mitigation.
"""

from __future__ import annotations

from dev10x.spec.drift_detector import (
    DriftKind,
    DriftReport,
    DriftSignal,
    detect_drift,
)

__all__ = [
    "DriftKind",
    "DriftReport",
    "DriftSignal",
    "detect_drift",
]
