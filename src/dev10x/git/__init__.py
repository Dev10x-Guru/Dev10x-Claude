"""Git MCP tool implementations.

Extracted from cli_server.py — cohesive Git operations (push, rebase,
worktree, aliases). Each function delegates to shell scripts via
subprocess_utils.async_run_script().
All public functions are async to avoid blocking the MCP event loop.
"""

from __future__ import annotations

import json
from typing import Any

from dev10x.domain.common.branch_name import BranchName
from dev10x.domain.common.result import Result, err, ok
from dev10x.subprocess_utils import async_run_script, parse_key_value_output


def _ok_json_or_kv(stdout: str) -> Result[dict[str, Any]]:
    """Parse script stdout as JSON, falling back to KEY=VALUE lines."""
    try:
        return ok(json.loads(stdout))
    except json.JSONDecodeError:
        return ok(parse_key_value_output(stdout))


def _conflict_error(stdout: str, *, extra: dict[str, Any] | None = None) -> Result[dict[str, Any]]:
    """Build the shared rebase-conflict error payload from script stdout."""
    parsed = parse_key_value_output(stdout)
    fields: dict[str, Any] = {
        "conflict": True,
        "conflicted_files": [f for f in parsed.get("conflicted_files", "").split(",") if f],
        "rebase_head": parsed.get("rebase_head", "unknown"),
        "hint": parsed.get("hint", ""),
    }
    if extra:
        fields.update(extra)
    return err("Rebase conflict detected", **fields)


async def _run_git_script(
    script: str,
    *args: str,
    conflict_aware: bool = False,
) -> Result[dict[str, Any]]:
    """Run a git skill script and shape its result.

    Centralizes the repeated returncode-check → JSON-or-KEY=VALUE success
    parsing. When ``conflict_aware`` is set, a non-zero exit carrying a
    ``CONFLICT_DETECTED`` marker yields the shared conflict error payload.
    """
    result = await async_run_script(script, *args)

    if result.returncode != 0:
        if conflict_aware and "CONFLICT_DETECTED" in result.stdout:
            return _conflict_error(result.stdout.strip())
        return err(result.stderr.strip())

    return _ok_json_or_kv(result.stdout)


async def push_safe(
    *,
    args: list[str],
    protected_branches: list[str] | None = None,
) -> Result[dict[str, Any]]:
    cmd_args = list(args)
    if protected_branches:
        for pb in protected_branches:
            cmd_args.extend(["--protected", pb])

    return await _run_git_script("skills/git/scripts/git-push-safe.sh", *cmd_args)


async def rebase_groom(*, seq_path: str, base_ref: str) -> Result[dict[str, Any]]:
    return await _run_git_script(
        "skills/git/scripts/git-rebase-groom.sh",
        seq_path,
        base_ref,
        conflict_aware=True,
    )


async def create_worktree(
    *,
    branch: str,
    base: str | None = None,
    path: str | None = None,
) -> Result[dict[str, Any]]:
    branch_ref = BranchName.try_parse(branch)
    if branch_ref is None:
        return err(f"Invalid branch name: {branch!r}")
    if branch_ref.is_protected:
        return err(
            f"Refusing to create worktree on protected branch {branch!r}. "
            "Use a feature branch (username/TICKET-ID/[worktree/]slug)."
        )
    wt_args = [branch]

    if base is not None:
        wt_args.extend(["--base", base])
    if path is not None:
        wt_args.extend(["--path", path])

    return await _run_git_script(
        "skills/git-worktree/scripts/create-worktree.sh",
        *wt_args,
    )


async def mass_rewrite(*, config_path: str) -> Result[dict[str, Any]]:
    result = await async_run_script(
        "skills/git-groom/scripts/mass-rewrite.py",
        config_path,
    )

    if result.returncode != 0:
        stdout = result.stdout.strip()
        if "CONFLICT_DETECTED" in stdout:
            return _conflict_error(stdout, extra={"output": stdout})
        return err(result.stderr.strip(), output=stdout)

    return ok({"success": True, "output": result.stdout.strip()})


async def start_split_rebase(
    *,
    commit_hash: str,
    base_branch: str = "develop",
) -> Result[dict[str, Any]]:
    result = await async_run_script(
        "skills/git-commit-split/scripts/start-split-rebase.sh",
        commit_hash,
        base_branch,
    )

    if result.returncode != 0:
        return err(
            result.stderr.strip(),
            output=result.stdout.strip(),
        )

    return ok({"success": True, "output": result.stdout.strip()})


async def next_worktree_name(*, base_dir: str | None = None) -> Result[dict[str, Any]]:
    wt_args = [base_dir] if base_dir else []

    result = await async_run_script(
        "skills/git-worktree/scripts/next-worktree-name.sh",
        *wt_args,
    )

    if result.returncode != 0:
        return err(result.stderr.strip())

    return ok({"path": result.stdout.strip()})


async def setup_aliases() -> Result[dict[str, Any]]:
    result = await async_run_script(
        "skills/git-alias-setup/scripts/git-alias-setup.sh",
    )

    if result.returncode != 0:
        return err(result.stderr.strip())

    return ok({"success": True, "output": result.stdout.strip()})
