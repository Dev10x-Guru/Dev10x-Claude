"""PAP-0 permission-policy fixture corpus loader (GH-797).

Validates the golden corpus at ``tests/fixtures/permission-policy/``
against the ``Policy`` domain enums so the fixtures and the model
cannot drift silently. No production code consumes the corpus yet —
PAP-1 (GH-798) wires the precedence loader against it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from dev10x.domain.common.policy import PolicyEffect, PolicySensitivity, PolicySource

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "permission-policy"

REQUIRED_SURFACES = {"bash", "mcp", "skill-script", "skill-invocation"}
SUPPLEMENTARY_SURFACES = {"self-settings"}

EFFECTS = {member.value for member in PolicyEffect}
SENSITIVITIES = {member.value for member in PolicySensitivity}
SOURCE_TIERS = {member.value for member in PolicySource}


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _surface_files() -> list[Path]:
    return sorted(FIXTURES_DIR.glob("*.yaml"))


def _cases() -> list[tuple[str, str, dict]]:
    rows: list[tuple[str, str, dict]] = []
    for path in _surface_files():
        data = _load(path)
        for case in data["cases"]:
            rows.append((path.name, data["surface"], case))
    return rows


SURFACE_FILES = _surface_files()
CASES = _cases()
CASE_IDS = [f"{name}:{case['id']}" for name, _surface, case in CASES]


def test_required_surfaces_present() -> None:
    found = {p.stem for p in SURFACE_FILES}
    assert REQUIRED_SURFACES <= found
    assert found <= REQUIRED_SURFACES | SUPPLEMENTARY_SURFACES


@pytest.mark.parametrize("path", SURFACE_FILES, ids=[p.name for p in SURFACE_FILES])
def test_surface_header_matches_filename(path: Path) -> None:
    data = _load(path)
    assert data["surface"] == path.stem
    assert isinstance(data["cases"], list)
    assert data["cases"]


@pytest.mark.parametrize(("name", "surface", "case"), CASES, ids=CASE_IDS)
def test_case_schema(name: str, surface: str, case: dict) -> None:
    assert case["id"].strip(), f"empty id in {name}"
    assert "/" in case["id"], f"id lacks provenance prefix in {name}:{case['id']}"
    assert case["input"].strip(), f"empty input in {name}:{case['id']}"
    assert case["sensitivity"] in SENSITIVITIES
    assert case["effect"] in EFFECTS
    assert case["source_tier"] in SOURCE_TIERS
    assert case["notes"].strip(), f"empty notes in {name}:{case['id']}"


def test_corpus_spans_tri_state_effects() -> None:
    effects = {case["effect"] for _name, _surface, case in CASES}
    assert effects == EFFECTS


def test_every_required_surface_spans_multiple_effects() -> None:
    by_surface: dict[str, set[str]] = {}
    for _name, surface, case in CASES:
        by_surface.setdefault(surface, set()).add(case["effect"])
    for surface in REQUIRED_SURFACES:
        assert len(by_surface[surface]) >= 2, f"{surface} corpus is effect-monotone"


def test_ids_unique_across_corpus() -> None:
    ids = [case["id"] for _name, _surface, case in CASES]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    assert not duplicates, f"duplicate case ids: {duplicates}"
