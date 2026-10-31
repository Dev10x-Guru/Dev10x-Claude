from __future__ import annotations

import re
from dataclasses import dataclass, field

OPTION_LINE = re.compile(r"^\s*(?:[❯>]\s*)?(\d{1,2})\.\s+(\S.*?)\s*$")
CURSOR = re.compile(r"^\s*[❯>]")
RULE_LINE = re.compile(r"^\s*[─╌━-]{8,}\s*$")
DIALOG_EDGE = re.compile(r"^\s*[─━]{8,}\s*$")
MAX_CONTEXT_LINES = 40
GUTTER = re.compile(r"^\s*│\s?")
INPUT_LINE = re.compile(r"^\s*[❯>](?!\s*\d{1,2}\.)")
HINT_LINE = re.compile(r"^\s*(?:⏵|\?\s+for shortcuts\b|esc to interrupt\b)")
ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;:?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")


def strip_ansi(text: str) -> str:
    return ANSI_ESCAPE.sub("", text)


@dataclass(frozen=True)
class PromptOption:
    key: str
    label: str
    detail: str = ""
    selected: bool = False


@dataclass(frozen=True)
class Prompt:
    question: str
    options: list[PromptOption] = field(default_factory=list)
    context: list[str] = field(default_factory=list)


def _runs(*, lines: list[str]) -> list[list[int]]:
    runs: list[list[int]] = []
    expected = 0
    for index, line in enumerate(lines):
        match = OPTION_LINE.match(line)
        if not match:
            continue
        number = int(match.group(1))
        if number == 1:
            runs.append([index])
            expected = 2
        elif runs and number == expected:
            runs[-1].append(index)
            expected += 1
    return [run for run in runs if len(run) >= 2]


def _question_at(*, lines: list[str], first: int) -> int | None:
    for index in range(first - 1, -1, -1):
        if lines[index].strip() and not RULE_LINE.match(lines[index]):
            return index
    return None


def _context(*, lines: list[str], question: int) -> list[str]:
    floor = max(0, question - MAX_CONTEXT_LINES)
    edge = next(
        (index for index in range(question - 1, floor - 1, -1) if DIALOG_EDGE.match(lines[index])),
        None,
    )
    if edge is None:
        return []
    block = [line.rstrip() for line in lines[edge + 1 : question]]
    while block and not block[0].strip():
        block.pop(0)
    while block and not block[-1].strip():
        block.pop()
    return block


def _detail(*, lines: list[str], start: int, stop: int) -> str:
    parts = []
    for line in lines[start + 1 : stop]:
        text = line.strip()
        if not text or RULE_LINE.match(line):
            break
        parts.append(text)
    return " ".join(parts)


def parse_prompt(*, pane_text: str) -> Prompt | None:
    lines = pane_text.splitlines()
    runs = _runs(lines=lines)
    if not runs:
        return None
    run = runs[-1]
    options = []
    for position, index in enumerate(run):
        match = OPTION_LINE.match(lines[index])
        assert match is not None
        stop = run[position + 1] if position + 1 < len(run) else len(lines)
        options.append(
            PromptOption(
                key=match.group(1),
                label=match.group(2),
                detail=_detail(lines=lines, start=index, stop=stop),
                selected=bool(CURSOR.match(lines[index])),
            )
        )
    question = _question_at(lines=lines, first=run[0])
    if question is None:
        return Prompt(question="", options=options)
    return Prompt(
        question=GUTTER.sub("", lines[question]).strip(),
        options=options,
        context=_context(lines=lines, question=question),
    )


def _status_rows(*, lines: list[str]) -> list[int]:
    rules = [index for index, line in enumerate(lines) if RULE_LINE.match(line)]
    if len(rules) < 2 or not INPUT_LINE.match(lines[rules[-2] + 1]):
        return []
    return [
        index
        for index in range(rules[-1] + 1, len(lines))
        if lines[index].strip() and not HINT_LINE.match(lines[index])
    ]


def parse_status_line(*, pane_text: str) -> str:
    plain = strip_ansi(pane_text).splitlines()
    return "\n".join(plain[index].strip() for index in _status_rows(lines=plain))


def parse_status_line_ansi(*, pane_ansi: str) -> str:
    raw = pane_ansi.splitlines()
    plain = [strip_ansi(line) for line in raw]
    return "\n".join(raw[index].strip() for index in _status_rows(lines=plain))


def find_option(*, prompt: Prompt | None, key: str, label: str) -> PromptOption | None:
    if prompt is None:
        return None
    return next(
        (option for option in prompt.options if option.key == key and option.label == label),
        None,
    )
