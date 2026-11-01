from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yaml

DEFAULT_KB_ROOT = Path("/home/janusz/GDrive/janusz.skonieczny/KB")
LESSONS_DIR = "wiki/lessons"
SLUG_LIMIT = 60
FRONTMATTER = "---\n"


@dataclass(frozen=True)
class Lesson:
    title: str
    body: str
    repo: str
    topic: str
    date: str
    path: str
    source_session: str = ""
    tags: list[str] = field(default_factory=list)


def slugify(title: str) -> str:
    raw = "".join(ch if ch.isascii() and ch.isalnum() else "-" for ch in title.lower())
    return "-".join(part for part in raw.split("-") if part)[:SLUG_LIMIT].strip("-") or "lesson"


def _link_new(*, directory: Path, stem: str, content: str) -> Path:
    fd, draft = tempfile.mkstemp(dir=str(directory), prefix=".", suffix=".tmp")
    try:
        os.write(fd, content.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    try:
        suffix = 1
        while True:
            name = f"{stem}.md" if suffix == 1 else f"{stem}-{suffix}.md"
            target = directory / name
            try:
                os.link(draft, target)
            except FileExistsError:
                suffix += 1
                continue
            return target
    finally:
        os.unlink(draft)


def write_lesson(
    *,
    kb_root: Path,
    title: str,
    body: str,
    repo: str,
    topic: str,
    tags: list[str],
    source_session: str,
    today: date,
) -> Path:
    directory = kb_root / LESSONS_DIR
    directory.mkdir(parents=True, exist_ok=True)
    frontmatter = {
        "repo": repo,
        "topic": topic,
        "tags": list(tags),
        "source_session": source_session,
        "date": today.isoformat(),
    }
    content = (
        FRONTMATTER
        + yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True)
        + FRONTMATTER
        + f"\n# {title}\n\n{body.rstrip()}\n"
    )
    return _link_new(
        directory=directory,
        stem=f"{today.isoformat()}-{slugify(title=title)}",
        content=content,
    )


def _read_lesson(*, path: Path) -> Lesson | None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    if not text.startswith(FRONTMATTER):
        return None
    head, separator, rest = text[len(FRONTMATTER) :].partition("\n" + FRONTMATTER)
    if not separator:
        return None
    try:
        meta: Any = yaml.safe_load(head)
    except yaml.YAMLError:
        return None
    if not isinstance(meta, dict):
        return None
    lines = rest.strip().splitlines()
    heading = lines[0] if lines else ""
    title = heading[2:].strip() if heading.startswith("# ") else path.stem
    body = "\n".join(lines[1:] if heading.startswith("# ") else lines).strip()
    return Lesson(
        title=title,
        body=body,
        repo=str(meta.get("repo", "")),
        topic=str(meta.get("topic", "")),
        tags=[str(tag) for tag in meta.get("tags") or []],
        source_session=str(meta.get("source_session", "")),
        date=str(meta.get("date", "")),
        path=str(path),
    )


def _matches(*, lesson: Lesson, repo: str, query: str) -> bool:
    if repo and lesson.repo != repo:
        return False
    if not query:
        return True
    haystack = " ".join([lesson.title, lesson.topic, *lesson.tags, lesson.body]).lower()
    return query.lower() in haystack


def find_lessons(
    *,
    kb_root: Path,
    repo: str = "",
    query: str = "",
    limit: int = 20,
) -> list[Lesson]:
    directory = kb_root / LESSONS_DIR
    if not directory.is_dir():
        return []
    lessons = [_read_lesson(path=path) for path in sorted(directory.glob("*.md"))]
    found = [
        lesson
        for lesson in lessons
        if lesson is not None and _matches(lesson=lesson, repo=repo, query=query)
    ]
    return sorted(found, key=lambda lesson: lesson.date, reverse=True)[:limit]
