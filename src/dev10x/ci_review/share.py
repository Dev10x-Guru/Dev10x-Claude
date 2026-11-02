from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from dev10x.ci_review import post_steps
from dev10x.ci_review.outbox import read_entries
from dev10x.ci_review.report import replica_body
from dev10x.ci_review.workflow import REVIEW_WORKFLOWS
from dev10x.core.domain.common.result import ErrorResult, Result, err, ok

REPORT_FILE: str = "report.md"
OUTBOX_FILE: str = "outbox.jsonl"
REPLICA_FILE: str = "replica-comment.md"

_RUN_DIR_NAME = re.compile(r"^\d{8}T\d{6}Z-(?P<workflow>.+)$")
_PR_DIR_NAME = re.compile(r"^pr-(?P<pr>\d+)$")


def share_replica(
    *,
    run_dir: Path,
    repo: str,
    pr: int,
    workflow: str,
    report: str,
    entries: list[dict[str, Any]],
) -> Result[str]:
    body_path = run_dir / REPLICA_FILE
    body_path.write_text(
        replica_body(workflow=workflow, report=report, entries=entries),
        encoding="utf-8",
    )
    return post_steps.post_replica(repo=repo, pr=pr, body_path=body_path)


def post_finished_run(*, run_dir: Path, repo: str, pr: int) -> Result[str]:
    workflow = workflow_of(run_dir=run_dir, pr=pr)
    if isinstance(workflow, ErrorResult):
        return workflow
    report_path = run_dir / REPORT_FILE
    try:
        report = report_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return err(
            f"{run_dir} has no readable {REPORT_FILE}; only a finished model run "
            f"can be posted: {exc}"
        )
    try:
        entries = read_entries(path=run_dir / OUTBOX_FILE)
    except (OSError, ValueError) as exc:
        return err(f"{run_dir / OUTBOX_FILE} is unreadable; the run may have been cut off: {exc}")
    return share_replica(
        run_dir=run_dir,
        repo=repo,
        pr=pr,
        workflow=workflow.value,
        report=report,
        entries=entries,
    )


def workflow_of(*, run_dir: Path, pr: int) -> Result[str]:
    named = _RUN_DIR_NAME.match(run_dir.name)
    if named is None or named.group("workflow") not in REVIEW_WORKFLOWS:
        return err(
            f"{run_dir.name!r} is not a ci-review run directory "
            "(<timestamp>-<code-review|hygiene>)"
        )
    parent = _PR_DIR_NAME.match(run_dir.parent.name)
    if parent is None or int(parent.group("pr")) != pr:
        return err(f"{run_dir} is not a run of PR #{pr}; pass the --pr it was recorded for")
    return ok(named.group("workflow"))
