"""Permission maintenance service layer.

The config-resolution boundary shared by the permission MCP adapter
(``dev10x.permission``) and the CLI (``dev10x.commands.permission``).
Both previously inlined the same ``find_config`` → ``load_config`` →
``find_settings_files`` sequence and reached directly into
``dev10x.skills.permission`` (audit N18). This layer owns that
sequence once — mirroring ``dev10x.plan.service`` — so the adapters
depend on the service, not on the skills package internals.

Name derivation and the actual settings mutations stay in
``dev10x.skills.permission.*``; the service only assembles the
context those operations consume.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dev10x.domain.common.result import ErrorResult, Result, ok


@dataclass(frozen=True)
class PermissionContext:
    """Resolved config + settings files for a permission operation."""

    config_path: Path
    config: dict[str, Any]
    settings_files: list[Path]


def load_permission_context(*, include_user: bool | None = None) -> Result[PermissionContext]:
    """Resolve the config path, parse it, and discover settings files.

    Returns the wrapped :class:`PermissionContext` on success, or the
    :class:`ErrorResult` from ``find_config`` when no userspace config
    can be resolved. ``settings_files`` may be empty — callers decide
    whether an empty result is an error (MCP) or a no-op (CLI), so this
    layer does not impose either policy.

    When ``include_user`` is ``None`` the config's
    ``include_user_settings`` flag (default ``True``) is honored; pass
    an explicit bool to override it (e.g. ``promote-plan`` excludes
    user settings).
    """
    from dev10x.skills.permission import update_paths as mod

    resolved = mod.find_config()
    if isinstance(resolved, ErrorResult):
        return resolved
    config_path = resolved.value
    config = mod.load_config(config_path)

    use_user = config.get("include_user_settings", True) if include_user is None else include_user
    settings_files = mod.find_settings_files(
        roots=config.get("roots", []),
        include_user=use_user,
    )
    return ok(
        PermissionContext(
            config_path=config_path,
            config=config,
            settings_files=settings_files,
        )
    )


__all__ = ["PermissionContext", "load_permission_context"]
