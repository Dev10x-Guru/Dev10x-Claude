"""Shared utilities for calling external scripts via subprocess."""

from __future__ import annotations

import asyncio
import contextlib
import functools
import json
import os
import subprocess
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from pathlib import Path
from typing import Any

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
    """
    bound = _effective_cwd.get()
    cwd = Path(bound).resolve() if bound else Path.cwd().resolve()
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
    """
    return subprocess.run(
        args,
        cwd=cwd if cwd is not None else _effective_cwd.get(),
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
        cwd=cwd if cwd is not None else _effective_cwd.get(),
        check=False,
    )


async def async_run(
    args: list[str],
    *,
    env: dict[str, str] | None = None,
    timeout: float = 30,
    cwd: str | None = None,
) -> subprocess.CompletedProcess[str]:
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        cwd=cwd if cwd is not None else _effective_cwd.get(),
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


def parse_json_output(text: str) -> dict[str, Any]:
    return json.loads(text)
