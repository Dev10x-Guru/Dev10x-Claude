"""Rewrite renamed skill names in user configs (ADR-0034 Stage A4, GH-1559).

When a Stage B step moves a skill from ``dev10x:<skill>`` to
``dev10x-<area>:<skill>``, it appends one row to ``SKILL_NAME_ALIASES``.
``dev10x config migrate-skill-names`` then rewrites the old name in the
user's hand-edited files, and :func:`resolve_skill_alias` maps the old
name to the new one until the row's ``removed_in``. While the table holds
rows, a ``SKILL_NAME_ALIASES`` entry in
:mod:`dev10x.core.domain.deprecations` must outlive every row.

The table is empty between extractions. The B1–B3 rows (``dev10x-qa``,
``dev10x-infra``, ``dev10x-db``) shipped in 0.114.0 and 0.115.0 and were
retired at 0.116.0 (GH-1865). B4 (GH-1567) adds the seven skills that moved
to ``dev10x-comm``, B5 (GH-1568) the seven that moved to ``dev10x-teach``,
B6 (GH-1569) the eight that moved to ``dev10x-tasks``, B7 (GH-1570) the
nineteen that moved to ``dev10x-scoping`` and B9 (GH-1572) the forty that
moved to ``dev10x-coding``; all five ship in 0.116.0, so their rows end two
releases later. Every write takes the file's lock and
lands atomically, and a second run finds nothing left to rewrite.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from dev10x.core.domain.common.result import Result, err, ok
from dev10x.core.domain.deprecations import parse_release
from dev10x.core.domain.file_locks import LockTimeoutError, atomic_write_text, file_lock
from dev10x.core.skill_rename import InvocationName, rewrite_text

FRICTION_YAML = "friction.yaml"
DOD_CRITERIA_YAML = "dod-acceptance-criteria.yaml"
PLAYBOOKS_DIR = "playbooks"


@dataclass(frozen=True)
class SkillNameAlias:
    old: str
    new: str
    removed_in: str

    def names(self) -> tuple[InvocationName, InvocationName]:
        return _invocation(text=self.old), _invocation(text=self.new)


EXTRACTION_ALIAS_REMOVED_IN = "0.118.0"

_MOVED_IN_0_116_EXTRACTIONS: dict[str, tuple[str, ...]] = {
    "dev10x-comm": (
        "bus",
        "gchat",
        "gog",
        "overwatch",
        "slack",
        "slack-setup",
        "voice-channel",
    ),
    "dev10x-teach": (
        "audit-file",
        "context-audit",
        "memory-maintenance",
        "skill-audit",
        "skill-audit-queue",
        "skill-create",
        "skill-index",
    ),
    "dev10x-tasks": (
        "park",
        "park-discover",
        "park-remind",
        "park-todo",
        "plan-sync",
        "reflect",
        "session-tasks",
        "session-wrap-up",
    ),
    "dev10x-scoping": (
        "adr",
        "adr-evaluate",
        "artifact",
        "ddd",
        "diagram-bpmn",
        "diagram-c4",
        "diagram-sequence",
        "estimate",
        "jira",
        "jtbd",
        "linear",
        "project-audit",
        "project-scope",
        "scope",
        "spec-sync",
        "spec-update",
        "ticket-create",
        "ticket-jtbd",
        "ticket-scope",
    ),
    "dev10x-coding": (
        "ci-review",
        "fanout",
        "foreman",
        "gchat-review-request",
        "gh-pr-bookmark",
        "gh-pr-create",
        "gh-pr-doctor",
        "gh-pr-fixup",
        "gh-pr-merge",
        "gh-pr-monitor",
        "gh-pr-request-review",
        "gh-pr-respond",
        "gh-pr-review",
        "gh-pr-triage",
        "gh-review-setup",
        "git",
        "git-alias-setup",
        "git-branch-prune",
        "git-commit",
        "git-commit-split",
        "git-fixup",
        "git-groom",
        "git-promote",
        "git-worktree",
        "git-worktree-prune",
        "ide-normalize",
        "investigate",
        "py-mockito",
        "py-test",
        "py-test-flaky",
        "py-uv",
        "qa-scope",
        "release-notes",
        "request-review",
        "review",
        "review-fix",
        "slack-review-request",
        "ticket-branch",
        "verify-acc-dod",
        "work-on",
    ),
}

SKILL_NAME_ALIASES: tuple[SkillNameAlias, ...] = tuple(
    SkillNameAlias(
        old=f"dev10x:{skill}",
        new=f"{plugin}:{skill}",
        removed_in=EXTRACTION_ALIAS_REMOVED_IN,
    )
    for plugin, skills in _MOVED_IN_0_116_EXTRACTIONS.items()
    for skill in skills
)


@dataclass(frozen=True)
class ConfigRewrite:
    path: Path
    replacements: int


def _invocation(*, text: str) -> InvocationName:
    plugin, _, skill = text.partition(":")
    return InvocationName(plugin=plugin, skill=skill)


def resolve_skill_alias(
    *,
    name: str,
    aliases: Iterable[SkillNameAlias] = SKILL_NAME_ALIASES,
) -> str:
    for alias in aliases:
        if name == alias.old:
            name = alias.new
    return name


def aliases_outliving(*, aliases: Iterable[SkillNameAlias], removed_in: str) -> list[str]:
    limit = parse_release(removed_in)
    return [alias.old for alias in aliases if parse_release(alias.removed_in) > limit]


def user_config_files(*, config_home: Path) -> list[Path]:
    singles = [config_home / FRICTION_YAML, config_home / DOD_CRITERIA_YAML]
    playbooks = sorted((config_home / PLAYBOOKS_DIR).glob("*.yaml"))
    return [path for path in [*singles, *playbooks] if path.is_file()]


def migrate_text(*, text: str, aliases: Sequence[SkillNameAlias]) -> tuple[str, int]:
    total = 0
    for alias in aliases:
        old, new = alias.names()
        text, replacements = rewrite_text(text=text, old=old, new=new)
        total += replacements
    return text, total


def migrate_user_configs(
    *,
    config_home: Path,
    aliases: Sequence[SkillNameAlias] = SKILL_NAME_ALIASES,
    dry_run: bool,
) -> Result[list[ConfigRewrite]]:
    rewrites: list[ConfigRewrite] = []
    for path in user_config_files(config_home=config_home):
        try:
            with file_lock(path):
                after, replacements = migrate_text(text=path.read_text(), aliases=aliases)
                if replacements and not dry_run:
                    atomic_write_text(path, after)
        except LockTimeoutError as error:
            return err(f"{path}: {error}. Please try again.")
        if replacements:
            rewrites.append(ConfigRewrite(path=path, replacements=replacements))
    return ok(rewrites)


__all__ = [
    "DOD_CRITERIA_YAML",
    "FRICTION_YAML",
    "PLAYBOOKS_DIR",
    "SKILL_NAME_ALIASES",
    "ConfigRewrite",
    "SkillNameAlias",
    "aliases_outliving",
    "migrate_text",
    "migrate_user_configs",
    "resolve_skill_alias",
    "user_config_files",
]
