"""Detect drift between a canonical spec and the current code (GH-172).

Two flavors of drift, classified per ADR 0005:

* **Structural drift** — class/function names, file paths, signatures
  changed in the code but not in the spec's
  ``## Architecture`` / ``## Implementation Steps`` sections.
  ``Dev10x:spec-sync`` regenerates only structural sections to
  match.

* **Behavioural drift** — requirements / acceptance criteria /
  safeguards no longer match the code's contract. ``Dev10x:spec-sync``
  refuses to proceed and delegates to ``Dev10x:spec-update``.

The detector is intentionally heuristic — perfect classification
requires AST + semantic analysis, which is out of scope here. It
errs on the side of flagging anything ambiguous as
``DriftKind.BEHAVIOURAL`` so the caller bails to the more careful
``Dev10x:spec-update`` path.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class DriftKind(StrEnum):
    """Classification of one drift signal.

    ``STRUCTURAL`` may be auto-fixed by ``Dev10x:spec-sync``.
    ``BEHAVIOURAL`` requires ``Dev10x:spec-update`` (spec-first
    edit + regenerate). ``NONE`` is the only "no drift" signal
    callers should treat as "all good".
    """

    NONE = "none"
    STRUCTURAL = "structural"
    BEHAVIOURAL = "behavioural"


@dataclass(frozen=True)
class DriftSignal:
    kind: DriftKind
    section: str
    detail: str


@dataclass(frozen=True)
class DriftReport:
    signals: tuple[DriftSignal, ...] = field(default_factory=tuple)

    @property
    def has_drift(self) -> bool:
        return any(s.kind is not DriftKind.NONE for s in self.signals)

    @property
    def has_behavioural(self) -> bool:
        return any(s.kind is DriftKind.BEHAVIOURAL for s in self.signals)

    @property
    def has_structural(self) -> bool:
        return any(s.kind is DriftKind.STRUCTURAL for s in self.signals)


_FILE_REF_RE = re.compile(r"`([a-zA-Z0-9_/.\-]+\.[a-zA-Z0-9]+)`")
_CALLABLE_REF_RE = re.compile(r"`([A-Za-z_][A-Za-z0-9_]*)\s*\(")
_HEADING_RE = re.compile(r"^(#+)\s+(.+?)\s*$")


def detect_drift(
    *,
    spec_path: Path,
    project_root: Path,
) -> DriftReport:
    """Compare the spec at ``spec_path`` against current code.

    Returns a ``DriftReport`` listing every detected mismatch.
    A spec that does not exist yields a single
    ``DriftKind.BEHAVIOURAL`` signal so callers fail closed.
    """

    if not spec_path.exists():
        return DriftReport(
            signals=(
                DriftSignal(
                    kind=DriftKind.BEHAVIOURAL,
                    section="<spec>",
                    detail=f"spec file missing: {spec_path}",
                ),
            )
        )

    sections = _split_sections(spec_path.read_text())
    signals: list[DriftSignal] = []
    signals.extend(_structural_signals(sections=sections, project_root=project_root))
    signals.extend(_behavioural_signals(sections=sections, project_root=project_root))
    return DriftReport(signals=tuple(signals))


def _split_sections(text: str) -> dict[str, str]:
    """Return a {heading: body} map keyed by the heading text."""

    sections: dict[str, str] = {}
    current_heading = "<preamble>"
    current_lines: list[str] = []
    for line in text.splitlines():
        match = _HEADING_RE.match(line)
        if match:
            sections[current_heading] = "\n".join(current_lines)
            current_heading = match.group(2).strip()
            current_lines = []
        else:
            current_lines.append(line)
    sections[current_heading] = "\n".join(current_lines)
    return sections


def _structural_signals(
    *,
    sections: dict[str, str],
    project_root: Path,
) -> list[DriftSignal]:
    """Flag missing-file references in Implementation Steps / Architecture."""

    signals: list[DriftSignal] = []
    for heading in ("Architecture", "Implementation Steps", "Code References"):
        body = sections.get(heading, "")
        for path in _FILE_REF_RE.findall(body):
            candidate = project_root / path
            if not candidate.exists():
                signals.append(
                    DriftSignal(
                        kind=DriftKind.STRUCTURAL,
                        section=heading,
                        detail=f"spec references missing file `{path}`",
                    )
                )
    return signals


def _behavioural_signals(
    *,
    sections: dict[str, str],
    project_root: Path,
) -> list[DriftSignal]:
    """Flag missing acceptance criteria coverage and safeguard mismatches.

    Heuristic — we look for callable references in Acceptance Criteria
    or Safeguards sections and check whether ``project_root`` still
    contains a definition for them.
    """

    signals: list[DriftSignal] = []
    for heading in ("Acceptance Criteria", "Safeguards"):
        body = sections.get(heading, "")
        for name in set(_CALLABLE_REF_RE.findall(body)):
            if not _name_defined_in_project(name=name, project_root=project_root):
                signals.append(
                    DriftSignal(
                        kind=DriftKind.BEHAVIOURAL,
                        section=heading,
                        detail=f"spec mentions `{name}(...)` but no definition found",
                    )
                )
    return signals


def _name_defined_in_project(*, name: str, project_root: Path) -> bool:
    """True if a `def <name>` or `class <name>` exists anywhere in src/."""

    if not project_root.exists():
        return False
    pattern = re.compile(rf"^(?:def|class)\s+{re.escape(name)}\b", flags=re.MULTILINE)
    for python_file in project_root.rglob("*.py"):
        try:
            if pattern.search(python_file.read_text()):
                return True
        except OSError:
            continue
    return False
