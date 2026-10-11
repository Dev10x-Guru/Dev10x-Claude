"""Bundled-execution batch detection for work-on (GH-248 G3 / GH-196).

Encodes the overlap-signal rule the work-on skill describes in prose:
two tickets share a commit batch when at least ``BATCH_THRESHOLD``
overlap signals hold simultaneously, and no batch grows beyond
``MAX_BATCH_SIZE``. Extracting it here makes the bundling decision
importable and unit-testable instead of re-derived per session.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from enum import StrEnum

BATCH_THRESHOLD = 2
MAX_BATCH_SIZE = 5


class OverlapSignal(StrEnum):
    SHARED_COMPONENT = "shared_component"
    SHARED_ERROR_CLASS = "shared_error_class"
    SAME_PARENT = "same_parent"
    REPEATED_LABEL = "repeated_label"
    EXPLICIT_REFERENCE = "explicit_reference"


PairSignals = Mapping[tuple[str, str], Iterable[OverlapSignal]]


def tickets_share_batch(shared_signals: Iterable[OverlapSignal]) -> bool:
    return len(set(shared_signals)) >= BATCH_THRESHOLD


def _signals_for(pair_signals: PairSignals, left: str, right: str) -> set[OverlapSignal]:
    for key in ((left, right), (right, left)):
        if key in pair_signals:
            return set(pair_signals[key])
    return set()


def group_into_batches(
    tickets: Sequence[str],
    pair_signals: PairSignals,
) -> list[list[str]]:
    batches: list[list[str]] = []

    for ticket in tickets:
        placed = False
        for batch in batches:
            if len(batch) >= MAX_BATCH_SIZE:
                continue
            if any(
                tickets_share_batch(_signals_for(pair_signals, ticket, member)) for member in batch
            ):
                batch.append(ticket)
                placed = True
                break
        if not placed:
            batches.append([ticket])

    return batches
