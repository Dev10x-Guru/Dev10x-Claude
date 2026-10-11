"""Rewrite one skill's invocation name across the repository (ADR-0034, GH-1558).

Stage B moves ``dev10x:<skill>`` to ``dev10x-<area>:<skill>`` one plugin
at a time. The scan covers the NS-05b inventory scope
(:func:`dev10x.core.skill_references.scanned_paths`) plus the
``command-skill-map.d`` fragments, so the inventory test can verify a
rename by counts alone. ``.claude/`` is outside that scope on purpose:
rule files there are supervisor-owned and get their own pass.

A rename refuses a target name that the tree already uses. That guard is
what makes ``A -> B -> A`` byte-identical: without it, the reverse step
would also rewrite references that were ``B`` before the first step.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from dev10x.core.config.loader import fragment_dir
from dev10x.core.domain.common.result import ErrorResult, Result, err, ok
from dev10x.core.domain.file_locks import atomic_write_text
from dev10x.core.plugin_map import CORE_PLUGIN_NAME, PluginMap
from dev10x.core.skill_references import SCANNED_FILES, scanned_paths

COMMAND_SKILL_MAP = SCANNED_FILES[0]
SKILL_PART = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")
BOUNDARY_BEFORE = r"(?<![\w.-])"
BOUNDARY_AFTER = r"(?![\w-])"


@dataclass(frozen=True)
class InvocationName:
    plugin: str
    skill: str

    @property
    def text(self) -> str:
        return f"{self.plugin}:{self.skill}"

    def pattern(self) -> re.Pattern[str]:
        first, rest = self.plugin[0], self.plugin[1:]
        lead = f"[{first.lower()}{first.upper()}]"
        return re.compile(
            f"{BOUNDARY_BEFORE}{lead}{re.escape(rest)}:{re.escape(self.skill)}{BOUNDARY_AFTER}"
        )

    def spelled_like(self, *, matched: str) -> str:
        if matched[:1].isupper():
            return self.text[:1].upper() + self.text[1:]
        return self.text


@dataclass(frozen=True)
class FileRewrite:
    path: Path
    before: str
    after: str
    replacements: int

    def diff(self, *, root: Path) -> str:
        name = self.path.relative_to(root).as_posix()
        return "".join(
            difflib.unified_diff(
                self.before.splitlines(keepends=True),
                self.after.splitlines(keepends=True),
                fromfile=f"a/{name}",
                tofile=f"b/{name}",
            )
        )


@dataclass(frozen=True)
class RenamePlan:
    root: Path
    old: InvocationName
    new: InvocationName
    rewrites: tuple[FileRewrite, ...]

    @property
    def replacements(self) -> int:
        return sum(rewrite.replacements for rewrite in self.rewrites)

    def diff(self) -> str:
        return "".join(rewrite.diff(root=self.root) for rewrite in self.rewrites)

    def apply(self) -> None:
        for rewrite in self.rewrites:
            atomic_write_text(rewrite.path, rewrite.after)


def parse_invocation_name(*, text: str, plugin_names: Iterable[str]) -> Result[InvocationName]:
    known = tuple(plugin_names)
    plugin, separator, skill = text.partition(":")
    if not separator:
        plugin, skill = CORE_PLUGIN_NAME, text
    if plugin not in known:
        return err(f"{text!r}: unknown plugin {plugin!r}; expected one of {', '.join(known)}")
    if not SKILL_PART.match(skill):
        return err(f"{text!r}: {skill!r} is not a skill name")
    return ok(InvocationName(plugin=plugin, skill=skill))


def rename_scope(*, root: Path) -> list[Path]:
    fragments = sorted(fragment_dir(yaml_path=root / COMMAND_SKILL_MAP).glob("*.yaml"))
    return sorted({*scanned_paths(root=root), *fragments})


def rewrite_text(*, text: str, old: InvocationName, new: InvocationName) -> tuple[str, int]:
    return old.pattern().subn(lambda found: new.spelled_like(matched=found.group(0)), text)


def count_mentions(*, paths: Iterable[Path], name: InvocationName) -> int:
    pattern = name.pattern()
    return sum(len(pattern.findall(path.read_text(errors="replace"))) for path in paths)


def plan_rename(*, root: Path, old: InvocationName, new: InvocationName) -> Result[RenamePlan]:
    if old == new:
        return err(f"{old.text} and {new.text} are the same name")
    paths = rename_scope(root=root)
    taken = count_mentions(paths=paths, name=new)
    if taken:
        return err(
            f"{new.text} is already referenced {taken} time(s); renaming onto it "
            "would merge two names and make the rename irreversible"
        )
    rewrites: list[FileRewrite] = []
    for path in paths:
        before = path.read_text(errors="replace")
        after, replacements = rewrite_text(text=before, old=old, new=new)
        if replacements:
            rewrites.append(
                FileRewrite(path=path, before=before, after=after, replacements=replacements)
            )
    return ok(RenamePlan(root=root, old=old, new=new, rewrites=tuple(rewrites)))


def plan_rename_from_text(
    *,
    root: Path,
    old: str,
    new: str,
    plugin_map: PluginMap,
) -> Result[RenamePlan]:
    names = plugin_map.known_plugin_names()
    parsed_old = parse_invocation_name(text=old, plugin_names=names)
    if isinstance(parsed_old, ErrorResult):
        return parsed_old
    parsed_new = parse_invocation_name(text=new, plugin_names=names)
    if isinstance(parsed_new, ErrorResult):
        return parsed_new
    return plan_rename(root=root, old=parsed_old.value, new=parsed_new.value)


__all__ = [
    "COMMAND_SKILL_MAP",
    "FileRewrite",
    "InvocationName",
    "RenamePlan",
    "count_mentions",
    "parse_invocation_name",
    "plan_rename",
    "plan_rename_from_text",
    "rename_scope",
    "rewrite_text",
]
