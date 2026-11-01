"""Tests for KB lesson notes (GH-1692)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import yaml

from dev10x.comm.overwatch.lessons import (
    LESSONS_DIR,
    Lesson,
    find_lessons,
    slugify,
    write_lesson,
)

TODAY = date(2026, 10, 31)


def _write(
    *,
    kb_root: Path,
    title: str = "Hooks load once per session",
    body: str = "Restart the session after a plugin upgrade.",
    repo: str = "dev10x-claude",
    topic: str = "hooks",
    tags: list[str] | None = None,
    today: date = TODAY,
) -> Path:
    return write_lesson(
        kb_root=kb_root,
        title=title,
        body=body,
        repo=repo,
        topic=topic,
        tags=tags if tags is not None else ["claude-code"],
        source_session="47a1ef74",
        today=today,
    )


class TestWriteLesson:
    def test_creates_note_with_frontmatter(self, tmp_path: Path) -> None:
        path = _write(kb_root=tmp_path)
        head = path.read_text(encoding="utf-8").split("---\n")[1]

        assert (path.relative_to(tmp_path).as_posix(), yaml.safe_load(head)) == (
            f"{LESSONS_DIR}/2026-10-31-hooks-load-once-per-session.md",
            {
                "repo": "dev10x-claude",
                "topic": "hooks",
                "tags": ["claude-code"],
                "source_session": "47a1ef74",
                "date": "2026-10-31",
            },
        )

    def test_never_overwrites(self, tmp_path: Path) -> None:
        first = _write(kb_root=tmp_path, body="First.")
        second = _write(kb_root=tmp_path, body="Second.")

        assert (second.name, "First." in first.read_text(encoding="utf-8")) == (
            "2026-10-31-hooks-load-once-per-session-2.md",
            True,
        )

    def test_leaves_no_draft_behind(self, tmp_path: Path) -> None:
        _write(kb_root=tmp_path)

        assert [path.name for path in (tmp_path / LESSONS_DIR).iterdir()] == [
            "2026-10-31-hooks-load-once-per-session.md"
        ]

    @pytest.mark.parametrize(
        ("title", "slug"),
        [("Use rg, not grep!", "use-rg-not-grep"), ("???", "lesson"), ("Zażółć", "za")],
    )
    def test_slugify(self, title: str, slug: str) -> None:
        assert slugify(title=title) == slug


class TestFindLessons:
    @pytest.fixture
    def kb_root(self, tmp_path: Path) -> Path:
        _write(kb_root=tmp_path)
        _write(
            kb_root=tmp_path,
            title="Bus watcher re-arm",
            body="Mark read before re-launching.",
            topic="bus",
            today=date(2026, 10, 30),
        )
        _write(kb_root=tmp_path, title="Hook timing", repo="tt-pos", topic="hooks")
        return tmp_path

    def test_by_repo_and_query(self, kb_root: Path) -> None:
        found = find_lessons(kb_root=kb_root, repo="dev10x-claude", query="HOOK")

        assert [lesson.title for lesson in found] == ["Hooks load once per session"]

    def test_newest_first(self, kb_root: Path) -> None:
        found = find_lessons(kb_root=kb_root, repo="dev10x-claude")

        assert [lesson.date for lesson in found] == ["2026-10-31", "2026-10-30"]

    def test_limit(self, kb_root: Path) -> None:
        assert len(find_lessons(kb_root=kb_root, limit=1)) == 1

    def test_reads_back_fields(self, kb_root: Path) -> None:
        [lesson] = find_lessons(kb_root=kb_root, query="re-launching")

        assert lesson == Lesson(
            title="Bus watcher re-arm",
            body="Mark read before re-launching.",
            repo="dev10x-claude",
            topic="bus",
            tags=["claude-code"],
            source_session="47a1ef74",
            date="2026-10-30",
            path=lesson.path,
        )

    @pytest.mark.parametrize(
        "content",
        [
            "plain note without frontmatter\n",
            "---\nunterminated: true\n",
            "---\n- a list\n---\n\n# x\n",
            "---\n: : bad yaml [\n---\n\n# x\n",
        ],
        ids=["no-frontmatter", "unterminated", "not-a-mapping", "bad-yaml"],
    )
    def test_skips_unreadable_notes(self, kb_root: Path, content: str) -> None:
        (kb_root / LESSONS_DIR / "stray.md").write_text(content, encoding="utf-8")

        assert len(find_lessons(kb_root=kb_root)) == 3

    def test_skips_undecodable_note(self, kb_root: Path) -> None:
        (kb_root / LESSONS_DIR / "binary.md").write_bytes(b"\xff\xfe\x00")

        assert len(find_lessons(kb_root=kb_root)) == 3

    def test_note_without_heading_uses_file_name(self, kb_root: Path) -> None:
        (kb_root / LESSONS_DIR / "bare.md").write_text(
            "---\nrepo: x\ndate: '2026-01-01'\n---\n\nJust text.\n", encoding="utf-8"
        )

        [lesson] = find_lessons(kb_root=kb_root, repo="x")

        assert (lesson.title, lesson.body) == ("bare", "Just text.")

    def test_missing_dir_returns_empty(self, tmp_path: Path) -> None:
        assert find_lessons(kb_root=tmp_path) == []
