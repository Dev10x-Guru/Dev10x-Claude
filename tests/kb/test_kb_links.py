"""Relative, percent-encoded vault links (GH-1985)."""

from __future__ import annotations

from pathlib import Path

from dev10x.kb.links import relative_link


def test_links_relative_to_the_source_note() -> None:
    link = relative_link(
        source=Path("/v/2026/2026-11/2026-11-17.md"),
        target=Path("/v/People/Jane (Host).md"),
    )

    assert link == "[Jane (Host)](../../People/Jane%20%28Host%29.md)"


def test_uses_given_text() -> None:
    link = relative_link(
        source=Path("/v/a.md"), target=Path("/v/Att/x #1?.txt"), text="Transcript"
    )

    assert link == "[Transcript](Att/x%20%231%3F.txt)"
