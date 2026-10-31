from __future__ import annotations

import shlex
from typing import Any

_EXCERPT_CHARS: int = 160


def summarize(
    *,
    workflow: str,
    failed_guards: list[str],
    cli_version: str,
    usage: str,
    entries: list[dict[str, Any]],
) -> str:
    guards = ", ".join(failed_guards) if failed_guards else "all pass"
    lines = [
        f"## dev10x ci-review — {workflow}",
        "",
        f"- Guards: {guards}",
        f"- Claude CLI: {cli_version}",
        "",
        usage.rstrip("\n"),
        "",
        "### Outbox (nothing was posted)",
    ]
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        by_kind.setdefault(str(entry.get("kind", "unknown")), []).append(entry)
    if not by_kind:
        lines.append("- (empty)")
    for kind, group in by_kind.items():
        lines.append("")
        lines.append(f"#### {kind} ({len(group)})")
        lines.extend(_describe(entry=entry) for entry in group)
    return "\n".join(lines) + "\n"


def _describe(*, entry: dict[str, Any]) -> str:
    kind = entry.get("kind")
    if kind == "inline_comment":
        line = entry.get("line") or entry.get("startLine")
        return f"- {entry.get('path')}:{line} — {_first_line(text=entry.get('body', ''))}"
    if kind == "post_step":
        argv = entry.get("argv")
        command = f" → `{shlex.join(argv)}`" if argv else ""
        return f"- {entry.get('step')}: {entry.get('branch')}{command}"
    body = entry.get("body_file_content") or entry.get("stdin") or ""
    excerpt = f" — {_excerpt(text=body)}" if body else ""
    return f"- `{shlex.join(entry.get('argv', []))}`{excerpt}"


def _first_line(*, text: str) -> str:
    return text.strip().splitlines()[0] if text.strip() else ""


def _excerpt(*, text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= _EXCERPT_CHARS else flat[: _EXCERPT_CHARS - 1] + "…"


def elide_prompt(*, argv: list[str], prompt: str) -> list[str]:
    lines = prompt.splitlines() or [""]
    size = len(prompt.encode("utf-8"))
    elided = f"{lines[0]} … {lines[-1]} ({size} bytes)"
    return [elided if arg == prompt else arg for arg in argv]
