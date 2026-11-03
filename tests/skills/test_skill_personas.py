"""A skill persona reaches the agent and stays in step with its front matter (GH-1638).

Skill loads show the SKILL.md body without its front matter, so the
`persona:` field only takes effect through the `**Persona:**` line that
opens the body. These tests keep the two copies identical.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_FILES = sorted(
    [*REPO_ROOT.glob("skills/*/SKILL.md"), *REPO_ROOT.glob("plugins/*/skills/*/SKILL.md")]
)
PILOT_SKILLS = ["skills/review/SKILL.md", "skills/adr/SKILL.md", "skills/ticket-scope/SKILL.md"]
MAX_PERSONA_LENGTH = 300
PERSONA_LABEL = "**Persona:**"
FRONT_MATTER = re.compile(r"\A---\n(?P<yaml>.*?)\n---\n(?P<body>.*)\Z", re.DOTALL)
PERSONA_KEY = re.compile(r"^persona:", re.MULTILINE)
FENCE = re.compile(r"^(```|~~~)")


def _relative(*, path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _text(*, path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _declares_persona(*, path: Path) -> bool:
    match = FRONT_MATTER.match(_text(path=path))
    return bool(match and PERSONA_KEY.search(match["yaml"]))


def _split(*, path: Path) -> tuple[dict, str]:
    match = FRONT_MATTER.match(_text(path=path))
    assert match, f"{_relative(path=path)}: no front matter delimited by --- lines"
    return yaml.safe_load(match["yaml"]), match["body"]


def _lines_outside_fences(*, body: str) -> list[str]:
    outside = []
    in_fence = False
    for line in body.splitlines():
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence:
            outside.append(line)
    return outside


def _normalised(*, text: str) -> str:
    return " ".join(text.split())


def _first_paragraph_after_title(*, path: Path, body: str) -> str:
    lines = _lines_outside_fences(body=body)
    titles = [index for index, line in enumerate(lines) if line.startswith("# ")]
    assert titles, f"{_relative(path=path)}: no H1 outside code fences"
    after_title = "\n".join(lines[titles[0] + 1 :]).strip()
    return _normalised(text=after_title.split("\n\n", maxsplit=1)[0])


def _persona(*, path: Path, front_matter: dict) -> str:
    persona = front_matter.get("persona")
    assert isinstance(persona, str), f"{_relative(path=path)}: persona must be a string"
    assert persona.strip(), f"{_relative(path=path)}: persona must not be empty"
    return _normalised(text=persona)


PERSONA_SKILLS = [path for path in SKILL_FILES if _declares_persona(path=path)]
OTHER_SKILLS = [path for path in SKILL_FILES if not _declares_persona(path=path)]


def _ids(path: Path) -> str:
    return _relative(path=path)


class TestSkillPersonas:
    def test_pilot_skills_declare_a_persona(self) -> None:
        declared = {_relative(path=path) for path in PERSONA_SKILLS}

        assert set(PILOT_SKILLS) <= declared

    @pytest.mark.parametrize("path", PERSONA_SKILLS, ids=_ids)
    def test_body_opens_with_the_front_matter_persona(self, path: Path) -> None:
        front_matter, body = _split(path=path)

        expected = f"{PERSONA_LABEL} {_persona(path=path, front_matter=front_matter)}"
        assert _first_paragraph_after_title(path=path, body=body) == expected

    @pytest.mark.parametrize("path", PERSONA_SKILLS, ids=_ids)
    def test_persona_stays_short(self, path: Path) -> None:
        front_matter, _ = _split(path=path)

        assert len(_persona(path=path, front_matter=front_matter)) <= MAX_PERSONA_LENGTH

    @pytest.mark.parametrize("path", OTHER_SKILLS, ids=_ids)
    def test_persona_line_needs_a_front_matter_field(self, path: Path) -> None:
        lines = _lines_outside_fences(body=_text(path=path))

        assert not [line for line in lines if line.startswith(PERSONA_LABEL)]
