"""Count actionable instructions per skill to enforce instruction budget.

Background (QRSPI): frontier LLMs follow ~150–200 instructions reliably,
then silently skip the rest. The model does not error — it quietly drops
alignment steps buried deepest in the instruction list. Large skills
like `work-on`, `scope`, and `ticket-scope` risk silent instruction
loss when their cumulative instruction set crosses this threshold.

This module counts actionable instructions in a skill file and
classifies the result so reviewers can flag skills approaching the
budget before they start dropping steps.

What counts as an actionable instruction:

- Numbered list items (Markdown `1.`, `2.`, etc.)
- Bulleted list items starting with an imperative verb
- Lines containing a **REQUIRED**, **MUST**, or **DO NOT** marker
- Tool-call specs (`AskUserQuestion(...)`, `TaskCreate(...)`,
  `Skill(...)`, etc.) on their own line

Comments, headings, prose paragraphs, table cells, and YAML
front matter are excluded — they provide context, not instructions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# ── Thresholds (tunable via --threshold flag) ──────────────────────────
DEFAULT_WARN = 100
DEFAULT_OVER = 150

# ── Line classifiers ───────────────────────────────────────────────────
_NUMBERED_LIST = re.compile(r"^\s*\d+\.\s+\S")
_BULLET_LIST = re.compile(r"^\s*[-*+]\s+(?:\*\*)?[A-Z]")
_ENFORCEMENT = re.compile(r"\*\*(REQUIRED|MUST|DO NOT|MANDATORY|ALWAYS|NEVER)\b", re.IGNORECASE)
_TOOL_CALL = re.compile(
    r"^\s*(?:`?|\*\*)?(AskUserQuestion|TaskCreate|TaskUpdate|Skill|Agent|Write|Edit|Read|Bash)\s*\("
)
_IMPERATIVE_VERBS = {
    "add",
    "apply",
    "ask",
    "assert",
    "assign",
    "build",
    "call",
    "check",
    "choose",
    "classify",
    "commit",
    "confirm",
    "convert",
    "copy",
    "create",
    "declare",
    "delegate",
    "delete",
    "detect",
    "dispatch",
    "edit",
    "ensure",
    "enter",
    "execute",
    "extract",
    "fetch",
    "find",
    "fix",
    "format",
    "gather",
    "generate",
    "get",
    "handle",
    "identify",
    "implement",
    "inject",
    "insert",
    "install",
    "invoke",
    "launch",
    "list",
    "load",
    "log",
    "mark",
    "merge",
    "monitor",
    "move",
    "name",
    "never",
    "open",
    "parse",
    "persist",
    "plan",
    "post",
    "prefer",
    "preserve",
    "print",
    "proceed",
    "process",
    "prompt",
    "push",
    "query",
    "read",
    "register",
    "reject",
    "remove",
    "rename",
    "replace",
    "report",
    "request",
    "require",
    "reset",
    "resolve",
    "respond",
    "restart",
    "return",
    "review",
    "run",
    "save",
    "scan",
    "select",
    "send",
    "set",
    "show",
    "skip",
    "split",
    "start",
    "stop",
    "store",
    "submit",
    "summarize",
    "switch",
    "test",
    "track",
    "transform",
    "trigger",
    "update",
    "use",
    "validate",
    "verify",
    "wait",
    "warn",
    "write",
}


@dataclass
class InstructionCount:
    """Instruction budget report for a single skill file."""

    path: Path
    count: int
    threshold_warn: int
    threshold_over: int

    @property
    def status(self) -> str:
        if self.count >= self.threshold_over:
            return "over"
        if self.count >= self.threshold_warn:
            return "warn"
        return "ok"


def _is_frontmatter(line: str, *, state: dict) -> bool:
    if line.startswith("---"):
        state["in_frontmatter"] = not state.get("in_frontmatter", False)
        return True
    return bool(state.get("in_frontmatter", False))


def _first_verb(line: str) -> str | None:
    stripped = line.lstrip("-*+ \t").lstrip("`*")
    word = stripped.split(None, 1)[0] if stripped else ""
    return word.lower().rstrip(":,.")


def is_actionable(line: str) -> bool:
    """Return True when the line carries an actionable instruction."""
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return False
    if _TOOL_CALL.match(line):
        return True
    if _NUMBERED_LIST.match(line):
        return True
    if _ENFORCEMENT.search(line):
        return True
    if _BULLET_LIST.match(line):
        verb = _first_verb(line)
        if verb and verb in _IMPERATIVE_VERBS:
            return True
    return False


def count_instructions(
    path: Path,
    *,
    warn: int = DEFAULT_WARN,
    over: int = DEFAULT_OVER,
) -> InstructionCount:
    """Count actionable instructions in a skill file."""
    content = path.read_text()
    state: dict = {}
    count = 0
    in_code_block = False

    for raw_line in content.splitlines():
        if raw_line.strip().startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue
        if _is_frontmatter(raw_line, state=state):
            continue
        if is_actionable(raw_line):
            count += 1

    return InstructionCount(
        path=path,
        count=count,
        threshold_warn=warn,
        threshold_over=over,
    )


def scan(
    paths: list[Path],
    *,
    warn: int = DEFAULT_WARN,
    over: int = DEFAULT_OVER,
) -> list[InstructionCount]:
    """Count instructions across multiple files."""
    results: list[InstructionCount] = []
    for path in paths:
        if not path.is_file():
            continue
        results.append(count_instructions(path, warn=warn, over=over))
    return results


def find_skill_files(root: Path) -> list[Path]:
    """Return all SKILL.md files under a root directory."""
    return sorted(root.rglob("SKILL.md"))
