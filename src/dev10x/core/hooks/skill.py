"""Skill and PostToolUse hook logic.

skill_tmpdir: Creates /tmp/Dev10x/<skill-name>/ scratch directory.
skill_metrics: Appends JSONL metric entry; prunes files older than 30 days.
ruff_format: Auto-formats Python files with ruff after Edit/Write.

Each hook is an :class:`~dev10x.hooks.base.AbstractHook` whose ``run()``
Template Method resolves input (passed ``data`` or stdin) before
dispatching to ``handle`` (audit finding A11). The module-level
functions are thin shims so existing entry scripts and CLI wrappers
keep calling a plain function.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from dev10x import subprocess_utils
from dev10x.domain.claude_paths import ClaudeDir
from dev10x.domain.common.skill_name import SkillName
from dev10x.domain.git_context import GitContext
from dev10x.hooks.base import AbstractHook
from dev10x.hooks.format_scope import (
    FormatPlan,
    LineRange,
    describe_changes,
    edited_range,
    resolve_format_policy,
)

# Two sequential ruff calls are possible (a `--range` attempt, then a
# whole-file retry), and `hooks.json` gives this hook 15s total. 6s each
# keeps the worst case at 12s, inside that budget — a hook killed
# mid-format is how a file ends up half-rewritten.
_FORMAT_TIMEOUT_SECONDS = 6


def _emit_hook_message(message: str) -> None:
    """Surface what the formatter did as a hook systemMessage (GH-1143).

    "PostToolUse hook modified <file> (likely a formatter)" was the only
    notice when the hook deleted an import the file still referenced. A
    silent rewrite is the part that makes the breakage hard to attribute.
    """
    print(json.dumps({"systemMessage": message}))


def _get_toplevel() -> str:
    # GH-979 (H11): construct a fresh GitContext per call so each lookup
    # respects the current effective CWD. A module-level singleton would
    # cache the first-call directory permanently across MCP invocations.
    return GitContext().toplevel or "unknown"


class SkillTmpdirHook(AbstractHook):
    """Create /tmp/Dev10x/<skill-name>/ scratch directory (PreToolUse hook)."""

    def handle(self, *, data: dict) -> None:
        skill_name = data.get("tool_input", {}).get("skill") or ""
        if not skill_name:
            return

        parsed = SkillName.try_parse(skill_name)
        if parsed is None:
            return
        safe_name = parsed.safe_path_name
        if safe_name:
            Path(f"/tmp/Dev10x/{safe_name}").mkdir(parents=True, exist_ok=True)


class SkillMetricsHook(AbstractHook):
    """Append skill invocation metric to JSONL file (PostToolUse hook)."""

    def handle(self, *, data: dict) -> None:
        skill_name = data.get("tool_input", {}).get("skill") or ""
        if not skill_name:
            return

        session_id = data.get("session_id") or ""
        if not session_id:
            return

        toplevel = _get_toplevel()
        project_hash = hashlib.md5(toplevel.encode()).hexdigest()

        now = datetime.now(UTC)
        timestamp = now.isoformat()
        date_tag = now.strftime("%Y-%m-%d")

        metrics_dir = ClaudeDir.metrics_dir()
        metrics_dir.mkdir(parents=True, exist_ok=True)

        metrics_file = metrics_dir / f"{project_hash}_{date_tag}.jsonl"
        entry = json.dumps({"skill": skill_name, "session": session_id, "timestamp": timestamp})
        # GH-548: single os.write to an O_APPEND fd so concurrent hook
        # processes never interleave partial JSON lines. TextIOWrapper may
        # split one logical record across multiple syscalls, breaking the
        # POSIX atomic-append guarantee. Mirrors audit/log_reader.append_record.
        line = (entry + "\n").encode("utf-8")
        fd = os.open(str(metrics_file), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, line)
        finally:
            os.close(fd)

        cutoff = now - timedelta(days=30)
        for old_file in metrics_dir.glob("*.jsonl"):
            try:
                if datetime.fromtimestamp(old_file.stat().st_mtime, tz=UTC) < cutoff:
                    old_file.unlink()
            except OSError:
                pass


class RuffFormatHook(AbstractHook):
    """Auto-format Python files with ruff after Edit/Write (PostToolUse hook).

    Scoped to the edited hunk and to projects that want ruff formatting
    (GH-1143). It deliberately does NOT run `ruff check --fix`: that pass
    is what deleted a still-referenced import mid-revert and collapsed
    branch logic in methods the session never touched. Lint fixes need
    whole-file intent and a review; a post-`Edit` pass has neither.
    See `dev10x.hooks.format_scope` for the full argument.
    """

    def handle(self, *, data: dict) -> None:
        tool_input = data.get("tool_input", {})
        file_path = tool_input.get("file_path") or ""
        if not file_path:
            return

        path = Path(file_path)
        if path.suffix != ".py" or not path.is_file():
            sys.exit(0)

        plan = resolve_format_policy(path)
        if not plan.should_format:
            _emit_hook_message(f"ruff-format skipped: {plan.skip_reason}")
            return

        try:
            before = path.read_text(encoding="utf-8")
        except OSError:
            return

        line_range = edited_range(tool_input=tool_input, content=before)
        self._format(path=path, plan=plan, line_range=line_range)

        try:
            after = path.read_text(encoding="utf-8")
        except OSError:
            return

        if summary := describe_changes(before=before, after=after):
            _emit_hook_message(f"ruff-format {path.name}: {summary}")

    def _format(
        self,
        *,
        path: Path,
        plan: FormatPlan,
        line_range: LineRange | None,
    ) -> None:
        """Run `ruff format`, narrowing to the edited hunk when possible.

        `--range` needs ruff >= 0.9. A caller's project may pin an older
        one, so an invocation rejected for an unknown argument retries
        whole-file rather than silently formatting nothing.
        """
        base = ["ruff", "format"]
        if plan.line_length is not None:
            base += ["--line-length", str(plan.line_length)]

        if line_range is not None:
            scoped = subprocess_utils.run(
                [*base, "--range", line_range.as_ruff_arg(), str(path)],
                check=False,
                capture_output=True,
                text=True,
                timeout=_FORMAT_TIMEOUT_SECONDS,
            )
            if scoped.returncode == 0:
                return

        subprocess_utils.run(
            [*base, str(path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=_FORMAT_TIMEOUT_SECONDS,
        )


def skill_tmpdir(data: dict | None = None) -> None:
    """Shim: dispatch to :class:`SkillTmpdirHook`."""
    SkillTmpdirHook().run(data)


def skill_metrics(data: dict | None = None) -> None:
    """Shim: dispatch to :class:`SkillMetricsHook`."""
    SkillMetricsHook().run(data)


def ruff_format(data: dict | None = None) -> None:
    """Shim: dispatch to :class:`RuffFormatHook`."""
    RuffFormatHook().run(data)
