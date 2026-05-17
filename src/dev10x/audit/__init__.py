"""Skill audit MCP tool implementations.

Wraps the skill-audit 3-script pipeline as MCP tools so the
skill-audit skill can process sessions without Bash allow-rules.

Also exposes hook-audit log discovery tools so agents can
inspect the audit-wrap JSONL stream without hunting for the
log directory with raw shell commands (GH-29).

JSONL parsing delegates to `dev10x.audit.log_reader.iter_records`
(GH-143) so there is one parser for hook audit logs.
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Any

from dev10x.audit.log_reader import iter_records, prune, summarize
from dev10x.domain.claude_paths import ClaudeDir
from dev10x.domain.common.result import Result, err, ok
from dev10x.subprocess_utils import async_run_script

__all__ = [
    "iter_records",
    "summarize",
    "prune",
    "extract_session",
    "analyze_actions",
    "analyze_permissions",
    "hook_log_path",
    "hook_recent",
]

_DEFAULT_HOOK_AUDIT_DIR = "/tmp/Dev10x/hook-audit"


def _resolve_audit_dir() -> Path:
    return Path(os.environ.get("DEV10X_HOOK_AUDIT_DIR", _DEFAULT_HOOK_AUDIT_DIR))


def _today_log_path(audit_dir: Path) -> Path:
    return audit_dir / f"hooks-{date.today().isoformat()}.jsonl"


async def extract_session(
    *,
    jsonl_path: str,
    output_path: str | None = None,
) -> Result[dict[str, Any]]:
    args = [jsonl_path]
    if output_path:
        args.append(output_path)

    result = await async_run_script(
        "skills/skill-audit/scripts/extract-session.py",
        *args,
    )

    if result.returncode != 0:
        return err(result.stderr.strip())

    return ok({"success": True, "output": result.stdout.strip()})


async def analyze_actions(
    *,
    transcript_path: str,
    output_path: str | None = None,
) -> Result[dict[str, Any]]:
    args = [transcript_path]
    if output_path:
        args.append(output_path)

    result = await async_run_script(
        "skills/skill-audit/scripts/analyze-actions.py",
        *args,
    )

    if result.returncode != 0:
        return err(result.stderr.strip())

    return ok({"success": True, "output": result.stdout.strip()})


async def analyze_permissions(
    *,
    transcript_path: str,
    settings_path: str | None = None,
    output_path: str | None = None,
) -> Result[dict[str, Any]]:
    """Run permission-friction analysis in-process (GH-142).

    Previously shelled out to skills/skill-audit/scripts/analyze-permissions.py;
    now calls dev10x.audit.analyze.build_audit_report() directly so MCP
    callers consume structured data without a subprocess hop.
    """

    from dev10x.audit.analyze import build_audit_report

    transcript_file = Path(transcript_path)
    if not transcript_file.exists():
        return err(f"transcript not found: {transcript_path}")

    settings_file = Path(settings_path) if settings_path else ClaudeDir.settings_local_json()

    try:
        report = build_audit_report(
            transcript=transcript_file.read_text(),
            settings_path=settings_file,
        )
    except Exception as exc:  # noqa: BLE001 — surface any analysis failure to caller
        return err(f"analyze_permissions failed: {exc}")

    output = report.render_markdown()

    if output_path:
        Path(output_path).write_text(output)
        return ok({"success": True, "output": f"Phase 4 output written to {output_path}"})

    return ok({"success": True, "output": output.strip()})


async def hook_log_path() -> Result[dict[str, Any]]:
    audit_dir = _resolve_audit_dir()
    today_log = _today_log_path(audit_dir)

    available = []
    if audit_dir.exists():
        available = sorted(p.name for p in audit_dir.glob("hooks-*.jsonl"))

    return ok(
        {
            "audit_dir": str(audit_dir),
            "today_log": str(today_log),
            "today_log_exists": today_log.exists(),
            "audit_dir_exists": audit_dir.exists(),
            "available_logs": available,
            "audit_disabled": os.environ.get("DEV10X_HOOK_AUDIT", "1").lower()
            in {"0", "false", "no", "off"},
        }
    )


async def hook_recent(
    *,
    limit: int = 50,
    hook_name: str | None = None,
    span_id: str | None = None,
    log_path: str | None = None,
) -> Result[dict[str, Any]]:
    audit_dir = _resolve_audit_dir()
    target = Path(log_path) if log_path else _today_log_path(audit_dir)

    if not target.exists():
        return err(
            f"audit log not found: {target}",
            log_path=str(target),
            exists=False,
            records=[],
        )

    if log_path:
        records = iter_records(paths=[target])
    else:
        records = iter_records(base_dir=audit_dir)

    if hook_name:
        records = [rec for rec in records if rec.get("hook") == hook_name]
    if span_id:
        records = [rec for rec in records if rec.get("span_id") == span_id]

    if limit > 0:
        records = records[-limit:]

    return ok(
        {
            "log_path": str(target),
            "exists": True,
            "count": len(records),
            "records": records,
        }
    )
