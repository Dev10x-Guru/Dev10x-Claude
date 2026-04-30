"""Skill audit MCP tool implementations.

Wraps the skill-audit 3-script pipeline as MCP tools so the
skill-audit skill can process sessions without Bash allow-rules.

Also exposes hook-audit log discovery tools so agents can
inspect the audit-wrap JSONL stream without hunting for the
log directory with raw shell commands (GH-29).
"""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import Any

from dev10x.subprocess_utils import async_run_script

_DEFAULT_HOOK_AUDIT_DIR = "/tmp/Dev10x/hook-audit"


def _resolve_audit_dir() -> Path:
    return Path(os.environ.get("DEV10X_HOOK_AUDIT_DIR", _DEFAULT_HOOK_AUDIT_DIR))


def _today_log_path(audit_dir: Path) -> Path:
    return audit_dir / f"hooks-{date.today().isoformat()}.jsonl"


async def extract_session(
    *,
    jsonl_path: str,
    output_path: str | None = None,
) -> dict[str, Any]:
    args = [jsonl_path]
    if output_path:
        args.append(output_path)

    result = await async_run_script(
        "skills/skill-audit/scripts/extract-session.py",
        *args,
    )

    if result.returncode != 0:
        return {"error": result.stderr.strip()}

    return {"success": True, "output": result.stdout.strip()}


async def analyze_actions(
    *,
    transcript_path: str,
    output_path: str | None = None,
) -> dict[str, Any]:
    args = [transcript_path]
    if output_path:
        args.append(output_path)

    result = await async_run_script(
        "skills/skill-audit/scripts/analyze-actions.py",
        *args,
    )

    if result.returncode != 0:
        return {"error": result.stderr.strip()}

    return {"success": True, "output": result.stdout.strip()}


async def analyze_permissions(
    *,
    transcript_path: str,
    settings_path: str | None = None,
    output_path: str | None = None,
) -> dict[str, Any]:
    args = [transcript_path]
    if settings_path:
        args.append(settings_path)
    if output_path:
        args.append(output_path)

    result = await async_run_script(
        "skills/skill-audit/scripts/analyze-permissions.py",
        *args,
    )

    if result.returncode != 0:
        return {"error": result.stderr.strip()}

    return {"success": True, "output": result.stdout.strip()}


async def hook_log_path() -> dict[str, Any]:
    audit_dir = _resolve_audit_dir()
    today_log = _today_log_path(audit_dir)

    available = []
    if audit_dir.exists():
        available = sorted(p.name for p in audit_dir.glob("hooks-*.jsonl"))

    return {
        "audit_dir": str(audit_dir),
        "today_log": str(today_log),
        "today_log_exists": today_log.exists(),
        "audit_dir_exists": audit_dir.exists(),
        "available_logs": available,
        "audit_disabled": os.environ.get("DEV10X_HOOK_AUDIT", "1").lower()
        in {"0", "false", "no", "off"},
    }


async def hook_recent(
    *,
    limit: int = 50,
    hook_name: str | None = None,
    span_id: str | None = None,
    log_path: str | None = None,
) -> dict[str, Any]:
    target = Path(log_path) if log_path else _today_log_path(_resolve_audit_dir())

    if not target.exists():
        return {
            "log_path": str(target),
            "exists": False,
            "records": [],
            "error": f"audit log not found: {target}",
        }

    records: list[dict[str, Any]] = []
    with target.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if hook_name and rec.get("hook") != hook_name:
                continue
            if span_id and rec.get("span_id") != span_id:
                continue
            records.append(rec)

    if limit > 0:
        records = records[-limit:]

    return {
        "log_path": str(target),
        "exists": True,
        "count": len(records),
        "records": records,
    }
