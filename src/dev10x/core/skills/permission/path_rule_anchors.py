"""Anchor and depth semantics for ``Read``/``Edit``/``Write`` rules (GH-1325).

Claude Code matches path-tool rules as gitignore patterns, which makes two
properties decidable that the catalog previously guessed at:

- the leading token selects the anchor, and a *single* leading slash
  anchors at the settings source rather than at the filesystem root;
- ``**`` crosses directory separators, so one tree rule reaches every
  depth beneath its anchor and a per-subdirectory enumeration adds
  nothing.

``**`` is read here as *one or more* segments. That understates a rule's
real reach, so an equivalence proof built on :func:`covers` can never
overstate what a replacement rule grants.

None of this applies to ``Bash()`` rules, which are matched as literal
command prefixes.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

PATH_TOOLS: tuple[str, ...] = ("Read", "Edit", "Write")

_RULE = re.compile(r"^(?P<tool>Read|Edit|Write)\((?P<pattern>.*)\)$")


class Anchor(Enum):
    FILESYSTEM = "filesystem"
    HOME = "home"
    SETTINGS_SOURCE = "settings_source"
    RELATIVE = "relative"


@dataclass(frozen=True)
class PathRule:
    tool: str
    pattern: str
    anchor: Anchor

    @property
    def reaches_a_fixed_location(self) -> bool:
        return self.anchor in (Anchor.FILESYSTEM, Anchor.HOME)


def anchor_of(*, pattern: str) -> Anchor:
    if pattern.startswith("//"):
        return Anchor.FILESYSTEM
    if pattern.startswith("~/"):
        return Anchor.HOME
    if pattern.startswith("/"):
        return Anchor.SETTINGS_SOURCE
    return Anchor.RELATIVE


def parse_path_rule(*, rule: str) -> PathRule | None:
    match = _RULE.match(rule.strip())
    if match is None:
        return None
    pattern = match.group("pattern")
    return PathRule(
        tool=match.group("tool"),
        pattern=pattern,
        anchor=anchor_of(pattern=pattern),
    )


def path_rules(*, rules: Iterable[str]) -> list[PathRule]:
    parsed = (parse_path_rule(rule=rule) for rule in rules)
    return [rule for rule in parsed if rule is not None]


def _segment_to_regex(*, segment: str) -> str:
    return "".join("[^/]*" if char == "*" else re.escape(char) for char in segment)


def _pattern_to_regex(*, pattern: str) -> re.Pattern[str]:
    parts = [
        r"[^/]+(?:/[^/]+)*" if segment == "**" else _segment_to_regex(segment=segment)
        for segment in pattern.split("/")
    ]
    return re.compile("^" + "/".join(parts) + "$")


def covers(*, rule: PathRule, absolute_path: str) -> bool:
    if rule.anchor is not Anchor.FILESYSTEM:
        return False
    return _pattern_to_regex(pattern=rule.pattern[1:]).match(absolute_path) is not None


def covered_by_any(*, rules: Iterable[PathRule], tool: str, absolute_path: str) -> bool:
    return any(
        covers(rule=rule, absolute_path=absolute_path) for rule in rules if rule.tool == tool
    )
