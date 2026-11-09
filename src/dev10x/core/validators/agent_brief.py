"""Validator: a subagent brief names the skill that owns its work (DX020, GH-1835).

Foreman and fanout crews get a structured brief; a plain ``Agent`` call
gets whatever the dispatcher typed. Those free-form briefs are where
subagents rebuild what a skill already does — a hand-rolled Playwright
harness instead of ``dev10x-qa:qa-self``, a raw ``git commit`` instead
of ``dev10x:git-commit`` — and where a hook denial turns into a hunt for
another way to run the same command.

This validator reads the ``Agent`` prompt. When it matches a pattern
from the keyword map but names neither the mapped skill nor one of its
accepted aliases, the dispatcher hears about it before the subagent
starts. A brief that deliberately does without the skill carries a line
``dev10x-ok: <reason>``, which keeps the exception auditable.

The map ships in ``agent-skill-map.yaml``. A project adjusts it, and
switches from the advisory default to ``deny``, through the ``dx020``
key of its ``friction.yaml`` entry, read like DX017's: file reads only,
worktree first, main checkout second.
"""

from __future__ import annotations

import functools
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from dev10x.domain import HookHint, HookInput, HookResult
from dev10x.domain.documents.friction_yaml import load_checkout_prefs
from dev10x.domain.documents.yaml_mapping import load_yaml_mapping
from dev10x.domain.profile_tier import ProfileTier
from dev10x.validators.base import ValidatorBase

log = logging.getLogger(__name__)

AGENT_TOOLS = frozenset({"Agent"})
PREFS_KEY = "dx020"
MODE_DENY = "deny"
ESCAPE = re.compile(r"^[ \t]*dev10x-ok:[ \t]*\S", re.IGNORECASE | re.MULTILINE)
MAP_PATH = Path(__file__).parent / "agent-skill-map.yaml"

_HOOK_DENIAL_RULE = (
    "Tell the subagent to invoke it (or its MCP wrapper), and to stop and "
    "report if a hook blocks a command rather than work around it."
)


@dataclass(frozen=True)
class SkillKeyword:
    skill: str
    patterns: tuple[re.Pattern[str], ...]
    names: re.Pattern[str]
    accept: tuple[str, ...] = ()

    def first_match(self, *, brief: str) -> str | None:
        for pattern in self.patterns:
            found = pattern.search(brief)
            if found:
                return found.group(0)
        return None

    def is_named_in(self, *, brief: str) -> bool:
        return self.names.search(brief) is not None


@dataclass(frozen=True)
class Finding:
    skill: str
    matched: str


def _strings(*, raw: Any) -> tuple[str, ...]:
    """The non-empty strings of a YAML list; anything else reads as empty."""
    if not isinstance(raw, list):
        return ()
    return tuple(item for item in raw if isinstance(item, str) and item)


def _compile(*, raw: Any, skill: str) -> tuple[re.Pattern[str], ...]:
    compiled = []
    for item in _strings(raw=raw):
        try:
            compiled.append(re.compile(item, re.IGNORECASE))
        except re.error:
            log.warning("DX020: skipping invalid pattern %r for %s", item, skill)
    return tuple(compiled)


def _name_pattern(*, names: tuple[str, ...]) -> re.Pattern[str]:
    alternatives = "|".join(re.escape(name) for name in names)
    return re.compile(rf"(?:(?<=__)|(?<![\w-]))(?:{alternatives})(?![\w-])", re.IGNORECASE)


def parse_entries(*, raw: Any) -> tuple[SkillKeyword, ...]:
    """Build keyword entries from a YAML list; malformed items are skipped."""
    if not isinstance(raw, list):
        return ()
    entries = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        skill = item.get("skill")
        if not isinstance(skill, str) or not skill:
            continue
        patterns = _compile(raw=item.get("patterns"), skill=skill)
        if not patterns:
            continue
        aliases = _strings(raw=item.get("accept"))
        entries.append(
            SkillKeyword(
                skill=skill,
                patterns=patterns,
                names=_name_pattern(names=(skill, *aliases)),
                accept=aliases,
            )
        )
    return tuple(entries)


@functools.cache
def default_entries() -> tuple[SkillKeyword, ...]:
    entries = parse_entries(raw=load_yaml_mapping(MAP_PATH).get("entries"))
    if not entries:
        log.warning("DX020: no keyword entries loaded from %s", MAP_PATH)
    return entries


def effective_entries(*, section: dict[str, Any]) -> tuple[SkillKeyword, ...]:
    """Defaults, minus ``skill_keywords.remove`` skills, plus ``.add`` entries."""
    overrides = section.get("skill_keywords")
    if not isinstance(overrides, dict):
        return default_entries()
    removed = set(_strings(raw=overrides.get("remove")))
    kept = tuple(entry for entry in default_entries() if entry.skill not in removed)
    return kept + parse_entries(raw=overrides.get("add"))


def _rule_section(*, cwd: str) -> dict[str, Any]:
    if not cwd:
        return {}
    section = load_checkout_prefs(checkout=Path(cwd)).get(PREFS_KEY)
    return section if isinstance(section, dict) else {}


def _brief(*, inp: HookInput) -> str:
    tool_input = inp.raw.get("tool_input")
    if not isinstance(tool_input, dict):
        return ""
    parts = (tool_input.get("description"), tool_input.get("prompt"))
    return "\n".join(part for part in parts if isinstance(part, str))


def find_unnamed_skills(*, brief: str, entries: tuple[SkillKeyword, ...]) -> list[Finding]:
    if ESCAPE.search(brief):
        return []
    return [
        Finding(skill=entry.skill, matched=matched)
        for entry in entries
        if (matched := entry.first_match(brief=brief)) and not entry.is_named_in(brief=brief)
    ]


def _message(*, findings: list[Finding], deny: bool) -> str:
    lines = [
        "🧭 Agent brief check (DX020): this brief asks for work a sanctioned "
        "skill owns, but does not name the skill:"
    ]
    lines += [f"  - `{finding.matched}` → `{finding.skill}`" for finding in findings]
    lines.append(_HOOK_DENIAL_RULE)
    lines.append(
        "If the brief deliberately does without the skill, add a line `dev10x-ok: <reason>` to it."
    )
    if deny:
        lines.append(
            "This repo sets `dx020: {mode: deny}` in friction.yaml; "
            "`DEV10X_HOOK_DISABLE=DX020` lifts it for a session."
        )
    return "\n".join(lines)


@dataclass
class AgentBriefValidator(ValidatorBase):
    """Flag ``Agent`` briefs that route around a sanctioned skill."""

    name: ClassVar[str] = "agent-brief"
    rule_id: ClassVar[str] = "DX020"
    profile: ClassVar[ProfileTier] = ProfileTier.STANDARD
    experimental: ClassVar[bool] = False

    def should_run(self, inp: HookInput) -> bool:
        return inp.tool_name in AGENT_TOOLS

    def validate(self, inp: HookInput) -> HookResult | HookHint | None:
        brief = _brief(inp=inp)
        if not brief.strip():
            return None
        section = _rule_section(cwd=inp.cwd)
        findings = find_unnamed_skills(brief=brief, entries=effective_entries(section=section))
        if not findings:
            return None
        deny = section.get("mode") == MODE_DENY
        message = _message(findings=findings, deny=deny)
        if deny:
            return HookResult(message=message, rule_id=self.rule_id)
        return HookHint(message=message, rule_id=self.rule_id)
