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

from dev10x.domain.common.result import ErrorResult, Result, err, ok
from dev10x.permission.service import load_permission_context


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

    ctx = load_permission_context()
    if isinstance(ctx, ErrorResult):
        return ctx
    config = ctx.value.config
    settings_files = ctx.value.settings_files
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

    # GH-269: previously shelled out to
    # ${CLAUDE_PLUGIN_ROOT}/skills/upgrade-cleanup/scripts/update-paths.py.
    # That shim is retired — the version-bump path now runs in-process
    # against the same module the CLI uses.
    return await asyncio.to_thread(
        _run_update_paths,
        version=version,
        dry_run=dry_run,
        init=init,
        quiet=quiet,
    )


def _run_update_paths(
    *,
    version: str | None,
    dry_run: bool,
    init: bool,
    quiet: bool,
) -> Result[dict[str, Any]]:
    from pathlib import Path

    from dev10x.skills.permission import update_paths as mod

    if init:
        return err(
            "init is not supported via MCP; run `uvx dev10x permission update-paths --init`."
        )

    ctx = load_permission_context()
    if isinstance(ctx, ErrorResult):
        return ctx
    config_path = ctx.value.config_path
    config = ctx.value.config
    settings_files = ctx.value.settings_files
    if not settings_files:
        return err("No settings files found.")

    cache_dir = Path(config["plugin_cache"]).expanduser()
    target = version or mod.detect_latest_version(cache_dir)
    if not target:
        return err(f"No versions found in {cache_dir}")

    publisher = mod.extract_cache_publisher(config["plugin_cache"])

    messages: list[str] = []
    if not quiet:
        messages.append(f"Config: {config_path}")
        messages.append(f"Target version: {target}")
        if publisher:
            messages.append(f"Target publisher: {publisher}")
        if dry_run:
            messages.append("(dry run — no files will be modified)")

    total_changes = 0
    files_changed = 0
    for path in sorted(settings_files):
        count, file_messages = mod.update_file(
            path,
            target,
            target_publisher=publisher,
            dry_run=dry_run,
        )
        if count > 0:
            if not quiet:
                messages.append(f"\n{path}")
                messages.extend(file_messages)
            total_changes += count
            files_changed += 1

    if total_changes == 0:
        messages.append("All files already up to date.")
    else:
        verb = "Would update" if dry_run else "Updated"
        messages.append(f"{verb} {total_changes} paths in {files_changed} files.")

    return ok(
        {
            "success": True,
            "output": "\n".join(messages).strip(),
            "messages": messages,
            "total_changes": total_changes,
            "files_changed": files_changed,
        }
    )
