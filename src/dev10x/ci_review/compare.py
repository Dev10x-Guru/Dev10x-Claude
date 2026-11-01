from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from dev10x.ci_review.post_steps import is_probe
from dev10x.ci_review.process import run_checked
from dev10x.core.domain.common.result import ErrorResult, Result, err, ok

NO_SEVERITY: str = "—"
_SEVERITY = re.compile(r"\b(CRITICAL|WARNING|INFO)\b")
_VERDICT_FLAGS: dict[str, str] = {
    "--request-changes": "CHANGES_REQUESTED",
    "-r": "CHANGES_REQUESTED",
    "--approve": "APPROVED",
    "-a": "APPROVED",
    "--comment": "COMMENTED",
    "-c": "COMMENTED",
}
# `commit_id` on a review comment moves to the newest head when a later push
# repositions it; `original_commit_id` is the commit it was posted against.
_COMMENT_FIELDS: str = (
    ".[] | {path, line: (.line // .original_line), body, created_at,"
    ' commit: (.original_commit_id // .commit_id), bot: (.user.type == "Bot")}'
)
_REVIEW_FIELDS: str = (
    '.[] | {state, body, submitted_at, commit: .commit_id, bot: (.user.type == "Bot")}'
)


@dataclass(frozen=True, order=True)
class Finding:
    path: str
    line: int
    severity: str


@dataclass(frozen=True)
class CiPosted:
    run_id: int
    findings: list[Finding]
    verdicts: list[str]


@dataclass(frozen=True)
class _RunScope:
    head_sha: str
    started: datetime
    ended: datetime


@dataclass(frozen=True)
class ComparisonRow:
    path: str
    line: int
    local: str | None
    ci: str | None


@dataclass(frozen=True)
class Comparison:
    rows: list[ComparisonRow]
    local_verdict: str | None
    ci: CiPosted


def severity_of(*, body: str) -> str:
    found = _SEVERITY.search(body)
    return found.group(1) if found else NO_SEVERITY


def local_findings(*, entries: list[dict[str, Any]]) -> list[Finding]:
    return sorted(
        Finding(
            path=str(entry.get("path")),
            line=int(entry.get("line") or entry.get("startLine") or 0),
            severity=severity_of(body=entry.get("body", "")),
        )
        for entry in entries
        if entry.get("kind") == "inline_comment" and not is_probe(body=entry.get("body", ""))
    )


def local_verdict(*, entries: list[dict[str, Any]]) -> str | None:
    reviews = [
        entry["argv"]
        for entry in entries
        if entry.get("kind") == "gh" and entry.get("argv", [])[:3] == ["gh", "pr", "review"]
    ]
    if not reviews:
        return None
    return next((_VERDICT_FLAGS[arg] for arg in reviews[-1] if arg in _VERDICT_FLAGS), "COMMENTED")


def compare(
    *,
    entries: list[dict[str, Any]],
    ci: CiPosted,
) -> Comparison:
    local = {(item.path, item.line): item.severity for item in local_findings(entries=entries)}
    remote = {(item.path, item.line): item.severity for item in ci.findings}
    rows = [
        ComparisonRow(
            path=path, line=line, local=local.get((path, line)), ci=remote.get((path, line))
        )
        for path, line in sorted(local.keys() | remote.keys())
    ]
    return Comparison(rows=rows, local_verdict=local_verdict(entries=entries), ci=ci)


def fetch_ci_posted(*, repo: str, pr: int, run_id: int) -> Result[CiPosted]:
    run = _api_json(args=["gh", "api", f"repos/{repo}/actions/runs/{run_id}"])
    if isinstance(run, ErrorResult):
        return run
    try:
        scope = _RunScope(
            head_sha=str(run.value["head_sha"]),
            started=_timestamp(value=run.value["run_started_at"]),
            ended=_timestamp(value=run.value["updated_at"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        return err(f"CI run {run_id} has no usable start/end time or head commit: {exc}")
    comments = _api_lines(
        args=["gh", "api", "--paginate", f"repos/{repo}/pulls/{pr}/comments", "--jq"],
        jq=_COMMENT_FIELDS,
    )
    if isinstance(comments, ErrorResult):
        return comments
    reviews = _api_lines(
        args=["gh", "api", "--paginate", f"repos/{repo}/pulls/{pr}/reviews", "--jq"],
        jq=_REVIEW_FIELDS,
    )
    if isinstance(reviews, ErrorResult):
        return reviews
    try:
        findings = sorted(
            Finding(
                path=str(item.get("path")),
                line=int(item.get("line") or 0),
                severity=severity_of(body=item.get("body") or ""),
            )
            for item in comments.value
            if _posted_by_run(item=item, key="created_at", scope=scope)
        )
        verdicts = [
            str(item.get("state"))
            for item in reviews.value
            if _posted_by_run(item=item, key="submitted_at", scope=scope)
        ]
    except (AttributeError, TypeError, ValueError) as exc:
        return err(f"CI run {run_id} posted a comment or review that cannot be read: {exc}")
    return ok(CiPosted(run_id=run_id, findings=findings, verdicts=verdicts))


def _posted_by_run(
    *,
    item: dict[str, Any],
    key: str,
    scope: _RunScope,
) -> bool:
    # The window alone would also claim any other bot (coverage, a second
    # reviewer) that posted while the run was going; the head commit ties a
    # post to what this run reviewed, and the window then excludes earlier
    # runs on the same commit.
    stamp = item.get(key)
    if not item.get("bot") or not stamp or item.get("commit") != scope.head_sha:
        return False
    return scope.started <= _timestamp(value=stamp) <= scope.ended


def _timestamp(*, value: str) -> datetime:
    return datetime.fromisoformat(value)


def _api_json(*, args: list[str]) -> Result[dict[str, Any]]:
    fetched = run_checked(args=args, timeout=60)
    if isinstance(fetched, ErrorResult):
        return fetched
    try:
        return ok(json.loads(fetched.value))
    except json.JSONDecodeError as exc:
        return err(f"`{' '.join(args[:3])}` returned invalid JSON: {exc}")


def _api_lines(*, args: list[str], jq: str) -> Result[list[dict[str, Any]]]:
    fetched = run_checked(args=[*args, jq], timeout=120)
    if isinstance(fetched, ErrorResult):
        return fetched
    try:
        return ok([json.loads(line) for line in fetched.value.splitlines() if line.strip()])
    except json.JSONDecodeError as exc:
        return err(f"`{' '.join(args[:4])}` returned invalid JSON: {exc}")
