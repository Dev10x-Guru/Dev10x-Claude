from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from dev10x.ci_review.outbox import append_entry, read_entries
from dev10x.ci_review.workspace import HYGIENE_MARKER
from dev10x.core.domain.common.result import Result, err, ok

PROBE_STEP: str = "Delete probe inline comments"
DRAFT_STEP: str = "Convert to draft when the review left findings"
HYGIENE_STEP: str = "Post hygiene comment"
HYGIENE_BODY: str = ".claude-ci/hygiene-comment.md"

# Same expression as the "Delete probe inline comments" step's jq `test`;
# tests/ci_review/test_post_steps.py pins it to the workflow text.
PROBE_PATTERN: str = (
    r"^\s*(test( comment)?|testing( (if|whether) (i can( comment| post)?( here| on this"
    r" line)?|this works|the (inline )?comment( tool)?( works)?))?|this is a test( comment)?"
    r"|can i (post|comment)( here)?|does this work|checking (if|whether) (i can|this works"
    r"|the (inline )?comment( tool)? works))[.!?]?\s*$"
)
_PROBE = re.compile(PROBE_PATTERN, re.IGNORECASE)
_PASS_LINE = re.compile(r"^✅ PR hygiene checks pass\.", re.MULTILINE)


def is_probe(*, body: str) -> bool:
    return len(body) < 100 and "**" not in body and _PROBE.search(body) is not None


def code_review_post_steps(*, outbox: Path, repo: str, pr: int) -> list[dict[str, Any]]:
    inline = [
        entry for entry in read_entries(path=outbox) if entry.get("kind") == "inline_comment"
    ]
    recorded: list[dict[str, Any]] = []
    probes = [entry for entry in inline if is_probe(body=entry.get("body", ""))]
    for probe in probes:
        recorded.append(
            _record(
                outbox=outbox,
                step=PROBE_STEP,
                branch="delete",
                argv=[
                    "gh",
                    "api",
                    "-X",
                    "DELETE",
                    f"repos/{repo}/pulls/comments/{probe['comment_id']}",
                ],
            )
        )
    findings = len(inline) - len(probes)
    if findings > 0:
        recorded.append(
            _record(
                outbox=outbox,
                step=DRAFT_STEP,
                branch="draft",
                argv=["gh", "pr", "ready", str(pr), "--undo", "--repo", repo],
                findings=findings,
            )
        )
    else:
        recorded.append(_record(outbox=outbox, step=DRAFT_STEP, branch="stay-ready", findings=0))
    return recorded


def hygiene_post_step(
    *,
    checkout: Path,
    outbox: Path,
    repo: str,
    pr: int,
    prior_comment_id: int | None,
) -> Result[dict[str, Any]]:
    body_path = checkout / HYGIENE_BODY
    if body_path.is_symlink() or not body_path.is_file() or body_path.stat().st_size == 0:
        _record(outbox=outbox, step=HYGIENE_STEP, branch="error")
        return err(
            f"Hygiene review wrote no comment: the model finished without writing {HYGIENE_BODY}."
        )
    body = body_path.read_text(encoding="utf-8") + f"\n{HYGIENE_MARKER}\n"
    if prior_comment_id is not None:
        entry = _record(
            outbox=outbox,
            step=HYGIENE_STEP,
            branch="update",
            argv=[
                "gh",
                "api",
                "-X",
                "PATCH",
                f"repos/{repo}/issues/comments/{prior_comment_id}",
                "-F",
                f"body=@{HYGIENE_BODY}",
            ],
            body=body,
        )
    elif _PASS_LINE.search(body):
        entry = _record(outbox=outbox, step=HYGIENE_STEP, branch="nothing-to-post", body=body)
    else:
        entry = _record(
            outbox=outbox,
            step=HYGIENE_STEP,
            branch="comment",
            argv=["gh", "pr", "comment", str(pr), "--repo", repo, "--body-file", HYGIENE_BODY],
            body=body,
        )
    return ok(entry)


def _record(*, outbox: Path, step: str, branch: str, **fields: Any) -> dict[str, Any]:
    entry = {"kind": "post_step", "step": step, "branch": branch, **fields}
    append_entry(path=outbox, entry=entry)
    return entry
