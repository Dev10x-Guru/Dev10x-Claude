"""Skill-index builder logic (GH-248 G11).

Ports the ``parse_skill`` front-matter parsing from
``skills/skill-index/scripts/generate-skills-menu.sh`` into importable,
unit-testable Python. The shell script extracts ``name`` and
``invocation-name`` from each ``SKILL.md`` front matter, computes the
menu key (invocation-name preferred, name as fallback), and rejects
scaffolding placeholders. This module makes that decision testable
without invoking ``yq``/``jq``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import yaml

_FRONT_MATTER_FENCE = "---"
_PLACEHOLDER_NAME = "my-skill-name"


@dataclass(frozen=True)
class SkillEntry:
    key: str
    name: str
    source: Path | None = None


def extract_front_matter(text: str) -> dict | None:
    lines = text.splitlines()
    if not lines or lines[0].strip() != _FRONT_MATTER_FENCE:
        return None

    body: list[str] = []
    for line in lines[1:]:
        if line.strip() == _FRONT_MATTER_FENCE:
            try:
                parsed = yaml.safe_load("\n".join(body))
            except yaml.YAMLError:
                return None
            return parsed if isinstance(parsed, dict) else None
        body.append(line)

    # No closing fence — malformed front matter.
    return None


def _compute_key(*, name: str, invocation_name: str) -> str:
    raw_key = invocation_name or name
    return raw_key.split("#", 1)[0].strip()


def parse_skill_frontmatter(text: str, source: Path | None = None) -> SkillEntry | None:
    front_matter = extract_front_matter(text=text)
    if front_matter is None:
        return None

    name = str(front_matter.get("name") or "").strip()
    if not name or "{" in name or name == _PLACEHOLDER_NAME:
        return None

    invocation_name = str(front_matter.get("invocation-name") or "").strip()
    key = _compute_key(name=name, invocation_name=invocation_name)
    if not key:
        return None

    return SkillEntry(key=key, name=name, source=source)


def scan_skill_dirs(skill_dirs: Iterable[Path]) -> list[SkillEntry]:
    entries: list[SkillEntry] = []
    for skill_dir in skill_dirs:
        for skill_file in sorted(skill_dir.glob("*/SKILL.md")):
            entry = parse_skill_frontmatter(
                text=skill_file.read_text(encoding="utf-8"),
                source=skill_file,
            )
            if entry is not None:
                entries.append(entry)

    return sorted(entries, key=lambda entry: entry.key)
