#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Extract Claude Code JSONL session transcript into readable markdown.

Usage:
    extract-session.py <jsonl-path> [output.md]

If output.md is omitted, writes to stdout.
"""

import io
import json
import os
import re
import sys
import tempfile
from datetime import datetime
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


SKIP_TYPES = {"file-history-snapshot", "progress", "system"}

CORRECTION_PATTERNS = re.compile(
    r"(?im)"
    r"^no[,.][ ]|"
    r"^actually[, ]|"
    r"\bi meant\b|"
    r"\bthat'?s wrong\b|"
    r"\bnot what i\b|"
    r"\bdon'?t do that\b|"
    r"\bplease don'?t\b|"
    r"\bi said\b|"
    r"\bwrong\b.{0,20}\binstead\b|"
    r"^use .+ instead\b"
)

MAX_TOOL_RESULT_LEN = 500
MAX_TOOL_INPUT_LEN = 300


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"... [{len(text) - limit} chars truncated]"


def extract_text_from_content(content: list | str) -> str:
    if isinstance(content, str):
        return content
    parts = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "\n".join(parts)


def extract_tool_uses(content: list) -> list[dict]:
    if not isinstance(content, list):
        return []
    tools = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            tool_input = block.get("input", {})
            if isinstance(tool_input, dict):
                summary_parts = []
                for k, v in tool_input.items():
                    v_str = str(v)
                    summary_parts.append(f"{k}={truncate(v_str, MAX_TOOL_INPUT_LEN)}")
                input_summary = ", ".join(summary_parts)
            else:
                input_summary = truncate(str(tool_input), MAX_TOOL_INPUT_LEN)
            tools.append(
                {
                    "name": block.get("name", "unknown"),
                    "id": block.get("id", ""),
                    "input_summary": input_summary,
                }
            )
    return tools


def extract_tool_results(content: list) -> list[dict]:
    if not isinstance(content, list):
        return []
    results = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_result":
            raw = block.get("content", "")
            if isinstance(raw, list):
                text_parts = []
                for item in raw:
                    if isinstance(item, dict):
                        text_parts.append(item.get("text", ""))
                    elif isinstance(item, str):
                        text_parts.append(item)
                raw = "\n".join(text_parts)
            results.append(
                {
                    "tool_use_id": block.get("tool_use_id", ""),
                    "content": truncate(str(raw), MAX_TOOL_RESULT_LEN),
                }
            )
    return results


SKILL_LOAD_PREFIX = "Base directory for this skill:"


def check_correction(text: str) -> bool:
    if text.lstrip().startswith(SKILL_LOAD_PREFIX):
        return False
    return bool(CORRECTION_PATTERNS.search(text))


def format_timestamp(ts: str) -> str:
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.strftime("%H:%M:%S")
    except (ValueError, AttributeError):
        return ts or "?"


def process_jsonl(jsonl_path: str, out: TextIO) -> None:
    path = Path(jsonl_path)
    if not path.exists():
        print(f"Error: {jsonl_path} does not exist", file=sys.stderr)
        sys.exit(1)

    session_id = None
    cwd = None
    git_branch = None
    turn_num = 0

    out.write("# Session Transcript\n\n")

    messages = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                messages.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    for msg in messages:
        if msg.get("sessionId"):
            session_id = msg["sessionId"]
            cwd = msg.get("cwd", "unknown")
            git_branch = msg.get("gitBranch", "")
            break

    first_ts = ""
    for msg in messages:
        if msg.get("timestamp") and msg.get("type") in ("user", "assistant"):
            first_ts = msg["timestamp"]
            break

    out.write(f"- **Session**: `{session_id or 'unknown'}`\n")
    out.write(f"- **Project**: `{cwd or 'unknown'}`\n")
    if git_branch:
        out.write(f"- **Branch**: `{git_branch}`\n")
    out.write(f"- **Started**: {first_ts}\n")
    out.write(f"- **Source**: `{jsonl_path}`\n")
    out.write("\n---\n\n")

    for msg in messages:
        msg_type = msg.get("type", "")
        if msg_type in SKIP_TYPES:
            continue

        ts = format_timestamp(msg.get("timestamp", ""))
        content = msg.get("message", {}).get("content", [])

        if msg_type == "user":
            text = extract_text_from_content(content)
            tool_results = extract_tool_results(content if isinstance(content, list) else [])

            if text.strip():
                turn_num += 1
                correction = check_correction(text.strip())
                marker = " **[CORRECTION]**" if correction else ""
                out.write(f"## Turn {turn_num} [{ts}] USER{marker}\n\n")
                out.write(f"{text.strip()}\n\n")

            if tool_results:
                for tr in tool_results:
                    summary_id = tr["tool_use_id"][:12]
                    out.write(f"<details><summary>Tool result ({summary_id}...)</summary>\n\n")
                    out.write(f"```\n{tr['content']}\n```\n")
                    out.write("</details>\n\n")

        elif msg_type == "assistant":
            text = extract_text_from_content(content)
            tool_uses = extract_tool_uses(content if isinstance(content, list) else [])

            has_output = text.strip() or tool_uses
            if not has_output:
                continue

            turn_num += 1
            out.write(f"## Turn {turn_num} [{ts}] ASSISTANT\n\n")

            if text.strip():
                out.write(f"{text.strip()}\n\n")

            if tool_uses:
                for tu in tool_uses:
                    out.write(f"**Tool: `{tu['name']}`**\n")
                    if tu["input_summary"]:
                        out.write(f"```\n{tu['input_summary']}\n```\n")
                    out.write("\n")

    out.write(f"\n---\n*Extracted {turn_num} turns from `{path.name}`*\n")


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        sys.exit(1)

    jsonl_path = sys.argv[1]
    if len(sys.argv) >= 3:
        output_path = sys.argv[2]
        buf = io.StringIO()
        process_jsonl(jsonl_path=jsonl_path, out=buf)
        _atomic_write_text(output_path, buf.getvalue())
        print(f"Extracted to {output_path}", file=sys.stderr)
    else:
        process_jsonl(jsonl_path=jsonl_path, out=sys.stdout)


if __name__ == "__main__":
    main()
