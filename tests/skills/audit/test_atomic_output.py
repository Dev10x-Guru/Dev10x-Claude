"""GH-562: the standalone audit uv-scripts write reports atomically.

extract_session.py and analyze_actions.py cannot import
dev10x.domain.file_locks (PEP 723 standalone scripts), so each inlines
an `_atomic_write_text` helper that mirrors atomic_write_text. These
tests exercise that helper directly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dev10x.skills.audit.analyze_actions import _atomic_write_text as actions_write
from dev10x.skills.audit.extract_session import _atomic_write_text as session_write

WRITERS = [actions_write, session_write]


@pytest.mark.parametrize("writer", WRITERS)
def test_writes_content(writer, tmp_path: Path) -> None:
    target = tmp_path / "report.md"
    writer(str(target), "# Report\n")
    assert target.read_text() == "# Report\n"


@pytest.mark.parametrize("writer", WRITERS)
def test_creates_parent_directory(writer, tmp_path: Path) -> None:
    target = tmp_path / "nested" / "deep" / "report.md"
    writer(str(target), "content")
    assert target.read_text() == "content"


@pytest.mark.parametrize("writer", WRITERS)
def test_leaves_no_stale_tmp(writer, tmp_path: Path) -> None:
    target = tmp_path / "report.md"
    writer(str(target), "content")
    leftovers = [p.name for p in tmp_path.iterdir() if p.suffix == ".tmp"]
    assert leftovers == []


@pytest.mark.parametrize("writer", WRITERS)
def test_overwrites_existing(writer, tmp_path: Path) -> None:
    target = tmp_path / "report.md"
    target.write_text("old")
    writer(str(target), "new")
    assert target.read_text() == "new"
