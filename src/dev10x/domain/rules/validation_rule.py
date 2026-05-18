from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import cached_property
from typing import Any

_SUBCOMMAND_BOUNDARY = r"(?![-\w])"

_SEARCH_TOOLS = frozenset({"find", "grep", "fgrep", "egrep", "rg", "ag", "ack", "xargs"})


def _resolved_executable(command: str) -> str:
    """Return the resolved executable basename for a shell command.

    Strips shell wrappers (``bash``, ``sh``, ``env VAR=x``) so a search
    tool invoked via ``bash`` is still recognized. Returns an empty
    string when the command is malformed.
    """
    parts = command.strip().split()
    idx = 0
    while idx < len(parts):
        head = parts[idx]
        if head in ("bash", "sh"):
            idx += 1
            continue
        if head == "env":
            idx += 1
            while idx < len(parts) and "=" in parts[idx]:
                idx += 1
            continue
        return head.split("/")[-1]
    return ""


def _is_search_command(command: str) -> bool:
    """Return True when the resolved executable is a filesystem search tool.

    Used by :meth:`Rule.matches_command` to suppress false positives where
    a rule pattern matches a filename appearing as a *search argument*
    (e.g. ``find -name 'git-push-safe.sh'``) rather than a command being
    executed (GH-210). Commands containing ``-exec`` or shell pipelines
    keep their normal evaluation because they can run the searched-for
    binary.
    """
    if "|" in command or "-exec" in command:
        return False
    return _resolved_executable(command=command) in _SEARCH_TOOLS


def _anchor_subcommand(*, pattern: str) -> str:
    """Anchor a CLI subcommand pattern at the right edge.

    YAML patterns like ``git commit`` or ``gh pr create`` are
    command-name prefixes; without a right-edge boundary, ``git commit``
    matches inside ``git commit-msg`` (an argument value), producing
    false positives (GH-84). Append a negative lookahead so the
    pattern's last token cannot be followed by another word or hyphen
    character.

    Patterns already ending in a regex anchor (``$``, ``\\b``) or an
    explicit lookaround are left untouched.
    """
    if pattern.endswith(("$", r"\b")) or pattern.endswith((")", "]")):
        return pattern
    return pattern + _SUBCOMMAND_BOUNDARY


@dataclass(frozen=True)
class Compensation:
    type: str
    skill: str = ""
    tool: str = ""
    alias: str = ""
    guardrails: str = ""
    fallback: str = ""
    description: str = ""

    @classmethod
    def from_yaml_entry(cls, entry: dict[str, Any]) -> Compensation:
        return cls(**{k: v for k, v in entry.items() if k in cls.__dataclass_fields__})


@dataclass(frozen=True)
class Rule:
    name: str
    patterns: list[str] = field(default_factory=list)
    matcher: str = "Bash"
    except_: list[str] = field(default_factory=list)
    compensations: list[Compensation] = field(default_factory=list)
    hook_block: bool = True
    reason: str = ""
    message: str = ""
    related: list[str] = field(default_factory=list)
    file_pattern: str = ""
    file_names: list[str] = field(default_factory=list)
    file_prefixes: list[str] = field(default_factory=list)
    file_substrings: list[str] = field(default_factory=list)
    content_pattern: str = ""

    @cached_property
    def compiled_patterns(self) -> list[re.Pattern[str]]:
        return [re.compile(_anchor_subcommand(pattern=p)) for p in self.patterns]

    @cached_property
    def compiled_file_pattern(self) -> re.Pattern[str] | None:
        return re.compile(self.file_pattern) if self.file_pattern else None

    @cached_property
    def compiled_content_pattern(self) -> re.Pattern[str] | None:
        return re.compile(self.content_pattern) if self.content_pattern else None

    def matches_file(self, *, file_path: str) -> bool:
        if self.compiled_file_pattern and self.compiled_file_pattern.search(file_path):
            return True
        name = file_path.rsplit("/", 1)[-1] if "/" in file_path else file_path
        if name in self.file_names:
            return True
        if any(name.startswith(p) for p in self.file_prefixes):
            return True
        return any(s in file_path for s in self.file_substrings)

    def matches_content(self, *, content: str) -> bool:
        if self.compiled_content_pattern is None:
            return True
        return self.compiled_content_pattern.search(content) is not None

    def format_message(self, *, file_path: str) -> str:
        text = self.message or self.reason or "BLOCKED"
        msg = text.format(file_path=file_path)
        for comp in self.compensations:
            desc = comp.description
            if desc:
                msg += f"\n\n{desc.strip()}"
        return msg

    def matches_command(self, *, command: str) -> bool:
        if not any(p.search(command) for p in self.compiled_patterns):
            return False
        if any(exc in command for exc in self.except_):
            return False
        if _is_search_command(command=command):
            return False
        return True

    @classmethod
    def from_yaml_entry(cls, entry: dict[str, Any]) -> Rule:
        compensations = [
            Compensation.from_yaml_entry(entry=c) for c in entry.get("compensations", [])
        ]
        return cls(
            name=entry.get("name", ""),
            patterns=entry.get("patterns", []),
            matcher=entry.get("matcher", "Bash"),
            except_=entry.get("except", []),
            compensations=compensations,
            hook_block=entry.get("hook_block", True),
            reason=entry.get("reason", ""),
            message=entry.get("message", ""),
            related=entry.get("related", []),
            file_pattern=entry.get("file_pattern", ""),
            file_names=entry.get("file_names", []),
            file_prefixes=entry.get("file_prefixes", []),
            file_substrings=entry.get("file_substrings", []),
            content_pattern=entry.get("content_pattern", ""),
        )
