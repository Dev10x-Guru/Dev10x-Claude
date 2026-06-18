"""Shared utilities for calling external scripts via subprocess.

**Pattern: Gateway** (Fowler, *PoEAA*). This module is the Gateway to
the operating-system subprocess boundary: ``run`` / ``async_run`` /
``async_run_script`` wrap every external-process invocation behind one
call surface that transparently routes to the caller's effective
working directory (see ``_effective_cwd`` / ``use_cwd`` below). Callers
never reach for ``subprocess.run`` directly — going through this Gateway
keeps CWD routing, timeout handling, and output parsing in a single
layer. ADR-0013 names the pattern here and on ``dev10x.github``.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import logging
import os
import subprocess
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from dev10x.domain.cwd_resolver import set_cwd_resolver

log = logging.getLogger(__name__)

# GH-979: long-lived MCP server processes inherit the CWD they were
# spawned in. When Claude Code's EnterWorktree switches the session
# to a worktree, MCP tools still run subprocesses against the main
# repo. MCP entry points set this ContextVar so subprocess_utils can
# transparently route every subprocess to the caller's effective CWD
# without threading `cwd=` through dozens of internal signatures.
_effective_cwd: ContextVar[str | None] = ContextVar("_effective_cwd", default=None)


@contextlib.contextmanager
def use_cwd(cwd: str | None):
    """Bind subprocess_utils calls to `cwd` for the duration of the block.

    Pass None (or omit) to leave the current binding untouched. MCP tool
    entry points wrap their handler invocation with this context manager
    when the caller passes `cwd=`.
    """
    if cwd is None:
        yield
        return
    token = _effective_cwd.set(cwd)
    try:
        yield
    finally:
        _effective_cwd.reset(token)


def effective_cwd() -> str | None:
    """Return the bound effective CWD or None if unbound."""
    return _effective_cwd.get()


def _recover_process_cwd() -> None:
    """Recover from a deleted OS-level process CWD (GH-418 Finding 1).

    Long-lived MCP server processes may have been spawned in a directory
    that was later deleted (e.g. a worktree removed after a branch merge).
    When ``os.getcwd()`` raises ``FileNotFoundError``, every subsequent
    subprocess call that omits an explicit ``cwd=`` will also fail with
    ENOENT — even operations that write to ``/tmp`` and never touch the
    repo directory.

    This function detects the deleted-CWD condition and recovers by
    calling ``os.chdir()`` to the plugin root, which is always valid
    (it is the directory containing the currently-executing module).
    Changing the process CWD is a global side effect, but it is
    justified here: a process with a deleted CWD is inoperable and
    the plugin root is the natural safe fallback for a server that
    started from there.

    Called automatically by ``safe_effective_cwd()`` when the process
    CWD is detected to be deleted.
    """
    try:
        os.getcwd()
    except (FileNotFoundError, OSError):
        fallback = get_plugin_root()
        log.warning(
            "GH-418: MCP server process CWD was deleted; recovering by os.chdir(%s)",
            fallback,
        )
        os.chdir(fallback)


def safe_effective_cwd() -> str | None:
    """Return the bound effective CWD only when that directory still exists.

    GH-410: long-lived MCP server processes bind a worktree path via
    ``use_cwd``. After the worktree is removed (branch-delete on merge or
    manual cleanup), the bound path no longer exists. Passing a deleted path
    as ``cwd=`` to ``subprocess.run`` or ``asyncio.create_subprocess_exec``
    raises ``[Errno 2] No such file or directory`` (ENOENT), hard-failing
    every MCP call even when the operation itself does not need a real repo
    directory (e.g. ``mktmp`` writes to ``/tmp``).

    This function validates the bound path before returning it. When the
    bound dir is gone it returns ``None`` so callers inherit the process CWD.

    GH-418 (Finding 1): when the process CWD itself is deleted, returning
    ``None`` is not sufficient — callers that inherit the process CWD will
    still fail with ENOENT. This function detects that case and calls
    ``_recover_process_cwd()`` so the inherited CWD is a valid directory.
    """
    bound = _effective_cwd.get()
    if bound is None:
        # No bound worktree; callers will inherit the process CWD.
        # Recover if that CWD was deleted (GH-418 Finding 1).
        _recover_process_cwd()
        return None
    if Path(bound).is_dir():
        return bound
    # Bound dir is deleted; fall back to process CWD, recovering it first.
    _recover_process_cwd()
    return None


def requires_cwd[R](
    func: Callable[..., Awaitable[R]],
) -> Callable[..., Awaitable[R]]:
    """Decorator: bind `cwd=` kwarg to the effective-CWD ContextVar.

    Applied to async MCP tool handlers that accept a `cwd: str | None`
    keyword argument. The decorator extracts `cwd` from kwargs and
    invokes the wrapped function inside a `use_cwd(cwd)` block so
    subprocess calls automatically route to the caller's working
    directory (GH-979).

    Enforces the contract at handler-definition time: the wrapped
    function MUST declare a `cwd` keyword parameter. New MCP handlers
    that forget the wrapper are caught by `tests/test_cwd_enforcement.py`
    which fails CI when a `@server.tool()` handler with a `cwd`
    parameter is missing `with use_cwd(...)` or `@requires_cwd`.
    """

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> R:
        cwd = kwargs.get("cwd")
        with use_cwd(cwd):
            return await func(*args, **kwargs)

    return wrapper


def get_plugin_root() -> Path:
    return Path(__file__).parents[2]


def _matches_plugin_root(candidate: Path) -> bool:
    """Return True if `candidate` looks like the Dev10x plugin source.

    A directory matches when it contains `.claude-plugin/plugin.json`
    naming this plugin. We tolerate both publisher.name pairs by
    checking the marker file's existence — version drift between the
    cached install and the working tree is the whole point of GH-42.
    """
    return (candidate / ".claude-plugin" / "plugin.json").is_file()


def resolve_script_path(script_path: str) -> Path:
    """Return the script path to invoke, preferring the working tree.

    When CWD (or any ancestor) is the plugin source repo — detected by
    the presence of `.claude-plugin/plugin.json` — and the script
    exists at the same relative path under it, return that path. This
    lets plugin developers exercise their unsaved/uncached edits via
    MCP tools (GH-42). Otherwise fall back to the cached install
    discovered via `get_plugin_root()`.

    GH-410: uses ``safe_effective_cwd()`` so a deleted bound worktree
    path does not raise ENOENT during path resolution. Falls back to the
    plugin root's CWD when the bound directory is gone.
    """
    bound = safe_effective_cwd()
    if bound:
        cwd = Path(bound).resolve()
    else:
        try:
            cwd = Path.cwd().resolve()
        except FileNotFoundError:
            # Process CWD was also deleted (rare but possible in tests or after
            # aggressive worktree cleanup). Fall back to the plugin root which is
            # always a valid path.
            return get_plugin_root() / script_path
    for candidate in (cwd, *cwd.parents):
        if _matches_plugin_root(candidate):
            local_script = candidate / script_path
            if local_script.exists():
                return local_script
            break
    return get_plugin_root() / script_path


def run(
    args: list[str],
    *,
    cwd: str | None = None,
    **kwargs: Any,
) -> subprocess.CompletedProcess[str]:
    """Synchronous subprocess.run that routes `cwd` to the effective CWD.

    The single sync chokepoint for invoking external binaries (git, gh,
    ruff, ...) from in-process code. When `cwd` is None it falls back to
    the effective-CWD ContextVar bound by `use_cwd` (GH-979), so calls made
    inside a long-lived MCP server hit the caller's worktree instead of the
    server's startup directory. All other `subprocess.run` keyword arguments
    (`capture_output`, `text`, `check`, `env`, `timeout`, ...) pass through
    unchanged.

    GH-410: uses ``safe_effective_cwd()`` so a deleted bound directory does
    not raise ENOENT; falls back to the process CWD (None) when the bound
    dir is gone.
    """
    return subprocess.run(
        args,
        cwd=cwd if cwd is not None else safe_effective_cwd(),
        **kwargs,
    )


def run_script(
    script_path: str,
    *args: str,
    env_vars: dict[str, str] | None = None,
    cwd: str | None = None,
) -> subprocess.CompletedProcess[str]:
    full_path = resolve_script_path(script_path)

    if not full_path.exists():
        # Mirror async_run's timeout sentinel so MCP modules can map the
        # missing-script case onto their existing returncode-based error
        # handling instead of leaking FileNotFoundError through the MCP
        # boundary as an unstructured server error (GH-89).
        return subprocess.CompletedProcess(
            args=[str(full_path), *args],
            returncode=-1,
            stdout="",
            stderr=f"Script not found: {full_path}",
        )

    env = os.environ.copy()
    if env_vars:
        env.update(env_vars)

    return subprocess.run(
        [str(full_path), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd if cwd is not None else safe_effective_cwd(),
        check=False,
    )


async def async_run(
    args: list[str],
    *,
    env: dict[str, str] | None = None,
    timeout: float = 30,
    cwd: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """GH-410: uses ``safe_effective_cwd()`` so a deleted bound worktree path
    does not cause ENOENT when launching subprocesses.
    """
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        cwd=cwd if cwd is not None else safe_effective_cwd(),
    )
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(),
            timeout=timeout,
        )
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return subprocess.CompletedProcess(
            args=args,
            returncode=-1,
            stdout="",
            stderr="Process timed out",
        )
    return subprocess.CompletedProcess(
        args=args,
        returncode=proc.returncode or 0,
        stdout=stdout_bytes.decode() if stdout_bytes else "",
        stderr=stderr_bytes.decode() if stderr_bytes else "",
    )


async def async_run_script(
    script_path: str,
    *args: str,
    env_vars: dict[str, str] | None = None,
    cwd: str | None = None,
) -> subprocess.CompletedProcess[str]:
    full_path = resolve_script_path(script_path)

    if not full_path.exists():
        # See run_script for rationale (GH-89).
        return subprocess.CompletedProcess(
            args=[str(full_path), *[str(a) for a in args]],
            returncode=-1,
            stdout="",
            stderr=f"Script not found: {full_path}",
        )

    env = os.environ.copy()
    if env_vars:
        env.update(env_vars)

    return await async_run(
        args=[str(full_path), *[str(a) for a in args]],
        env=env,
        timeout=60,
        cwd=cwd,
    )


def parse_key_value_output(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in text.strip().split("\n"):
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip()
    return result


# GH-584 (audit N21): wire the concrete effective-CWD resolver into the
# domain seam so `dev10x.domain.git_context` resolves the bound worktree
# without importing this infra module (ADR-0008 Rule #1). Infra → domain
# is the allowed inward direction. `use_cwd` lives here too, so any code
# that can bind a CWD has already imported this module and triggered the
# wiring; processes that never import it keep the unbound (process-CWD)
# default.
set_cwd_resolver(effective_cwd)
