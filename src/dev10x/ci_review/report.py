from __future__ import annotations

import re
import shlex
from typing import Any

from dev10x.ci_review.compare import NO_SEVERITY, Comparison

_EXCERPT_CHARS: int = 160
_ABSENT: str = "absent"
LOCAL_REPLICA_HEADER: str = "Local CI replica"
LOCAL_REPLICA_MARKER: str = "<!-- dev10x-local-ci-review -->"
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_ROUND = re.compile(r"\(Round (\d+|N)\)", re.IGNORECASE)


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


def render_comparison(*, comparison: Comparison) -> str:
    lines = [
        f"### Compared with CI run {comparison.ci.run_id}",
        "",
        "| Finding | Local | CI |",
        "| --- | --- | --- |",
    ]
    lines.extend(
        f"| `{row.path}:{row.line}` | {row.local or _ABSENT} | {row.ci or _ABSENT} |"
        for row in comparison.rows
    )
    if not comparison.rows:
        lines.append("| (no inline findings on either side) | | |")
    matched = sum(1 for row in comparison.rows if row.local and row.ci)
    local_only = sum(1 for row in comparison.rows if row.local and not row.ci)
    ci_only = sum(1 for row in comparison.rows if row.ci and not row.local)
    ci_verdicts = ", ".join(comparison.ci.verdicts) or NO_SEVERITY
    lines.extend(
        [
            "",
            f"- Matched: {matched} · local only: {local_only} · CI only: {ci_only}",
            f"- Verdict: local {comparison.local_verdict or NO_SEVERITY} · CI {ci_verdicts}",
        ]
    )
    return "\n".join(lines) + "\n"


def replica_body(*, workflow: str, report: str, entries: list[dict[str, Any]]) -> str:
    summaries = [text for entry in entries if (text := _summary_text(entry=entry))]
    lines = [
        f"## {LOCAL_REPLICA_HEADER} — {workflow}",
        "",
        f"_Posted by `dev10x ci-review --post` from a local replay of the Claude CI {workflow}."
        " This is not a CI review round; CI never saw it._",
        "",
        _neutralize(text=report).rstrip("\n"),
    ]
    for text in summaries:
        lines.extend(
            [
                "",
                "<details><summary>Summary the replay would have posted</summary>",
                "",
                _neutralize(text=text).strip("\n"),
                "",
                "</details>",
            ]
        )
    lines.extend(["", LOCAL_REPLICA_MARKER])
    return "\n".join(lines) + "\n"


def _summary_text(*, entry: dict[str, Any]) -> str:
    if entry.get("kind") == "gh" and entry.get("argv", [])[:3] == ["gh", "pr", "review"]:
        return str(entry.get("body_file_content") or entry.get("stdin") or "")
    if entry.get("kind") == "post_step":
        return str(entry.get("body") or "")
    return ""


def _neutralize(*, text: str) -> str:
    # CI finds its own comments by HTML marker and numbers rounds from
    # "(Round N)" headings; the replica must match neither.
    stripped = _HTML_COMMENT.sub("", text)
    return _ROUND.sub(r"(replica of round \1)", stripped)


def elide_prompt(*, argv: list[str], prompt: str) -> list[str]:
    lines = prompt.splitlines() or [""]
    size = len(prompt.encode("utf-8"))
    elided = f"{lines[0]} … {lines[-1]} ({size} bytes)"
    return [elided if arg == prompt else arg for arg in argv]
