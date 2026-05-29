"""Skill and PostToolUse hook logic.

skill_tmpdir: Creates /tmp/Dev10x/<skill-name>/ scratch directory.
skill_metrics: Appends JSONL metric entry; prunes files older than 30 days.
ruff_format: Auto-formats Python files with ruff after Edit/Write.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from dev10x import subprocess_utils
from dev10x.domain.claude_paths import ClaudeDir
from dev10x.domain.common.skill_name import SkillName
from dev10x.domain.git_context import GitContext


def _get_toplevel() -> str:
    # GH-979 (H11): construct a fresh GitContext per call so each lookup
    # respects the current effective CWD. A module-level singleton would
    # cache the first-call directory permanently across MCP invocations.
    return GitContext().toplevel or "unknown"


def _load_stdin() -> dict:
    try:
        return json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        return {}


def skill_tmpdir(data: dict | None = None) -> None:
    """Create /tmp/Dev10x/<skill-name>/ scratch directory (PreToolUse hook)."""
    if data is None:
        data = _load_stdin()
    skill_name = data.get("tool_input", {}).get("skill") or ""
    if not skill_name:
        return

    parsed = SkillName.try_parse(skill_name)
    if parsed is None:
        return
    safe_name = parsed.safe_path_name
    if safe_name:
        Path(f"/tmp/Dev10x/{safe_name}").mkdir(parents=True, exist_ok=True)


def skill_metrics(data: dict | None = None) -> None:
    """Append skill invocation metric to JSONL file (PostToolUse hook)."""
    if data is None:
        data = _load_stdin()

    skill_name = data.get("tool_input", {}).get("skill") or ""
    if not skill_name:
        return

    session_id = data.get("session_id") or ""
    if not session_id:
        return

    toplevel = _get_toplevel()
    project_hash = hashlib.md5(toplevel.encode()).hexdigest()

    now = datetime.now(UTC)
    timestamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    date_tag = now.strftime("%Y-%m-%d")

    metrics_dir = ClaudeDir.metrics_dir()
    metrics_dir.mkdir(parents=True, exist_ok=True)

    metrics_file = metrics_dir / f"{project_hash}_{date_tag}.jsonl"
    entry = json.dumps({"skill": skill_name, "session": session_id, "timestamp": timestamp})
    with metrics_file.open("a") as f:
        f.write(entry + "\n")

    cutoff = now - timedelta(days=30)
    for old_file in metrics_dir.glob("*.jsonl"):
        try:
            if datetime.fromtimestamp(old_file.stat().st_mtime, tz=UTC) < cutoff:
                old_file.unlink()
        except OSError:
            pass


def ruff_format(data: dict | None = None) -> None:
    """Auto-format Python files with ruff after Edit/Write (PostToolUse hook)."""
    if data is None:
        data = _load_stdin()

    file_path = data.get("tool_input", {}).get("file_path") or ""
    if not file_path:
        return

    path = Path(file_path)
    if path.suffix != ".py" or not path.is_file():
        sys.exit(0)

    subprocess_utils.run(["ruff", "format", file_path], check=False)
    subprocess_utils.run(["ruff", "check", "--fix", file_path], check=False)
