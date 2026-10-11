"""Rewrite renamed skill names in user configs (ADR-0034 Stage A4, GH-1559).

When a Stage B step moves a skill from ``dev10x:<skill>`` to
``dev10x-<area>:<skill>``, it appends one row to ``SKILL_NAME_ALIASES``.
``dev10x config migrate-skill-names`` then rewrites the old name in the
user's hand-edited files, and :func:`resolve_skill_alias` keeps the old
name readable as a deprecated alias until the row's ``removed_in``. The
register entry for ``SKILL_NAME_ALIASES`` in
:mod:`dev10x.core.domain.deprecations` must outlive every row.

Stage A renames nothing, so the table ships empty; fixtures prove the
mechanism. Every write takes the file's lock and lands atomically, and
a second run finds nothing left to rewrite.
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


SKILL_NAME_ALIASES: tuple[SkillNameAlias, ...] = ()


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
