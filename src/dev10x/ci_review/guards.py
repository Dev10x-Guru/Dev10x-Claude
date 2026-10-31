from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from dev10x.ci_review.process import run_checked
from dev10x.core.domain.common.result import ErrorResult, Result, err, ok

PR_FIELDS: str = "number,state,isDraft,isCrossRepository,baseRefName,headRefOid,title"


def fetch_pr(*, repo: str, number: int) -> Result[dict[str, Any]]:
    result = run_checked(
        args=["gh", "pr", "view", str(number), "--repo", repo, "--json", PR_FIELDS],
        timeout=60,
    )
    if isinstance(result, ErrorResult):
        return result
    try:
        return ok(json.loads(result.value))
    except json.JSONDecodeError as exc:
        return err(f"gh pr view returned invalid JSON: {exc}")


def evaluate_guards(*, pr: dict[str, Any], guards: Iterable[str]) -> list[str]:
    active = set(guards)
    failed: list[str] = []
    if "draft" in active and pr.get("isDraft"):
        failed.append("draft")
    if "fork" in active and pr.get("isCrossRepository"):
        failed.append("fork")
    state = pr.get("state")
    if state != "OPEN":
        failed.append(f"not-open:{state}")
    return failed
