"""GH-116: enumerate local user skills and propose per-project pre-approval.

Local skills in ``~/.claude/skills/<name>/SKILL.md`` (including namespaced
``<ns>:<name>`` directories) need an explicit ``Skill(<name>)`` allow rule
in each project's ``settings.json`` to avoid a first-use permission
prompt. Today the doctor never surfaces this gap — this module gives it
the building blocks.

Discovery is split from approval:

- :func:`enumerate_local_skills` walks ``~/.claude/skills/`` and returns
  the parsed names.
- :func:`enumerate_projects` finds Claude project directories.
- :func:`group_by_namespace` clusters skills sharing a prefix so the
  caller can offer a wildcard rule once a project pre-approves 3+ from
  the same namespace.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from dev10x.domain.claude_paths import ClaudeDir
from dev10x.domain.common.skill_name import SkillName

SKILL_NAME_RE = re.compile(
    r"^\s*name:\s*['\"]?(?P<name>[A-Za-z0-9:_\-]+)['\"]?\s*$",
    re.MULTILINE,
)

NAMESPACE_WILDCARD_THRESHOLD = 3


@dataclass
class LocalSkill:
    name: str
    directory: Path
    namespace: str | None = None  # e.g. "tt" in "tt:db"

    @property
    def short_name(self) -> str:
        parsed = SkillName.try_parse(self.name)
        return parsed.short_name if parsed else self.name


@dataclass
class NamespaceGroup:
    namespace: str
    skills: list[LocalSkill] = field(default_factory=list)

    @property
    def wildcard_rule(self) -> str:
        return f"Skill({self.namespace}:*)"

    @property
    def threshold_met(self) -> bool:
        return len(self.skills) >= NAMESPACE_WILDCARD_THRESHOLD


def enumerate_local_skills(*, skills_root: Path | None = None) -> list[LocalSkill]:
    """Walk ``skills_root`` (default ``~/.claude/skills``) and parse each
    SKILL.md's ``name:`` field.

    Returns one :class:`LocalSkill` per discovered skill, with the
    namespace prefix split out for grouping. Returns ``[]`` when
    the root does not exist.
    """
    root = skills_root or ClaudeDir.skills_dir()
    if not root.exists():
        return []

    skills: list[LocalSkill] = []
    for skill_md in sorted(root.glob("*/SKILL.md")):
        try:
            content = skill_md.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        match = SKILL_NAME_RE.search(content)
        if not match:
            continue
        name = match.group("name")
        parsed = SkillName.try_parse(name)
        namespace = parsed.namespace if parsed else None
        skills.append(
            LocalSkill(name=name, directory=skill_md.parent, namespace=namespace),
        )
    return skills


def enumerate_projects(*, projects_root: Path | None = None) -> list[Path]:
    """List Claude project directories under ``projects_root``.

    Default root is ``~/.claude/projects``. Each immediate child
    directory represents one project.
    """
    root = projects_root or ClaudeDir.projects_dir()
    if not root.exists():
        return []
    return sorted(p for p in root.iterdir() if p.is_dir())


def group_by_namespace(*, skills: list[LocalSkill]) -> list[NamespaceGroup]:
    """Cluster ``skills`` by namespace prefix. Skills without a
    namespace are dropped from the grouping output (they cannot
    benefit from a wildcard rule).
    """
    groups: dict[str, list[LocalSkill]] = {}
    for skill in skills:
        if skill.namespace is None:
            continue
        groups.setdefault(skill.namespace, []).append(skill)

    return [
        NamespaceGroup(namespace=ns, skills=sorted(s, key=lambda x: x.name))
        for ns, s in sorted(groups.items())
    ]


def missing_skill_rules(
    *,
    skills: list[LocalSkill],
    existing_allow: list[str],
) -> list[str]:
    """Return ``Skill(<name>)`` rules not yet present in ``existing_allow``.

    Honors wildcard coverage: ``Skill(<ns>:*)`` covers all
    ``Skill(<ns>:<name>)`` skills in the namespace.
    """
    existing = set(existing_allow)
    wildcards = {
        rule[len("Skill(") : -1].rstrip("*").rstrip(":")
        for rule in existing
        if rule.startswith("Skill(") and rule.endswith(":*)")
    }

    proposals: list[str] = []
    for skill in skills:
        explicit = f"Skill({skill.name})"
        if explicit in existing:
            continue
        if skill.namespace and skill.namespace in wildcards:
            continue
        proposals.append(explicit)
    return proposals
