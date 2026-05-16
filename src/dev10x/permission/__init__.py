"""Permission maintenance MCP tool implementations.

Wraps permission sub-commands as an MCP tool so skills can update
plugin permission settings without Bash allow-rule friction.

Calls the public ``ensure_*`` / ``generalize`` helpers in
``dev10x.skills.permission.update_paths``, which return structured
result dicts (``exit_code``, ``messages``, ``errors``, stats). No
``redirect_stdout`` capture — the helpers do not print to stdout.
"""

from __future__ import annotations

import asyncio
from typing import Any

from dev10x.domain.result import Result, err, ok
from dev10x.subprocess_utils import async_run, get_plugin_root


def _run_sub_command(
    *,
    ensure_base: bool = False,
    generalize: bool = False,
    ensure_scripts: bool = False,
    ensure_workspace: bool = False,
    ensure_reads: bool = False,
    dry_run: bool = False,
    quiet: bool = False,
) -> Result[dict[str, Any]]:
    from dev10x.skills.permission import update_paths as mod

    config_path = mod.find_config()
    config = mod.load_config(config_path)
    settings_files = mod.find_settings_files(
        roots=config.get("roots", []),
        include_user=config.get("include_user_settings", True),
    )
    if not settings_files:
        return err("No settings files found.")

    combined_messages: list[str] = []
    combined_errors: list[str] = []
    exit_code = 0

    def _run(result: dict[str, Any]) -> bool:
        """Append result's messages/errors and return True if it succeeded."""
        nonlocal exit_code
        combined_messages.extend(result.get("messages", []))
        combined_errors.extend(result.get("errors", []))
        rc = int(result.get("exit_code", 0))
        if rc != 0:
            exit_code = rc
            return False
        return True

    if ensure_workspace:
        if not _run(
            mod.ensure_workspace(
                config=config,
                settings_files=settings_files,
                dry_run=dry_run,
                quiet=quiet,
            )
        ):
            return _format_failure(combined_messages, combined_errors, exit_code)
    if ensure_base:
        if not _run(
            mod.ensure_base(
                config=config,
                settings_files=settings_files,
                dry_run=dry_run,
                quiet=quiet,
            )
        ):
            return _format_failure(combined_messages, combined_errors, exit_code)
    if generalize:
        if not _run(
            mod.generalize(
                settings_files=settings_files,
                dry_run=dry_run,
                quiet=quiet,
            )
        ):
            return _format_failure(combined_messages, combined_errors, exit_code)
    if ensure_scripts:
        if not _run(
            mod.ensure_scripts(
                config=config,
                settings_files=settings_files,
                dry_run=dry_run,
                quiet=quiet,
            )
        ):
            return _format_failure(combined_messages, combined_errors, exit_code)
    if ensure_reads:
        if not _run(
            mod.ensure_reads(
                config=config,
                settings_files=settings_files,
                dry_run=dry_run,
                quiet=quiet,
            )
        ):
            return _format_failure(combined_messages, combined_errors, exit_code)

    output = "\n".join(combined_messages).strip()
    return ok({"success": True, "output": output, "messages": combined_messages})


def _format_failure(
    messages: list[str],
    errors: list[str],
    exit_code: int,
) -> Result[dict[str, Any]]:
    error_text = "\n".join(errors).strip()
    if not error_text:
        body = "\n".join(messages).strip()
        error_text = body or f"Sub-command failed with exit code {exit_code}"
    return err(error_text, messages=messages, errors=errors)


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
) -> Result[dict[str, Any]]:
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
        return err(result.stderr.strip())

    return ok({"success": True, "output": result.stdout.strip()})
