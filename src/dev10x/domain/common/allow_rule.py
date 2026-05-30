"""AllowRule value object — canonical ``Tool(pattern)`` permission rule.

Consolidates four drifted matching/parsing implementations that
produced contradictory diagnostics from the same allow rule
(audit finding C2, 2026-05-18):

- ``hooks/permission_diagnostics.PermissionResolutionPolicy`` — signature
  matching with ``:*`` space-boundary expansion (the correct semantics,
  adopted here as canonical).
- ``skills/audit/analyze_permissions.matches_allow_rule`` /
  ``parse_allow_rules`` — diverged on ``:*`` (bare ``startswith``) and an
  empty-rules quirk.
- ``validators/prefix_friction._matches_allow_rule`` /
  ``_load_all_allow_patterns`` — path-coverage matching + a settings loader.
- ``skills/permission_investigator/report._extract_path`` — inner-path
  extraction.

The settings loader duplicated across 8+ sites (finding C3) lives here as
``AllowRuleLoader``; the factory helpers (finding C9) build canonical rule
strings without hand-formatting ``Tool(pattern)``.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

_RULE_RE = re.compile(r"^(?P<tool>[A-Za-z_]\w*)\((?P<pattern>.*)\)$")


@dataclass(frozen=True)
class AllowRule:
    tool: str
    pattern: str
    raw: str

    @classmethod
    def parse(cls, rule: str) -> AllowRule:
        stripped = rule.strip()
        match = _RULE_RE.match(stripped)
        if match:
            return cls(tool=match.group("tool"), pattern=match.group("pattern"), raw=rule)
        return cls(tool=stripped, pattern="", raw=rule)

    @classmethod
    def try_parse(cls, rule: str) -> AllowRule | None:
        if not isinstance(rule, str) or not rule.strip():
            return None
        return cls.parse(rule)

    def matches(self, signature: str) -> bool:
        rule = self.raw.strip()
        if signature.startswith("mcp__") or "(" not in rule:
            return fnmatch.fnmatch(name=signature, pat=rule)

        target = AllowRule.parse(signature)
        if target.tool != self.tool:
            return False
        return self._pattern_matches(value=target.pattern)

    def _pattern_matches(self, *, value: str) -> bool:
        pattern = self.pattern
        if pattern.endswith(":*"):
            prefix = pattern[:-2]
            return value == prefix or value.startswith(prefix + " ")
        if pattern.endswith("**"):
            return value.startswith(pattern[:-2])
        return fnmatch.fnmatch(name=value, pat=pattern)

    @property
    def is_prefix(self) -> bool:
        return self.pattern.endswith(":*")

    @property
    def inner_path(self) -> str:
        if ":" in self.pattern:
            return self.pattern.split(":", 1)[0]
        return self.pattern

    def covers_path(self, segment: str) -> bool:
        base = self.inner_path
        if not base:
            return False
        expanded_segment = os.path.expanduser(segment)
        expanded_base = os.path.expanduser(base)
        return expanded_segment.startswith(expanded_base) or segment.startswith(base)

    @classmethod
    def bash(cls, pattern: str) -> AllowRule:
        return cls(tool="Bash", pattern=pattern, raw=f"Bash({pattern})")

    @classmethod
    def read(cls, pattern: str) -> AllowRule:
        return cls(tool="Read", pattern=pattern, raw=f"Read({pattern})")

    @classmethod
    def skill(cls, pattern: str) -> AllowRule:
        return cls(tool="Skill", pattern=pattern, raw=f"Skill({pattern})")


class AllowRuleLoader:
    @staticmethod
    def load(path: str | Path) -> list[str]:
        try:
            data = json.loads(Path(path).read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return []
        allow = data.get("permissions", {}).get("allow", [])
        if not isinstance(allow, list):
            return []
        return [entry if isinstance(entry, str) else str(entry) for entry in allow]

    @classmethod
    def rules(cls, path: str | Path) -> list[AllowRule]:
        return [rule for raw in cls.load(path) if (rule := AllowRule.try_parse(raw))]
