"""Session event dispatch — thin SessionStart / SessionStop / PreCompact handlers.

Event-routing module. Owns the entry points referenced by
``hooks/scripts/session-*.py`` and ``commands/hook.py``. Rendering and
data assembly live elsewhere:

* Document I/O — :mod:`dev10x.domain.session_document`.
* Named policies (friction parsing, permission migration, decision
  guidance) — :mod:`dev10x.hooks.session_policy`.
* Place provisioning (``/tmp`` setup, git alias inventory) —
  :mod:`dev10x.hooks.session_place`.
* Aggregated query + formatters — :mod:`dev10x.session.queries`.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dev10x.domain.claude_paths import ClaudeDir
from dev10x.domain.git_context import GitContext
from dev10x.domain.session_document import (
    plan_path_for_toplevel,
    state_path_for_toplevel,
    write_state,
)
from dev10x.hooks.session_policy import MigratePluginPermissionsRule
from dev10x.session.queries import (
    SessionContextQuery,
    format_compaction_summary,
    format_reload_context,
)

_git = GitContext()


def _get_toplevel() -> str | None:
    return GitContext().toplevel


def _escape_for_json(*, s: str) -> str:
    return (
        s.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )


def _run_git(*args: str) -> str:
    try:
        return GitContext().run(*args)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def _plugin_root() -> Path:
    return Path(__file__).parents[3]


def build_reload_context() -> str:
    """Build the session-reload additionalContext string. Empty when no state."""
    toplevel = _get_toplevel()
    if not toplevel:
        return ""
    ctx = SessionContextQuery.gather_reload(toplevel=toplevel)
    return format_reload_context(ctx=ctx)


def session_reload() -> None:
    context = build_reload_context()
    if not context:
        sys.exit(0)
    escaped = _escape_for_json(s=context)
    print(
        '{"hookSpecificOutput":{"hookEventName":"SessionStart",'
        f'"additionalContext":"{escaped}"}}}}'
    )


def context_compact() -> None:
    toplevel = _get_toplevel()
    if not toplevel:
        sys.exit(0)
    ctx = SessionContextQuery.gather_compaction(toplevel=toplevel)
    summary = format_compaction_summary(ctx=ctx, plugin_root=_plugin_root())
    escaped = _escape_for_json(s=summary)
    print(f'{{"hookSpecificOutput":{{"systemMessage":"{escaped}"}}}}')


def build_guidance_context() -> str:
    """Return the session-guidance.md contents, or empty string if missing."""
    guidance_file = _plugin_root() / "hooks" / "scripts" / "session-guidance.md"
    return guidance_file.read_text() if guidance_file.exists() else ""


def build_install_check_context() -> str:
    """Warn the user when the Dev10x install needs bootstrap or upgrade.

    Returns an empty string when the install is current — the orchestrator
    drops empty segments, so a no-op leaves no trace in additionalContext.
    """
    from dev10x.domain.install_version import install_state

    state = install_state()
    if state.needs_bootstrap:
        return (
            "Dev10x config folder is missing at ~/.config/Dev10x.\n"
            "Run `/Dev10x:upgrade-cleanup` to bootstrap the userspace install."
        )
    if state.needs_upgrade:
        plugin = state.plugin_version or "unknown"
        applied = state.applied_version or "never applied"
        return (
            f"Dev10x plugin {plugin} is installed but upgrade-cleanup was last "
            f"run for {applied}.\n"
            "Run `/Dev10x:upgrade-cleanup` to refresh permissions and "
            "migrate config files."
        )
    return ""


def session_install_check() -> None:
    """Emit install-state guidance as additionalContext (SessionStart hook)."""
    content = build_install_check_context()
    if not content:
        sys.exit(0)
    escaped = _escape_for_json(s=content)
    print(
        '{"hookSpecificOutput":{"hookEventName":"SessionStart",'
        f'"additionalContext":"{escaped}"}}}}'
    )


def session_guidance() -> None:
    """Output session-guidance.md as additionalContext (SessionStart hook)."""
    content = build_guidance_context()
    if not content:
        sys.exit(0)
    escaped = _escape_for_json(s=content)
    print(
        '{"hookSpecificOutput":{"hookEventName":"SessionStart",'
        f'"additionalContext":"{escaped}"}}}}'
    )


def session_migrate_permissions() -> None:
    """Migrate stale plugin permission rules to current version (SessionStart hook).

    Delegates to :class:`MigratePluginPermissionsRule`. Only runs when
    installed via the plugin cache (not ``--plugin-dir``).
    """
    rule = MigratePluginPermissionsRule(plugin_root=_plugin_root(), home_path=Path.home())
    if not rule.applicable():
        sys.exit(0)
    total_migrated, files_changed = rule.apply()
    if total_migrated > 0:
        files_str = ", ".join(files_changed)
        print(
            f"Migrated {total_migrated} stale permission rule(s) "
            f"to current plugin version in {files_str}"
        )


def session_persist(data: dict | None = None) -> None:
    """Persist session state to disk for next-session reload (SessionStop hook)."""
    if data is None:
        try:
            data = json.load(sys.stdin)
        except (json.JSONDecodeError, EOFError):
            sys.exit(0)
    session_id = data.get("session_id") or ""
    if not session_id:
        return
    toplevel = _get_toplevel()
    if not toplevel:
        return

    state_dir = ClaudeDir.session_state_dir()
    state_dir.mkdir(parents=True, exist_ok=True)
    state_dir.chmod(0o700)

    worktree_name = Path(toplevel).name if (Path(toplevel) / ".git").is_file() else ""
    state: dict[str, Any] = {
        "session_id": session_id,
        "branch": _run_git("rev-parse", "--abbrev-ref", "HEAD") or "unknown",
        "worktree": worktree_name,
        "working_directory": toplevel,
        "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "modified_files": _run_git("diff", "--name-only").splitlines()[:20],
        "staged_files": _run_git("diff", "--cached", "--name-only").splitlines()[:20],
        "recent_commits": _run_git("log", "--oneline", "-5").splitlines(),
        "has_plan": plan_path_for_toplevel(toplevel=toplevel).exists(),
    }
    write_state(path=state_path_for_toplevel(toplevel=toplevel), state=state)


def session_goodbye(data: dict | None = None) -> None:
    """Output goodbye message with community link and resume hint (SessionStop hook)."""
    if data is None:
        try:
            data = json.load(sys.stdin)
        except (json.JSONDecodeError, EOFError):
            data = {}
    session_id = data.get("session_id") or ""
    url = "https://www.skool.com/Dev10x-1892"
    print()
    print("Thank you for using Dev10x. Join the community to get the most out of the plugin:")
    print(f"\033]8;;{url}\033\\{url}\033]8;;\033\\")
    if session_id:
        print()
        print("Resume this session with:")
        print(f"  claude --resume {session_id}")


__all__ = [
    "build_install_check_context",
    "build_reload_context",
    "build_guidance_context",
    "session_reload",
    "context_compact",
    "session_guidance",
    "session_install_check",
    "session_migrate_permissions",
    "session_persist",
    "session_goodbye",
]
