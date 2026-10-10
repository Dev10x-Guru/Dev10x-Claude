"""Detection and pre-flight capability (ADR-0027).

Dependencies are reached through ``_gateway.<name>`` (ADR-0027 D2), so a
test patches ``dev10x.github._gateway.<name>`` and intercepts every caller.
"""

from __future__ import annotations

from typing import Any

from dev10x.core.paths import skill_script
from dev10x.domain.common.result import Result, err, ok
from dev10x.github import _gateway
from dev10x.subprocess_utils import parse_key_value_output


async def detect_tracker(*, ticket_id: str) -> Result[dict[str, Any]]:
    return await _gateway._run_and_parse(
        skill_script(skill="gh-context", rel="detect-tracker.sh"),
        ticket_id,
        fallback=parse_key_value_output,
    )


async def pr_detect(*, arg: str) -> Result[dict[str, Any]]:
    return await _gateway._run_and_parse(
        skill_script(skill="gh-context", rel="gh-pr-detect.sh"),
        arg,
        fallback=parse_key_value_output,
    )


async def detect_base_branch(
    *,
    base: str | None = None,
    force: bool = False,
) -> Result[dict[str, Any]]:
    args: list[str] = []
    if base:
        args.extend(["--base", base])
    if force:
        args.append("--force")

    result = await _gateway.async_run_script(
        skill_script(skill="gh-pr-create", rel="detect-base-branch.sh"),
        *args,
    )

    if result.returncode != 0:
        return err(result.stderr.strip())

    parsed = parse_key_value_output(result.stdout)
    return ok(
        {
            "base_branch": parsed.get("BASE_BRANCH", ""),
            "has_develop": bool(parsed.get("DEV_BRANCH", "")),
        }
    )


async def verify_pr_state(*, force: bool = False) -> Result[dict[str, Any]]:
    args: list[str] = []
    if force:
        args.append("--force")

    return await _gateway._run_and_parse(
        skill_script(skill="gh-pr-create", rel="verify-state.sh"),
        *args,
        fallback=parse_key_value_output,
    )


async def pre_pr_checks(*, base_branch: str | None = None) -> Result[dict[str, Any]]:
    args: list[str] = []
    if base_branch:
        args.append(base_branch)

    result = await _gateway.async_run_script(
        skill_script(skill="gh-pr-create", rel="pre-pr-checks.sh"),
        *args,
    )

    if result.returncode != 0:
        return err(result.stderr.strip(), output=result.stdout.strip())

    return ok({"success": True, "output": result.stdout.strip()})
