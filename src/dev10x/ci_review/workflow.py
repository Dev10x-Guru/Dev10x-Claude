from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from typing import Any

import yaml

from dev10x.core.domain.common.result import Result, err, ok

REVIEW_WORKFLOWS: dict[str, str] = {
    "code-review": "claude-code-review.yml",
    "hygiene": "claude-pr-hygiene.yml",
}

ACTION_PREFIX: str = "anthropics/claude-code-action@"
BUILD_SCRIPT: str = "build-claude-inputs.sh"
STAGE_SCRIPT: str = "stage-trusted.sh"
KEEP_PR_HEAD: str = "--keep-pr-head"

_GUARD_MARKERS: dict[str, str] = {
    "draft": "pull_request.draft",
    "fork": "pull_request.head.repo.fork",
}


@dataclass(frozen=True)
class ReviewJob:
    job_id: str
    build_inputs: tuple[str, ...]
    action_ref: str
    guards: tuple[str, ...]
    keep_pr_head: bool
    paths: tuple[str, ...] = ()
    paths_ignore: tuple[str, ...] = ()


def load_review_job(*, workflow_text: str) -> Result[ReviewJob]:
    try:
        document = yaml.safe_load(workflow_text)
    except yaml.YAMLError as exc:
        return err(f"workflow is not valid YAML: {exc}")
    jobs: dict[str, Any] = (document or {}).get("jobs") or {}
    for job_id, job in jobs.items():
        steps: list[dict[str, Any]] = job.get("steps") or []
        action = next(
            (step for step in steps if str(step.get("uses", "")).startswith(ACTION_PREFIX)),
            None,
        )
        if action is None:
            continue
        return _job_from_steps(
            job_id=job_id,
            job=job,
            steps=steps,
            action=action,
            trigger=_pull_request_trigger(document=document),
        )
    return err(f"workflow has no job running {ACTION_PREFIX.rstrip('@')}")


def _pull_request_trigger(*, document: dict[Any, Any]) -> dict[str, Any]:
    # PyYAML reads the bare `on:` key as the boolean True (YAML 1.1).
    triggers = document.get("on", document.get(True))
    if not isinstance(triggers, dict):
        return {}
    pull_request = triggers.get("pull_request")
    return pull_request if isinstance(pull_request, dict) else {}


def would_trigger(
    *,
    files: list[str],
    paths: tuple[str, ...],
    paths_ignore: tuple[str, ...],
) -> bool:
    if paths:
        return any(_last_match_wins(path=file, patterns=paths) for file in files)
    if paths_ignore:
        return not all(_last_match_wins(path=file, patterns=paths_ignore) for file in files)
    return True


def _last_match_wins(*, path: str, patterns: tuple[str, ...]) -> bool:
    matched = False
    for pattern in patterns:
        negated = pattern.startswith("!")
        if _glob(pattern=pattern.removeprefix("!")).fullmatch(path):
            matched = not negated
    return matched


def _glob(*, pattern: str) -> re.Pattern[str]:
    parts: list[str] = []
    index = 0
    while index < len(pattern):
        if pattern.startswith("**/", index):
            parts.append("(?:.*/)?")
            index += 3
        elif pattern.startswith("**", index):
            parts.append(".*")
            index += 2
        elif pattern[index] == "*":
            parts.append("[^/]*")
            index += 1
        elif pattern[index] == "?":
            parts.append("[^/]")
            index += 1
        elif pattern[index] == "[" and (close := pattern.find("]", index + 2)) != -1:
            parts.append(_char_class(body=pattern[index + 1 : close]))
            index = close + 1
        else:
            parts.append(re.escape(pattern[index]))
            index += 1
    return re.compile("".join(parts))


def _char_class(*, body: str) -> str:
    # GitHub's filter follows minimatch, where a leading `!` negates the class.
    negated = body.startswith("!")
    members = body.removeprefix("!").replace("\\", "\\\\").replace("^", "\\^").replace("[", "\\[")
    return f"[^/{members}]" if negated else f"[{members}]"


def _job_from_steps(
    *,
    job_id: str,
    job: dict[str, Any],
    steps: list[dict[str, Any]],
    action: dict[str, Any],
    trigger: dict[str, Any],
) -> Result[ReviewJob]:
    inputs = next((step for step in steps if step.get("id") == "inputs"), None)
    if inputs is None:
        return err(f"job {job_id!r} has no `inputs` step building the Claude inputs")
    tokens = shlex.split(str(inputs.get("run", "")))
    script_index = next(
        (index for index, token in enumerate(tokens) if token.endswith(BUILD_SCRIPT)),
        None,
    )
    if script_index is None or not tokens[script_index + 1 :]:
        return err(f"job {job_id!r} `inputs` step does not run {BUILD_SCRIPT} with arguments")
    condition = str(job.get("if", ""))
    stage = next((step for step in steps if step.get("id") == "stage"), {})
    stage_lines = [line for line in str(stage.get("run", "")).splitlines() if STAGE_SCRIPT in line]
    return ok(
        ReviewJob(
            job_id=job_id,
            build_inputs=tuple(tokens[script_index + 1 :]),
            action_ref=str(action["uses"]).split("@", 1)[1],
            guards=tuple(name for name, marker in _GUARD_MARKERS.items() if marker in condition),
            keep_pr_head=any(KEEP_PR_HEAD in line for line in stage_lines),
            paths=tuple(str(item) for item in trigger.get("paths") or ()),
            paths_ignore=tuple(str(item) for item in trigger.get("paths-ignore") or ()),
        )
    )
