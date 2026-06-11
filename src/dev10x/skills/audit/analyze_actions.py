#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Deterministic Phase 1 action inventory for skill-audit.

Parses a normalized markdown transcript (produced by extract-session.py)
and emits:
- A table of every tool call, skill invocation, and agent dispatch
- Action type classification
- User correction markers
- Summary counts

Usage:
    analyze-actions.py <transcript.md> [output.md]

If output.md is omitted, writes to stdout.
"""

import io
import os
import re
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TextIO


def _atomic_write_text(output_path: str, content: str) -> None:
    """Crash-safe write via mkstemp + fsync + os.replace (GH-562).

    This standalone uv-script cannot import
    ``dev10x.domain.file_locks.atomic_write_text``, so the same
    temp-then-rename pattern is inlined here.
    """
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), suffix=".tmp")
    try:
        os.write(fd, content.encode("utf-8"))
        os.fsync(fd)
        os.close(fd)
        os.replace(tmp, str(target))
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


TURN_RE = re.compile(
    r"^## Turn (\d+) \[([^\]]+)\] (USER|ASSISTANT)(.*)",
    re.MULTILINE,
)

TOOL_RE = re.compile(r"^\*\*Tool: `([^`]+)`\*\*", re.MULTILINE)

TOOL_INPUT_BLOCK_RE = re.compile(
    r"^\*\*Tool: `([^`]+)`\*\*\n```\n(.*?)```",
    re.MULTILINE | re.DOTALL,
)

SKILL_INVOKE_RE = re.compile(
    r"skill=(['\"]?)([^'\"(),\s]+)\1",
)

AGENT_DISPATCH_RE = re.compile(
    r'description=(["\'])(.*?)\1',
)

AGENT_TYPE_RE = re.compile(
    r'subagent_type=(["\']?)([^"\'(),\s]+)\1',
)

ACTION_KEYWORDS: dict[str, list[str]] = {
    "Git": [
        "git commit",
        "git push",
        "git rebase",
        "git checkout",
        "git merge",
        "git branch",
        "git fetch",
        "git pull",
        "git stash",
        "git cherry-pick",
        "git reset",
        "git log",
        "git diff",
        "git add",
        "git tag",
    ],
    "PR": [
        "gh pr ",
        "pr create",
        "pr view",
        "pr merge",
        "pr ready",
        "pr checks",
        "pr review",
        "pr comment",
        "pr diff",
    ],
    "Issue": ["gh issue", "issue view", "issue create", "issue comment"],
    "Test": ["pytest", "uv run pytest", "python -m pytest", "coverage"],
    "Lint": ["ruff", "black", "isort", "mypy", "flake8"],
    "CodeChange": [],
    "Config": ["settings.json", "settings.local.json", "chmod", "uv.lock"],
}


@dataclass
class Turn:
    number: int
    time: str
    role: str
    is_correction: bool
    text: str
    tool_calls: list["ToolCall"] = field(default_factory=list)


@dataclass
class ToolCall:
    tool_name: str
    input_summary: str
    action_type: str = ""
    description: str = ""
    skill_invoked: str = ""


@dataclass
class ActionRow:
    index: int
    turn: int
    time: str
    role: str
    action_type: str
    description: str
    skill_invoked: str
    is_correction: bool = False


def parse_turns(text: str) -> list[Turn]:
    matches = list(TURN_RE.finditer(text))
    turns: list[Turn] = []

    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()

        is_correction = "**[CORRECTION]**" in m.group(4)
        turn = Turn(
            number=int(m.group(1)),
            time=m.group(2),
            role=m.group(3),
            is_correction=is_correction,
            text=body,
        )

        for tool_match in TOOL_INPUT_BLOCK_RE.finditer(body):
            tc = ToolCall(
                tool_name=tool_match.group(1),
                input_summary=tool_match.group(2).strip(),
            )
            turn.tool_calls.append(tc)

        bare_tools = set()
        for tool_match in TOOL_RE.finditer(body):
            bare_tools.add(tool_match.group(1))
        named_tools = {tc.tool_name for tc in turn.tool_calls}
        for name in bare_tools - named_tools:
            turn.tool_calls.append(ToolCall(tool_name=name, input_summary=""))

        turns.append(turn)

    return turns


ACTION_TYPE_BY_TOOL: dict[str, str] = {
    "Skill": "Skill",
    "Agent": "Agent",
    "TaskCreate": "Task",
    "TaskUpdate": "Task",
    "TaskList": "Task",
    "TaskGet": "Task",
    "AskUserQuestion": "Decision",
    "Write": "CodeChange",
    "Edit": "CodeChange",
    "Read": "Read",
    "Glob": "Search",
    "Grep": "Search",
    "WebFetch": "Web",
    "WebSearch": "Web",
}


def _classify_bash(input_summary: str) -> str:
    combined = f"Bash {input_summary}".lower()
    for action_type, keywords in ACTION_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in combined:
                return action_type
    return "Other"


def classify_action(tool_name: str, input_summary: str) -> str:
    mapped = ACTION_TYPE_BY_TOOL.get(tool_name)
    if mapped is not None:
        return mapped
    if tool_name == "Bash":
        return _classify_bash(input_summary=input_summary)
    return "Other"


def describe_tool_call(tc: ToolCall) -> str:
    if tc.tool_name == "Skill":
        match = SKILL_INVOKE_RE.search(tc.input_summary)
        if match:
            tc.skill_invoked = match.group(2)
            return f"Invoke {tc.skill_invoked}"
        return f"Skill call: {tc.input_summary[:60]}"

    if tc.tool_name == "Agent":
        desc_match = AGENT_DISPATCH_RE.search(tc.input_summary)
        type_match = AGENT_TYPE_RE.search(tc.input_summary)
        parts = ["Dispatch"]
        if type_match:
            parts.append(f"({type_match.group(2)})")
        if desc_match:
            parts.append(f": {desc_match.group(2)[:50]}")
        tc.skill_invoked = f"Agent({type_match.group(2) if type_match else 'general-purpose'})"
        return " ".join(parts)

    if tc.tool_name == "Bash":
        cmd = tc.input_summary
        first_line = cmd.split("\n")[0][:80] if cmd else ""
        return first_line or "bash command"

    if tc.tool_name in ("Write", "Edit"):
        path_match = re.search(r"file_path=([^\s,]+)", tc.input_summary)
        if path_match:
            return f"{tc.tool_name}: {path_match.group(1)[:60]}"

    if tc.tool_name == "Read":
        path_match = re.search(r"file_path=([^\s,]+)", tc.input_summary)
        if path_match:
            return f"Read: {path_match.group(1)[:60]}"

    return f"{tc.tool_name}: {tc.input_summary[:60]}"


def build_action_rows(turns: list[Turn]) -> list[ActionRow]:
    rows: list[ActionRow] = []
    idx = 0

    for turn in turns:
        if turn.role == "USER" and turn.is_correction:
            idx += 1
            rows.append(
                ActionRow(
                    index=idx,
                    turn=turn.number,
                    time=turn.time,
                    role="USER",
                    action_type="Correction",
                    description=turn.text[:80].replace("\n", " "),
                    skill_invoked="",
                    is_correction=True,
                )
            )
            continue

        for tc in turn.tool_calls:
            tc.action_type = classify_action(
                tool_name=tc.tool_name,
                input_summary=tc.input_summary,
            )
            tc.description = describe_tool_call(tc)
            idx += 1
            rows.append(
                ActionRow(
                    index=idx,
                    turn=turn.number,
                    time=turn.time,
                    role=turn.role[:4],
                    action_type=tc.action_type,
                    description=tc.description,
                    skill_invoked=tc.skill_invoked,
                )
            )

    return rows


def write_output(rows: list[ActionRow], out: TextIO) -> None:
    out.write("# Phase 1: Action Inventory\n\n")

    out.write("| # | Turn | Time | Role | Action Type | Description | Skill Invoked |\n")
    out.write("|---|------|------|------|-------------|-------------|---------------|\n")

    for r in rows:
        desc = r.description.replace("|", "\\|")
        skill = r.skill_invoked.replace("|", "\\|")
        marker = " **[CORRECTION]**" if r.is_correction else ""
        out.write(
            f"| {r.index} | {r.turn} | {r.time} | {r.role}{marker} "
            f"| {r.action_type} | {desc} | {skill} |\n"
        )

    out.write("\n---\n\n")

    type_counts: dict[str, int] = {}
    skill_counts: dict[str, int] = {}
    correction_count = 0

    for r in rows:
        type_counts[r.action_type] = type_counts.get(r.action_type, 0) + 1
        if r.skill_invoked:
            skill_counts[r.skill_invoked] = skill_counts.get(r.skill_invoked, 0) + 1
        if r.is_correction:
            correction_count += 1

    out.write("## Summary\n\n")
    out.write(f"**Total actions:** {len(rows)}\n\n")

    out.write("**By type:**\n")
    for t, c in sorted(type_counts.items(), key=lambda x: -x[1]):
        out.write(f"- {t}: {c}\n")

    out.write("\n**Skills invoked:**\n")
    if skill_counts:
        for s, c in sorted(skill_counts.items(), key=lambda x: -x[1]):
            out.write(f"- {s}: {c}\n")
    else:
        out.write("- (none)\n")

    out.write(f"\n**User corrections detected:** {correction_count}\n")


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        sys.exit(1)

    transcript_path = sys.argv[1]
    transcript = Path(transcript_path).read_text()
    turns = parse_turns(text=transcript)
    rows = build_action_rows(turns=turns)

    if len(sys.argv) >= 3:
        output_path = sys.argv[2]
        buf = io.StringIO()
        write_output(rows=rows, out=buf)
        _atomic_write_text(output_path, buf.getvalue())
        print(f"Phase 1 output written to {output_path}", file=sys.stderr)
    else:
        write_output(rows=rows, out=sys.stdout)


if __name__ == "__main__":
    main()
