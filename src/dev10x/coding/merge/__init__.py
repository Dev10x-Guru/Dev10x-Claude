from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from dev10x.coding.skills.merge import fixes_scope, handoff_audit
from dev10x.domain.common.result import ErrorResult, Result, err, ok
from dev10x.subprocess_utils import async_run

_GIT_LOG_TIMEOUT_SECONDS = 30


async def audit_handoff_report(
    *,
    report: Mapping[str, object],
    pr_state: Mapping[str, object],
) -> Result[dict[str, Any]]:
    audit = handoff_audit.audit_handoff_report(report=report, pr_state=pr_state)
    return ok(
        {
            "verdict": audit.verdict,
            "accepted": audit.accepted,
            "reasons": list(audit.reasons),
            "merged_at": audit.merged_at,
            "merged_by": audit.merged_by,
            "summary": audit.summary(),
        }
    )


async def read_commit_messages(
    *,
    base: str,
    head: str = "HEAD",
    repo_dir: str | None = None,
) -> Result[list[str]]:
    result = await async_run(
        args=["git", "log", "--format=%B%x00", f"{base}..{head}"],
        timeout=_GIT_LOG_TIMEOUT_SECONDS,
        cwd=repo_dir,
    )
    if result.returncode != 0:
        return err(f"git log {base}..{head} failed: {result.stderr.strip()}")
    return ok([chunk for chunk in result.stdout.split("\0") if chunk.strip()])


async def reconcile_fixes_links(
    *,
    body: str,
    base: str,
    head: str = "HEAD",
    repo_dir: str | None = None,
    acknowledge: list[int] | None = None,
) -> Result[dict[str, Any]]:
    if repo_dir and not os.path.isabs(repo_dir):
        return err(f"repo_dir must be an absolute path, got {repo_dir!r}")

    messages = await read_commit_messages(base=base, head=head, repo_dir=repo_dir)
    if isinstance(messages, ErrorResult):
        return messages

    verdict = fixes_scope.reconcile_fixes_links(
        body=body,
        commit_messages=messages.value,
        acknowledged=set(acknowledge or ()),
    )
    report: dict[str, Any] = {
        "ok": verdict.ok,
        "linked": list(verdict.linked),
        "delivered": list(verdict.delivered),
        "unbacked": list(verdict.unbacked),
        "commits_read": len(messages.value),
        "summary": verdict.summary(),
    }
    if verdict.unbacked and not messages.value:
        report["hint"] = fixes_scope.empty_range_hint(base=base, head=head, repo_dir=repo_dir)
    return ok(report)
