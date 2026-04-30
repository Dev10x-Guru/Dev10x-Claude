"""Permission maintenance MCP tool implementations.

Wraps permission sub-commands as an MCP tool so skills can update
plugin permission settings without Bash allow-rule friction.
"""

from __future__ import annotations

import asyncio
import io
from contextlib import redirect_stdout
from typing import Any

from dev10x.mcp.subprocess_utils import async_run, get_plugin_root


def _run_sub_command(
    *,
    ensure_base: bool = False,
    generalize: bool = False,
    ensure_scripts: bool = False,
    ensure_workspace: bool = False,
    ensure_reads: bool = False,
    dry_run: bool = False,
    quiet: bool = False,
) -> dict[str, Any]:
    from dev10x.skills.permission import update_paths as mod

    config_path = mod.find_config()
    config = mod.load_config(config_path)
    settings_files = mod.find_settings_files(
        roots=config.get("roots", []),
        include_user=config.get("include_user_settings", True),
    )
    if not settings_files:
        return {"error": "No settings files found."}

    buf = io.StringIO()
    rc = 0

    with redirect_stdout(buf):
        if ensure_workspace:
            rc = mod._ensure_workspace(
                config=config,
                settings_files=settings_files,
                dry_run=dry_run,
                quiet=quiet,
            )
        if ensure_base and rc == 0:
            rc = mod._ensure_base(
                config=config,
                settings_files=settings_files,
                dry_run=dry_run,
                quiet=quiet,
            )
        if generalize and rc == 0:
            rc = mod._generalize(
                settings_files=settings_files,
                dry_run=dry_run,
                quiet=quiet,
            )
        if ensure_scripts and rc == 0:
            rc = mod._ensure_scripts(
                config=config,
                settings_files=settings_files,
                dry_run=dry_run,
                quiet=quiet,
            )
        if ensure_reads and rc == 0:
            rc = mod._ensure_reads(
                config=config,
                settings_files=settings_files,
                dry_run=dry_run,
                quiet=quiet,
            )

    output = buf.getvalue().strip()
    if rc != 0:
        return {"error": output or f"Sub-command failed with exit code {rc}"}
    return {"success": True, "output": output}


async def update_paths(
    *,
    version: str | None = None,
    dry_run: bool = False,
    ensure_base: bool = False,
    generalize: bool = False,
    ensure_scripts: bool = False,
    ensure_workspace: bool = False,
    ensure_reads: bool = False,
    init: bool = False,
    quiet: bool = False,
) -> dict[str, Any]:
    if ensure_base or generalize or ensure_scripts or ensure_workspace or ensure_reads:
        return await asyncio.to_thread(
            _run_sub_command,
            ensure_base=ensure_base,
            generalize=generalize,
            ensure_scripts=ensure_scripts,
            ensure_workspace=ensure_workspace,
            ensure_reads=ensure_reads,
            dry_run=dry_run,
            quiet=quiet,
        )

    script = get_plugin_root() / "skills/upgrade-cleanup/scripts/update-paths.py"
    args: list[str] = [str(script)]

    if version:
        args.extend(["--version", version])
    if dry_run:
        args.append("--dry-run")
    if init:
        args.append("--init")
    if quiet:
        args.append("--quiet")

    result = await async_run(args=args, timeout=60)

    if result.returncode != 0:
        return {"error": result.stderr.strip()}

    return {"success": True, "output": result.stdout.strip()}
