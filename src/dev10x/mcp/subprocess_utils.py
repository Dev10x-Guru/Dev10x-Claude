"""Shared utilities for calling external scripts via subprocess."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from pathlib import Path
from typing import Any


def get_plugin_root() -> Path:
    return Path(__file__).parents[3]


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
    cwd = Path.cwd().resolve()
    for candidate in (cwd, *cwd.parents):
        if _matches_plugin_root(candidate):
            local_script = candidate / script_path
            if local_script.exists():
                return local_script
            break
    return get_plugin_root() / script_path


def run_script(
    script_path: str,
    *args: str,
    env_vars: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    full_path = resolve_script_path(script_path)

    if not full_path.exists():
        raise FileNotFoundError(f"Script not found: {full_path}")

    env = os.environ.copy()
    if env_vars:
        env.update(env_vars)

    return subprocess.run(
        [str(full_path), *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


async def async_run(
    args: list[str],
    *,
    env: dict[str, str] | None = None,
    timeout: float = 30,
) -> subprocess.CompletedProcess[str]:
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
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
) -> subprocess.CompletedProcess[str]:
    full_path = resolve_script_path(script_path)

    if not full_path.exists():
        raise FileNotFoundError(f"Script not found: {full_path}")

    env = os.environ.copy()
    if env_vars:
        env.update(env_vars)

    return await async_run(
        args=[str(full_path), *[str(a) for a in args]],
        env=env,
        timeout=60,
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
