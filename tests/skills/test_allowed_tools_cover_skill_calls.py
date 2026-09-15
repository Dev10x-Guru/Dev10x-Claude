"""Every delegated skill a skill body invokes must be declared.

A `Skill(...)` call whose target is missing from the caller's
`allowed-tools:` front matter costs an approval prompt on **every**
invocation, in every project, forever — while looking fully wired up
everywhere a reader would think to check. It is the skill-to-skill
twin of the MCP gap GH-1153 documents, and it had no guard: the
closest tooling (`test_catalog_covers_mcp_tools.py`,
`bin/check-skill-cli-friction.py`) covers MCP tools and raw CLI
friction, not delegation.

`Dev10x:gchat-review-request` was the worked example — its Step 4 had
called `Skill(Dev10x:gchat)` undeclared since the skill shipped,
inside the same plugin whose notification friction GH-1308 exists to
reduce.

Scope note: a skill that delegates through an `instructions.md` is
checked there too, because `allowed-tools:` in SKILL.md must cover
tool calls in BOTH files (CLAUDE.md § External Tool Declarations).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).parents[2]
_SKILLS_DIR = _REPO_ROOT / "skills"

#: A delegation in a body: Skill("X"), Skill(skill="X"), or Skill(X).
_CALL_RE = re.compile(r"""Skill\(\s*(?:skill\s*=\s*)?["']?([A-Za-z0-9:_-]+)["']?""")

#: A declaration in front matter: `- Skill(X)`, or a bare `- Skill`,
#: which grants the tool outright and so covers every delegation.
_DECLARATION_RE = re.compile(r"""^\s*-\s*Skill(?:\(\s*["']?([A-Za-z0-9:_*-]+)["']?\s*\))?\s*$""")

#: Lines that show what NOT to do. A body teaching an anti-pattern is
#: not invoking it, and demanding a declaration for the wrong call
#: would be the guard arguing with the documentation.
_COUNTEREXAMPLE_RE = re.compile(
    r"(❌|NEVER|WRONG|Anti-pattern|PROHIBITED|instead of)", re.IGNORECASE
)


def _skill_documents() -> list[tuple[Path, list[Path]]]:
    """Each SKILL.md paired with every body its front matter governs."""
    documents = []
    for skill_md in sorted(_SKILLS_DIR.glob("*/SKILL.md")):
        bodies = [skill_md]
        instructions = skill_md.parent / "instructions.md"
        if instructions.exists():
            bodies.append(instructions)
        documents.append((skill_md, bodies))
    return documents


def _front_matter(*, text: str) -> str:
    if not text.startswith("---"):
        return ""
    end = text.find("\n---", 3)
    return text[:end] if end != -1 else ""


def _declared(*, skill_md: Path) -> set[str]:
    """Skill names the front matter grants; ``*`` for a blanket grant."""
    matter = _front_matter(text=skill_md.read_text(encoding="utf-8"))
    return {
        match.group(1) or "*"
        for line in matter.splitlines()
        if (match := _DECLARATION_RE.match(line))
    }


def _plugin_skill_names() -> set[str]:
    return {path.parent.name for path in _SKILLS_DIR.glob("*/SKILL.md")}


def _canonical(*, target: str, plugin_skills: set[str]) -> str:
    """Resolve a bare name the way a reader would.

    Prose and ASCII diagrams write ``Skill(qa-scope)`` where the
    invocation is really ``Dev10x:qa-scope``. Taking those literally
    would have this guard demand a declaration for a skill that does
    not exist — worse than no guard, because the fix it asks for is
    wrong. A bare name matching a directory under ``skills/`` is this
    plugin's; anything else (``test``, a user skill) is left alone.
    """
    if ":" in target:
        return target
    return f"Dev10x:{target}" if target in plugin_skills else target


def _invoked(*, bodies: list[Path], own_name: str) -> set[str]:
    plugin_skills = _plugin_skill_names()
    targets: set[str] = set()
    for body in bodies:
        text = body.read_text(encoding="utf-8")
        # Skip the front matter: its `- Skill(X)` entries are
        # declarations, not calls.
        start = len(_front_matter(text=text))
        for line in text[start:].splitlines():
            if _COUNTEREXAMPLE_RE.search(line):
                continue
            targets.update(
                _canonical(target=target, plugin_skills=plugin_skills)
                for target in _CALL_RE.findall(line)
            )
    return {target for target in targets if target != own_name}


def _undeclared(*, skill_md: Path, bodies: list[Path]) -> set[str]:
    declared = _declared(skill_md=skill_md)
    if any(name.endswith("*") for name in declared):
        # A wildcard grant covers whatever it covers; this guard is
        # about silence, not about narrowing an explicit choice.
        return set()
    own_name = f"Dev10x:{skill_md.parent.name}"
    plugin_skills = _plugin_skill_names()
    canonical_declarations = {
        _canonical(target=name, plugin_skills=plugin_skills) for name in declared
    }
    return _invoked(bodies=bodies, own_name=own_name) - canonical_declarations


@pytest.mark.parametrize(
    ("skill_md", "bodies"),
    _skill_documents(),
    ids=[skill_md.parent.name for skill_md, _ in _skill_documents()],
)
def test_every_delegated_skill_is_declared(skill_md: Path, bodies: list[Path]) -> None:
    missing = _undeclared(skill_md=skill_md, bodies=bodies)

    assert not missing, (
        f"{skill_md.parent.name} invokes {sorted(missing)} but does not declare "
        f"them under allowed-tools:. Each undeclared delegation costs an "
        f"approval prompt on every run of this skill. Add "
        f"'  - Skill(<name>)' to the front matter of {skill_md.relative_to(_REPO_ROOT)}."
    )


def test_the_guard_sees_the_delegation_surface() -> None:
    """A guard that matches nothing passes for the wrong reason.

    Narrowing the scan — a changed call spelling, a moved body file —
    would shrink this guard's field of view silently, which is the
    failure mode `test_discovery_sees_every_registration` was added to
    prevent for MCP tools (GH-1215).
    """
    total = sum(
        len(_invoked(bodies=bodies, own_name=f"Dev10x:{skill_md.parent.name}"))
        for skill_md, bodies in _skill_documents()
    )

    assert total > 50, (
        f"only {total} delegations found across skills/ — the scan has "
        f"probably stopped matching the call spelling in use"
    )
