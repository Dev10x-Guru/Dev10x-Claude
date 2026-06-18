"""Session event dispatch — thin SessionStart / SessionStop / PreCompact handlers.

Event-routing module. Owns the entry points referenced by
``hooks/scripts/session-*.py`` and ``commands/hook.py``. Rendering and
data assembly live elsewhere:

* Document I/O — :mod:`dev10x.domain.session_document`.
* Named policies (friction parsing, permission migration, decision
  guidance) — :mod:`dev10x.hooks.session_policy`.
* Place provisioning (``/tmp`` setup, git alias inventory) —
  :mod:`dev10x.hooks.session_place`.
* Aggregated query + formatters — :mod:`dev10x.domain.documents.session_context`.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from dev10x.domain.claude_paths import ClaudeDir
from dev10x.domain.documents.session_context import (
    SessionContextQuery,
    format_compaction_summary,
    format_reload_context,
)
from dev10x.domain.documents.session_state import SessionState
from dev10x.domain.git_context import GitContext
from dev10x.domain.session_document import (
    plan_path_for_toplevel,
    state_path_for_toplevel,
    write_state,
)
from dev10x.hooks.session_policy import MigratePluginPermissionsRule


def _get_toplevel() -> str | None:
    # GH-979 (H11): fresh GitContext per call — no module-level singleton,
    # which would pin the first-call CWD across MCP invocations.
    return GitContext().toplevel


def _escape_for_json(*, s: str) -> str:
    return (
        s.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )


def _emit_context(content: str) -> None:
    """Emit content as a SessionStart additionalContext JSON envelope.

    Exits silently (sys.exit(0)) when content is empty. This is the
    single shared emit path for all standalone SessionStart hook
    sub-commands — previously duplicated across session_reload,
    session_install_check, and session_guidance.
    """
    if not content:
        sys.exit(0)
    escaped = _escape_for_json(s=content)
    print(
        '{"hookSpecificOutput":{"hookEventName":"SessionStart",'
        f'"additionalContext":"{escaped}"}}}}'
    )


def _run_git_safe(git: GitContext, *args: str) -> str:
    try:
        return git.run(*args)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def _plugin_root() -> Path:
    return Path(__file__).parents[3]


def drain_stdin() -> None:
    """Discard the hook payload Claude Code writes to stdin (GH-249 H5).

    Hooks that never read stdin can leave the writer's pipe full; draining
    it avoids a ``BrokenPipeError`` on the Claude Code side. Best-effort —
    any read failure (already closed, empty) is swallowed.
    """
    try:
        sys.stdin.read()
    except Exception:
        pass


def build_reload_context() -> str:
    """Build the session-reload additionalContext string. Empty when no state."""
    toplevel = _get_toplevel()
    if not toplevel:
        return ""
    ctx = SessionContextQuery.gather_reload(toplevel=toplevel)
    return format_reload_context(ctx=ctx)


def session_reload() -> None:
    _emit_context(build_reload_context())


def context_compact() -> None:
    drain_stdin()
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


def build_autonomy_reassurance_context() -> str:
    """Reassurance block for adaptive + solo-maintainer sessions (GH-261).

    Returns an empty string outside the autonomous-shipping profile; the
    orchestrator drops empty segments so non-solo sessions see no change.
    """
    from dev10x.domain.documents.session_yaml import SessionYamlDocument
    from dev10x.domain.session_rules import BuildAutonomyReassuranceRule

    toplevel = _get_toplevel()
    if not toplevel:
        return ""
    friction_level, active_modes = SessionYamlDocument(toplevel=toplevel).read_friction_and_modes()
    return BuildAutonomyReassuranceRule(
        friction_level=friction_level, active_modes=active_modes
    ).apply()


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


def build_hook_version_drift_context() -> str:
    """Warn when the running-hook version lags the latest installed version.

    Claude Code loads hooks once at session start from ``$CLAUDE_PLUGIN_ROOT``.
    An on-disk ``claude plugin update`` installs a newer version but does NOT
    swap the running hooks — the session continues executing the pre-upgrade
    hooks until it restarts. This means shipped friction fixes, new validators,
    and catalog improvements are dormant in long-running sessions.

    This check is **distinct** from :func:`build_install_check_context`, which
    compares the installed version against the last-applied upgrade-cleanup
    version. That check detects settings staleness; this one detects
    running-hook staleness — they can diverge when settings were refreshed
    but the session was not restarted.

    Returns an empty string when no drift is detected or when either version
    cannot be determined (``--plugin-dir`` dev installs, new users, etc.).
    """
    from dev10x.domain.install_version import (
        read_latest_installed_version,
        read_running_hook_version,
    )

    running = read_running_hook_version()
    if running is None:
        return ""
    latest = read_latest_installed_version()
    if latest is None:
        return ""
    if running == latest:
        return ""
    return (
        f"Dev10x hooks running v{running} but v{latest} is installed on disk.\n"
        "Restart this session (or run `/Dev10x:upgrade-cleanup`) to activate "
        "shipped friction fixes, validators, and catalog improvements."
    )


def session_install_check() -> None:
    """Emit install-state guidance as additionalContext (SessionStart hook)."""
    _emit_context(build_install_check_context())


def session_guidance() -> None:
    """Output session-guidance.md as additionalContext (SessionStart hook)."""
    _emit_context(build_guidance_context())


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

    git = GitContext(cwd=toplevel)
    state = SessionState.capture(
        session_id=session_id,
        toplevel=toplevel,
        run_git=lambda *args: _run_git_safe(git, *args),
        timestamp=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    ).to_dict()
    state["working_directory"] = toplevel
    state["has_plan"] = plan_path_for_toplevel(toplevel=toplevel).exists()
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
    "build_hook_version_drift_context",
    "build_install_check_context",
    "build_reload_context",
    "build_autonomy_reassurance_context",
    "build_guidance_context",
    "session_reload",
    "context_compact",
    "session_guidance",
    "session_install_check",
    "session_migrate_permissions",
    "session_persist",
    "session_goodbye",
]
