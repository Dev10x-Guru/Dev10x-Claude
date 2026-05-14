"""Validator: JTBD outcome-focused commit titles.

Ported from validate-commit-jtbd.py.

Intercepts `git commit` commands, extracts the title line, strips
gitmoji + ticket prefix, and blocks if the description starts with
an implementation-focused verb (Add, Update, Remove, etc.).

Skips: fixup!/squash! commits, --amend, merge commits.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from dev10x.domain import HookInput, HookResult
from dev10x.domain.result import ErrorResult, Result, err, ok

_VERB_BASES = [
    "Add",
    "Adjust",
    "Align",
    "Apply",
    "Bump",
    "Change",
    "Clean",
    "Combine",
    "Configure",
    "Consolidate",
    "Delete",
    "Drop",
    "Extend",
    "Extract",
    "Implement",
    "Include",
    "Install",
    "Integrate",
    "Introduce",
    "Merge",
    "Migrate",
    "Modify",
    "Move",
    "Organize",
    "Patch",
    "Pin",
    "Refactor",
    "Register",
    "Remove",
    "Rename",
    "Replace",
    "Revert",
    "Set",
    "Split",
    "Switch",
    "Synchronize",
    "Sync",
    "Update",
    "Wire",
    "Wrap",
]

JTBD_VERBS = (
    "Enable, Allow, Support, Prevent, Ensure, Simplify, Improve, "
    "Optimize, Resolve, Streamline, Protect, Enforce, Automate, "
    "Unblock, Accelerate, Stabilize, Surface, Centralize, "
    "Decouple, Isolate, Harden, Standardize"
)

BLOCK_MSG = (
    "JTBD violation: commit title is implementation-focused.\n"
    "\n"
    "  Title: {title}\n"
    '  Problem: starts with "{verb}" \u2014 describes what changed, '
    "not what it enables.\n"
    "\n"
    "Rewrite to describe the user-facing outcome:\n"
    '  Bad:  "Add retry logic to payment service"\n'
    '  Good: "Enable automatic retry on payment failure"\n'
    "\n"
    "Outcome-focused verbs: {jtbd_verbs}\n"
    "\n"
    "Update the commit message in the temp file and retry."
)

GIT_COMMIT_RE = re.compile(r"\bgit\s+commit\b")
TICKET_RE = re.compile(r"^[A-Z]+-\d+\s+")

BYPASS_GITMOJI: frozenset[str] = frozenset({"🔖", "📝", "🔀"})


def _expand_verbs(bases: list[str]) -> list[str]:
    expanded: list[str] = []
    for v in bases:
        expanded.append(v)
        if v.endswith("e"):
            expanded.append(v + "d")
        elif v.endswith("y"):
            expanded.append(v[:-1] + "ied")
        else:
            expanded.append(v + "ed")
        if v.endswith("e"):
            expanded.append(v[:-1] + "ing")
        else:
            expanded.append(v + "ing")
    return expanded


ALL_VERBS = _expand_verbs(_VERB_BASES)

VERB_RE = re.compile(
    r"^(" + "|".join(re.escape(v) for v in ALL_VERBS) + r")\b",
    re.IGNORECASE,
)


def _extract_title_from_file(path: str) -> str | None:
    try:
        first_line = Path(path).read_text().splitlines()[0]
        return first_line.strip()
    except (FileNotFoundError, IndexError, OSError):
        return None


def _extract_title(command: str) -> str | None:
    match = re.search(r"-F\s+(\S+)", command)
    if match:
        return _extract_title_from_file(match.group(1))

    match = re.search(r"""-m\s+(['"])(.*?)\1""", command)
    if match:
        return match.group(2).splitlines()[0].strip()

    match = re.search(r"-m\s+(\S+)", command)
    if match:
        return match.group(1)

    return None


def _extract_gitmoji(title: str) -> str:
    i = 0
    while i < len(title) and not title[i].isascii():
        i += 1
    return title[:i].strip()


def _strip_prefix(title: str) -> str:
    i = 0
    while i < len(title) and not title[i].isascii():
        i += 1
    desc = title[i:].strip()
    desc = TICKET_RE.sub("", desc).strip()
    return desc


def _check_jtbd(title: str) -> Result[str]:
    desc = _strip_prefix(title)
    match = VERB_RE.match(desc)
    if match:
        return err(match.group(1))
    return ok("")


@dataclass
class CommitJtbdValidator:
    name: str = "commit-jtbd"
    bypass_gitmoji: frozenset[str] = BYPASS_GITMOJI

    def should_run(self, inp: HookInput) -> bool:
        return GIT_COMMIT_RE.search(inp.command) is not None

    def validate(self, inp: HookInput) -> HookResult | None:
        command = inp.command

        if "--amend" in command or "--fixup" in command:
            return None

        title = _extract_title(command)
        if not title:
            return None

        if title.startswith(("fixup!", "squash!", "Merge ")):
            return None

        gitmoji = _extract_gitmoji(title)
        if gitmoji in self.bypass_gitmoji:
            return None

        result = _check_jtbd(title)
        if isinstance(result, ErrorResult):
            return HookResult(
                message=BLOCK_MSG.format(
                    title=title,
                    verb=result.error,
                    jtbd_verbs=JTBD_VERBS,
                )
            )

        return None
