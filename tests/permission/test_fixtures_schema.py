from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "permission-friction"

EFFECTS = {"allow", "ask", "deny"}
CLASSES = {"safe-read", "safe-write", "destructive", "fence-tool", "arbitrary-code"}
REVERSIBILITY = {"trivial", "assisted", "none", None}
FRICTION = {
    "permission-prompt",
    "hook-block",
    "PREFIX_POISONED_CHAIN",
    "MISSING_RULE",
    "option-2-footgun",
    "agent-bouncing-loop",
    None,
}

# Per GH-271 reflections: safe-read is always allow; destructive and
# arbitrary-code may NEVER be allow (the whole point of the taxonomy).
ALLOWED_EFFECTS_BY_CLASS = {
    "safe-read": {"allow"},
    "safe-write": {"allow", "ask"},
    "destructive": {"ask", "deny"},
    "fence-tool": {"allow", "ask", "deny"},
    "arbitrary-code": {"ask", "deny"},
}

ID_RE = re.compile(r"^#\d+$")


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _class_files() -> list[Path]:
    return sorted(p for p in FIXTURES_DIR.glob("*.yaml") if p.name != "unclassified.yaml")


def _class_rows() -> list[tuple[str, str, dict]]:
    rows: list[tuple[str, str, dict]] = []
    for path in _class_files():
        data = _load(path)
        for row in data["rows"]:
            rows.append((path.name, data["command_class"], row))
    return rows


CLASS_FILES = _class_files()
CLASS_ROWS = _class_rows()
CLASS_ROW_IDS = [f"{name}:{row['id']}" for name, _cls, row in CLASS_ROWS]
UNCLASSIFIED = _load(FIXTURES_DIR / "unclassified.yaml")
UNCLASSIFIED_ROWS = UNCLASSIFIED["rows"]
UNCLASSIFIED_IDS = [row["id"] for row in UNCLASSIFIED_ROWS]


def test_class_files_present() -> None:
    found = {p.stem for p in CLASS_FILES}
    assert found == CLASSES


@pytest.mark.parametrize("path", CLASS_FILES, ids=[p.name for p in CLASS_FILES])
def test_class_file_header_matches_filename(path: Path) -> None:
    data = _load(path)
    assert data["command_class"] == path.stem
    assert data["command_class"] in CLASSES
    assert isinstance(data["rows"], list)
    assert data["rows"]


@pytest.mark.parametrize(("name", "klass", "row"), CLASS_ROWS, ids=CLASS_ROW_IDS)
def test_row_schema(name: str, klass: str, row: dict) -> None:
    assert klass in CLASSES
    assert ID_RE.match(row["id"]), row["id"]
    assert row["command"], f"empty command in {name}:{row['id']}"
    assert row["effect"] in EFFECTS
    assert row["reversibility"] in REVERSIBILITY
    assert row["friction"] in FRICTION
    assert row["notes"], f"empty notes in {name}:{row['id']}"


@pytest.mark.parametrize(("name", "klass", "row"), CLASS_ROWS, ids=CLASS_ROW_IDS)
def test_effect_coherent_with_class(name: str, klass: str, row: dict) -> None:
    assert row["effect"] in ALLOWED_EFFECTS_BY_CLASS[klass]


@pytest.mark.parametrize("row", UNCLASSIFIED_ROWS, ids=UNCLASSIFIED_IDS)
def test_unclassified_carries_no_classification(row: dict) -> None:
    assert ID_RE.match(row["id"]), row["id"]
    assert row["command"]
    assert "effect" not in row
    assert "command_class" not in row


def test_ids_unique_across_all_files() -> None:
    ids = [row["id"] for _name, _cls, row in CLASS_ROWS] + UNCLASSIFIED_IDS
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    assert not duplicates, f"duplicate evidence ids: {duplicates}"
