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
from dev10x.domain.common.result import Result, SuccessResult, err, ok
from dev10x.domain.documents.session_yaml import SessionYamlDocument
from dev10x.domain.git_context import GitContext
from dev10x.subprocess_utils import async_run, async_run_script, parse_key_value_output


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


def _paused_error(stdout: str) -> Result[dict[str, Any]]:
    """Build the payload for a rebase that stopped with no unmerged paths.

    Distinct from ``_conflict_error`` on purpose: reporting this state as
    ``conflict: true`` with an empty ``conflicted_files`` list told callers
    to resolve conflicts git never reported, and following that hint is
    what completed the damage in GH-1103.
    """
    parsed = parse_key_value_output(stdout)
    return err(
        "Rebase paused with no unmerged paths",
        conflict=False,
        paused=True,
        conflicted_files=[],
        rebase_head=parsed.get("rebase_head", "unknown"),
        hint=parsed.get("hint", ""),
    )


async def _run_git_script(
    script: str,
    *args: str,
    conflict_aware: bool = False,
) -> Result[dict[str, Any]]:
    """Run a git skill script and shape its result.

    Centralizes the repeated returncode-check → JSON-or-KEY=VALUE success
    parsing. When ``conflict_aware`` is set, a non-zero exit carrying a
    ``CONFLICT_DETECTED`` marker yields the shared conflict error payload,
    and a ``REBASE_PAUSED`` marker the distinct paused payload (GH-1103).
    """
    result = await async_run_script(script, *args)

    if result.returncode != 0:
        if conflict_aware and "CONFLICT_DETECTED" in result.stdout:
            return _conflict_error(result.stdout.strip())
        if conflict_aware and "REBASE_PAUSED" in result.stdout:
            return _paused_error(result.stdout.strip())
        return err(result.stderr.strip())

    return _ok_json_or_kv(result.stdout)


def _resolve_protected_branches(explicit: list[str] | None) -> list[str] | None:
    """Resolve the protected-branch set for a push (GH-1031).

    An explicit caller list wins. Otherwise the project's durable
    ``protected_branches`` pref applies, so a repo whose integration branch
    is not one of the shell script's defaults stays protected without every
    caller passing the list — an unattended agent never does.

    ``None`` (no caller list, no pref, or no resolvable repo root) leaves the
    flag off entirely and lets ``git-push-safe.sh`` apply its own default set —
    which protects MORE branches than an empty list would, so that is the safe
    direction to degrade in.
    """
    if explicit:
        return list(explicit)
    toplevel = GitContext().toplevel
    if toplevel is None:
        return None
    return SessionYamlDocument(toplevel=toplevel).read_protected_branches()


async def push_safe(
    *,
    args: list[str],
    protected_branches: list[str] | None = None,
) -> Result[dict[str, Any]]:
    cmd_args = list(args)
    for pb in _resolve_protected_branches(protected_branches) or []:
        cmd_args.extend(["--protected", pb])

    return await _run_git_script("skills/git/scripts/git-push-safe.sh", *cmd_args)


def qualify_base_ref(base_ref: str, *, remote_exists: bool) -> str:
    """Prefer ``origin/<base>`` over a possibly-stale local branch (GH-486).

    A bare local branch name (``develop``) may lag ``origin/develop``
    after rebase-merge advances the remote, long-lived feature work, or
    worktrees sharing an outdated local ref. Grooming against the stale
    local ref mis-computes the commit range. When the remote-tracking
    ref exists, groom against it instead. Already-qualified refs (those
    containing ``/``, e.g. ``origin/develop``) and SHAs pass through
    unchanged.
    """
    if "/" in base_ref:
        return base_ref
    return f"origin/{base_ref}" if remote_exists else base_ref


async def _resolve_groom_base(base_ref: str) -> tuple[str, str | None]:
    """Resolve the effective groom base ref and a stale-local notice.

    Returns ``(effective_ref, notice)``. ``notice`` is non-None only when
    the local branch lags its remote-tracking counterpart, so the caller
    can surface "grooming against origin/<base>" instead of silently
    using a stale ref (GH-486).
    """
    if "/" in base_ref:
        return base_ref, None

    remote = f"origin/{base_ref}"
    # One round-trip: `rev-list --count base..origin/base` exits non-zero
    # when either ref is absent (no remote-tracking ref), and emits the
    # lag count when both exist — so a single call both detects the
    # remote and measures staleness.
    behind = await async_run(
        args=["git", "rev-list", "--count", f"{base_ref}..{remote}"],
        timeout=15,
    )
    if behind.returncode != 0:
        return base_ref, None

    effective = qualify_base_ref(base_ref, remote_exists=True)
    count = behind.stdout.strip()
    notice: str | None = None
    if count.isdigit() and int(count) > 0:
        notice = (
            f"local {base_ref} is {count} commit(s) behind {remote} — "
            f"grooming against {effective} (fork-point), not the stale local ref"
        )
    return effective, notice


async def rebase_groom(*, seq_path: str, base_ref: str) -> Result[dict[str, Any]]:
    effective_ref, notice = await _resolve_groom_base(base_ref)
    result = await _run_git_script(
        "skills/git/scripts/git-rebase-groom.sh",
        seq_path,
        effective_ref,
        conflict_aware=True,
    )
    if notice is not None and isinstance(result, SuccessResult):
        return ok({**result.value, "base_notice": notice})
    return result


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

    # create-worktree.sh takes strictly positional args
    # (<worktree-path> <branch-name> [base-ref] [repo-root]) — it does
    # not parse flags. Passing `--base`/`--path` tokens through as
    # positionals silently misroutes them into the script's repo-root
    # slot (GH-960). Resolve a concrete worktree-path up front (via the
    # same default logic as next_worktree_name) and forward `base` as
    # its own positional so the script's start-point argument sees it.
    if path is None:
        name_result = await next_worktree_name()
        if not isinstance(name_result, SuccessResult):
            return name_result
        path = name_result.value["path"]

    return await _run_git_script(
        "skills/git-worktree/scripts/create-worktree.sh",
        path,
        branch,
        base or "",
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
