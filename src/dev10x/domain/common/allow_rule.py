"""AllowRule value object — a single Claude Code permission allow rule.

Consolidates four drifted ``Tool(pattern)`` matching implementations and
five settings loaders that had diverged semantically (audit finding C2/C3,
2026-05-18). Before this module the same allow rule could be reported as
matched by one diagnostic and unmatched by another.

The canonical matching semantics are the space-boundary-aware ones that
``hooks/permission_diagnostics`` already used (the strictest, most correct
of the four):

- ``mcp__`` rules and bare globs (no parentheses): ``fnmatch`` over the
  whole signature.
- ``Bash`` rules with a ``:*`` suffix: the command must equal the prefix
  exactly or continue past a space boundary — so ``Bash(git:*)`` matches
  ``git status`` but NOT ``github-cli``.
- ``Read``/``Write``/``Edit`` rules with a ``**`` suffix: directory prefix
  match. Other path patterns fall back to ``fnmatch``.

``~`` and ``$HOME`` are expanded on both sides of prefix comparisons so a
``~/.claude/skills`` rule matches a ``/home/<user>/.claude/skills`` command.
"""

from __future__ import annotations

import fnmatch
import json
import os
from dataclasses import dataclass
from pathlib import Path

_PATH_TOOLS = frozenset({"Read", "Write", "Edit"})


def _expand(value: str) -> str:
    return os.path.expandvars(os.path.expanduser(value))


@dataclass(frozen=True)
class AllowRule:
    tool: str
    pattern: str
    raw: str

    def __str__(self) -> str:
        return self.raw

    @classmethod
    def parse(cls, rule: str) -> AllowRule:
        if "(" not in rule or not rule.endswith(")"):
            return cls(tool=rule, pattern="", raw=rule)
        paren = rule.index("(")
        return cls(tool=rule[:paren], pattern=rule[paren + 1 : -1], raw=rule)

    @classmethod
    def bash(cls, pattern: str) -> AllowRule:
        return cls.parse(f"Bash({pattern})")

    @classmethod
    def read(cls, pattern: str) -> AllowRule:
        return cls.parse(f"Read({pattern})")

    @classmethod
    def write(cls, pattern: str) -> AllowRule:
        return cls.parse(f"Write({pattern})")

    @classmethod
    def edit(cls, pattern: str) -> AllowRule:
        return cls.parse(f"Edit({pattern})")

    @classmethod
    def skill(cls, name: str) -> AllowRule:
        return cls.parse(f"Skill({name})")

    def matches(self, signature: str) -> bool:
        if "(" not in self.raw or not self.raw.endswith(")"):
            return fnmatch.fnmatch(name=signature, pat=self.raw)

        sig_paren = signature.find("(")
        if sig_paren == -1:
            return fnmatch.fnmatch(name=signature, pat=self.raw)

        if signature[:sig_paren] != self.tool:
            return False

        value = signature[sig_paren + 1 :].rstrip(")")
        return self._matches_value(value=value)

    def _matches_value(self, *, value: str) -> bool:
        if self.tool == "Bash" and self.pattern.endswith(":*"):
            prefix = _expand(self.pattern[:-2])
            expanded = _expand(value)
            return expanded == prefix or expanded.startswith(prefix + " ")

        if self.tool in _PATH_TOOLS and self.pattern.endswith("**"):
            prefix = _expand(self.pattern[:-2])
            return _expand(value).startswith(prefix)

        return fnmatch.fnmatch(name=value, pat=self.pattern)


class AllowRuleLoader:
    """Loads ``permissions.allow`` rule strings from a settings JSON file."""

    @staticmethod
    def load_optional(path: str | Path) -> list[str] | None:
        """Return the allow list, or ``None`` when the file has no valid one.

        ``None`` distinguishes "no allow list present" (missing file,
        malformed JSON, absent or non-list ``allow`` key) from an explicitly
        empty ``[]``. Callers that need that distinction (e.g. permission
        diagnostics reporting ``has_allow_list``) use this; callers that just
        want rules use :meth:`load`.
        """
        p = Path(path)
        if not p.is_file():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        allow = data.get("permissions", {}).get("allow")
        if not isinstance(allow, list):
            return None
        return allow

    @staticmethod
    def load(path: str | Path) -> list[str]:
        """Return the allow list, or ``[]`` on missing/malformed input."""
        return AllowRuleLoader.load_optional(path=path) or []
