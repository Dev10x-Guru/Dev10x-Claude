"""Decide what the PostToolUse formatter may touch (GH-1143).

The formatter used to run `ruff format` plus `ruff check --fix` over the
whole file after every Edit. Three things went wrong with that, all
observed in one `tt-e2e` session:

1. **It broke a file by stripping a live import.** A three-Edit revert
   of a `datetime.UTC` rewrite left `from datetime import datetime` while
   line 285 still called `datetime.now(timezone.utc)`. Each Edit+hook
   pair is evaluated in isolation, so after edit 1 the `timezone` name
   genuinely *was* unused and F401 removed it; edit 3 restored the call
   site and nothing restored the import. No individual step was wrong;
   the final state was a `NameError`. Unused-import pruning needs
   whole-file intent, which a post-`Edit` pass never has.

2. **It rewrote code nobody edited.** An unrelated `toggle_enabled`
   method in the same file had its `if/elif` collapsed into an
   unparenthesised mixed `and`/`or` expression; two other untouched
   methods acquired `UTC`, `Generator[Page]` and f-string rewrites.
   Equivalent here, but arriving unreviewed and attributed to whoever
   commits next.

3. **It imposed a line length the project rejects.** `tt-e2e` configures
   Black at 99 and passes its own pre-commit on the original forms, so
   the 88-column reflow enforced no project standard at all.

This module answers the two questions that prevent all three: *may we
format this file?* and *which lines?*
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

_LINE_LENGTH_KEY = "line-length"
_MAX_LINE_LENGTH_KEY = "max-line-length"


@dataclass(frozen=True)
class LineRange:
    """1-indexed inclusive line span an edit touched."""

    start: int
    end: int

    def as_ruff_arg(self) -> str:
        return f"{self.start}-{self.end}"


@dataclass(frozen=True)
class FormatPlan:
    """What the formatter is permitted to do for one tool call."""

    should_format: bool
    line_range: LineRange | None = None
    line_length: int | None = None
    skip_reason: str = ""


def _project_root(path: Path) -> Path | None:
    """Nearest ancestor carrying a project marker."""
    for parent in [path.parent, *path.parent.parents]:
        if (parent / "pyproject.toml").is_file() or (parent / "setup.cfg").is_file():
            return parent
    return None


def _pyproject(root: Path) -> dict:
    config = root / "pyproject.toml"
    if not config.is_file():
        return {}
    try:
        return tomllib.loads(config.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError):
        return {}


def _flake8_max_line_length(root: Path) -> int | None:
    for name in ("setup.cfg", ".flake8", "tox.ini"):
        candidate = root / name
        if not candidate.is_file():
            continue
        try:
            text = candidate.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            key, _, value = line.partition("=")
            if key.strip() == _MAX_LINE_LENGTH_KEY:
                try:
                    return int(value.strip())
                except ValueError:
                    continue
    return None


def resolve_format_policy(path: Path) -> FormatPlan:
    """Decide whether to format `path`, and at what line length.

    A project whose own `[tool.ruff]` config governs the file is formatted
    with ruff's own discovery — that IS the project standard. A project
    that configures a *different* formatter has its line length honoured
    rather than overridden with ruff's 88-column default. A project that
    runs its own pre-commit and has no ruff config is left alone
    entirely: its hooks are the standard, and anything this hook rewrites
    there is net-new unreviewed change.
    """
    root = _project_root(path)
    if root is None:
        return FormatPlan(should_format=True)

    tools = _pyproject(root).get("tool", {})
    if "ruff" in tools:
        return FormatPlan(should_format=True)

    black_length = tools.get("black", {}).get(_LINE_LENGTH_KEY)
    if isinstance(black_length, int):
        return FormatPlan(should_format=True, line_length=black_length)

    flake8_length = _flake8_max_line_length(root)
    if flake8_length is not None:
        return FormatPlan(should_format=True, line_length=flake8_length)

    if (root / ".pre-commit-config.yaml").is_file():
        return FormatPlan(
            should_format=False,
            skip_reason=(
                f"{root.name} runs its own pre-commit and configures no ruff "
                "formatter — deferring to it rather than imposing one"
            ),
        )

    return FormatPlan(should_format=True)


def _span_of(*, content: str, needle: str) -> LineRange | None:
    index = content.find(needle)
    if index == -1:
        return None
    start = content.count("\n", 0, index) + 1
    return LineRange(start=start, end=start + needle.count("\n"))


def edited_range(*, tool_input: dict, content: str) -> LineRange | None:
    """Line span an Edit touched, or None when the whole file is in scope.

    A `Write` authors the entire file, so there is no narrower scope to
    respect. An `Edit` is located by its `new_string`; when that cannot be
    found (the formatter already ran, or the string is ambiguous) the
    caller falls back to whole-file formatting, which is the pre-GH-1143
    behaviour and no worse.
    """
    edits = tool_input.get("edits")
    if isinstance(edits, list) and edits:
        spans = [
            span
            for edit in edits
            if isinstance(edit, dict)
            and (span := _span_of(content=content, needle=str(edit.get("new_string", ""))))
        ]
        if not spans:
            return None
        return LineRange(
            start=min(span.start for span in spans),
            end=max(span.end for span in spans),
        )

    new_string = tool_input.get("new_string")
    if not isinstance(new_string, str) or not new_string:
        return None
    return _span_of(content=content, needle=new_string)


def describe_changes(*, before: str, after: str) -> str:
    """Name what the formatter did, so a silent rewrite becomes visible.

    "PostToolUse hook modified <file> (likely a formatter)" was the only
    signal when an import was deleted out from under a live call site.
    Naming the changed line numbers turns that into something a reader
    can check.
    """
    if before == after:
        return ""
    before_lines = before.splitlines()
    after_lines = after.splitlines()
    changed = [
        number
        for number, (old, new) in enumerate(zip(before_lines, after_lines, strict=False), start=1)
        if old != new
    ]
    delta = len(after_lines) - len(before_lines)
    parts: list[str] = []
    if changed:
        shown = ", ".join(str(n) for n in changed[:5])
        suffix = f" (+{len(changed) - 5} more)" if len(changed) > 5 else ""
        parts.append(f"reformatted line(s) {shown}{suffix}")
    if delta:
        parts.append(f"{'added' if delta > 0 else 'removed'} {abs(delta)} line(s)")
    return "; ".join(parts) or "whitespace only"
