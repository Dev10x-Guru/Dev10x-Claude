"""PR summary and notification capability (ADR-0027).

Dependencies are reached through ``_gateway.<name>`` (ADR-0027 D2), so a
test patches ``dev10x.github._gateway.<name>`` and intercepts every caller.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dev10x.domain.common.result import Result, err, ok
from dev10x.domain.dead_letter import record_undelivered
from dev10x.github import _gateway


async def generate_commit_list(
    *,
    pr_number: int,
    base_branch: str | None = None,
) -> Result[dict[str, Any]]:
    args = [str(pr_number)]
    if base_branch:
        args.append(base_branch)

    result = await _gateway.async_run_script(
        "skills/gh-pr-create/scripts/generate-commit-list.sh",
        *args,
    )

    if result.returncode != 0:
        return err(result.stderr.strip())

    return ok({"commit_list": result.stdout.strip()})


async def post_summary_comment(
    *,
    issue_id: str,
    summary_text: str,
    repo: str | None = None,
) -> Result[dict[str, Any]]:
    env_vars: dict[str, str] = {}
    resolved_repo = repo or await _gateway._detect_repo()
    if resolved_repo:
        bot_env = await _gateway._bot_env(repo=resolved_repo)
        if bot_env is not None:
            env_vars["GH_TOKEN"] = bot_env["GH_TOKEN"]
            env_vars["GITHUB_TOKEN"] = bot_env["GITHUB_TOKEN"]
    result = await _gateway.async_run_script(
        "skills/gh-pr-create/scripts/post-summary-comment.sh",
        issue_id,
        summary_text,
        env_vars=env_vars or None,
    )

    if result.returncode != 0:
        return err(result.stderr.strip())

    return ok({"success": True, "output": result.stdout.strip()})


async def pr_notify(
    *,
    pr_number: int,
    repo: str,
    action: str = "prepare",
    channel: str | None = None,
    message: str | None = None,
    message_file: str | None = None,
    reviewer: str | None = None,
    skip_slack: bool = False,
    skip_reviewers: bool = False,
    skip_checklist: bool = False,
) -> Result[dict[str, Any]]:
    plugin_root = Path(__file__).parents[3]
    script_path = plugin_root / "skills" / "gh-pr-monitor" / "scripts" / "pr-notify.py"

    if not script_path.exists():
        return err(f"Script not found: {script_path}")

    args = [
        "uv",
        "run",
        "--script",
        str(script_path),
        action,
        "--pr",
        str(pr_number),
        "--repo",
        repo,
    ]

    if action == "send":
        if channel:
            args.extend(["--channel", channel])
        if message:
            args.extend(["--message", message])
        if message_file:
            args.extend(["--message-file", message_file])
        if reviewer:
            args.extend(["--reviewer", reviewer])
        if skip_slack:
            args.append("--skip-slack")
        if skip_reviewers:
            args.append("--skip-reviewers")
        if skip_checklist:
            args.append("--skip-checklist")

    proc = await _gateway.async_run(args=args, timeout=60)

    if proc.returncode != 0:
        reason = proc.stderr.strip()
        # GH-1421: only a failed `send` is a lost notification. `prepare`
        # composes a message without dispatching one, so recording it
        # would fill the log with entries nothing was ever going to
        # deliver — and a sink full of noise is not discoverable.
        if action == "send":
            record_undelivered(
                channel=channel or "(default)",
                transport="pr_notify",
                error=reason,
                body=message,
                context={"pr_number": pr_number, "repo": repo, "reviewer": reviewer},
            )
        return err(reason)

    try:
        return ok(json.loads(proc.stdout))
    except json.JSONDecodeError:
        return ok({"success": True, "output": proc.stdout.strip()})
