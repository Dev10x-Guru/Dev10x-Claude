"""Session service layer.

The IO/orchestration boundary for session-start context builders. This
layer owns the concerns that the hook dispatch must not — plugin-root
resolution, document reads, install-state probes, version-drift checks,
and policy-rule invocations — and delegates all formatting to the domain
(``session_context``, ``session_rules``). It stays separate from the
hook entry-points deliberately: folding this orchestration into the
dispatch shims would couple them to the filesystem layout and prevent
direct unit testing.

Both ``dev10x.hooks.session_dispatch`` and any future MCP surface
delegate here, eliminating the previously inlined orchestration from
the dispatch functions.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

# Sentinel used by methods that accept an optional pre-resolved ``toplevel``
# string. A caller that passes ``_UNSET`` (the default) triggers git
# discovery inside the method. A caller that passes ``None`` explicitly
# (e.g. when ``_get_toplevel()`` already returned ``None``) signals "no
# repo available — return early". This avoids the ambiguity of using ``None``
# for both "not provided" and "absent".
_UNSET: Final = object()


class SessionServiceError(Exception):
    """Raised when a session service operation cannot proceed."""


class SessionService:
    """Orchestrates session-context assembly for SessionStart and PreCompact hooks.

    Constructed with a ``plugin_root`` so callers can inject a test double
    without monkeypatching module globals. Pass ``None`` to let the service
    resolve the real plugin root from the package location (production use).
    """

    def __init__(self, *, plugin_root: Path | None = None) -> None:
        self._plugin_root = plugin_root or self._default_plugin_root()

    @staticmethod
    def _default_plugin_root() -> Path:
        return Path(__file__).parents[3]

    def build_reload_context(self, *, toplevel: str | None = _UNSET) -> str:  # type: ignore[assignment]
        """Return the session-reload additionalContext string.

        Returns an empty string when no git toplevel is available or when
        there is no prior session state / plan to report.

        Pass ``toplevel`` as a pre-resolved string to skip git discovery.
        Pass ``None`` explicitly (e.g. from a ``_get_toplevel()`` call that
        found no repo) to return early without git discovery. Omit the
        parameter to let the service run git discovery itself.
        """
        from dev10x.domain.documents.session_context import (
            SessionContextQuery,
            format_reload_context,
        )
        from dev10x.domain.git_context import GitContext

        resolved: str | None = GitContext().toplevel if toplevel is _UNSET else toplevel
        if not resolved:
            return ""
        ctx = SessionContextQuery.gather_reload(toplevel=resolved)
        return format_reload_context(ctx=ctx)

    def build_guidance_context(self) -> str:
        """Return the session-guidance.md contents, or empty string if missing."""
        guidance_file = self._plugin_root / "hooks" / "scripts" / "session-guidance.md"
        return guidance_file.read_text() if guidance_file.exists() else ""

    def build_background_preamble_context(self) -> str:
        """Return the background-dispatch friction preamble (GH-610).

        Background subagents (workflow / monitor / loop / fanout) start with
        a fresh system prompt and never receive the SessionStart friction
        briefing. Dispatchers prepend this text to each subagent prompt so it
        avoids hook-tripping command shapes and stays on the pre-approved
        tool surface. Returns the canonical preamble document contents, or an
        empty string when the document is missing.
        """
        preamble_file = (
            self._plugin_root / "references" / "orchestration" / "background-preamble.md"
        )
        return preamble_file.read_text() if preamble_file.exists() else ""

    def build_autonomy_reassurance_context(self, *, toplevel: str | None = _UNSET) -> str:  # type: ignore[assignment]
        """Return a reassurance block for adaptive + solo-maintainer sessions (GH-261).

        Returns an empty string outside the autonomous-shipping profile.

        Pass ``toplevel`` as a pre-resolved string to skip git discovery.
        Pass ``None`` explicitly to return early without git discovery. Omit
        the parameter to let the service run git discovery itself.
        """
        from dev10x.domain.documents.session_yaml import SessionYamlDocument
        from dev10x.domain.git_context import GitContext
        from dev10x.domain.session_rules import BuildAutonomyReassuranceRule

        resolved: str | None = GitContext().toplevel if toplevel is _UNSET else toplevel
        if not resolved:
            return ""
        friction_level, active_modes = SessionYamlDocument(
            toplevel=resolved
        ).read_friction_and_modes()
        return BuildAutonomyReassuranceRule(
            friction_level=friction_level, active_modes=active_modes
        ).apply()

    def build_install_check_context(self) -> str:
        """Return a warning when the Dev10x install needs bootstrap or upgrade.

        Returns an empty string when the install is current.
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

    def build_hook_version_drift_context(self) -> str:
        """Return a warning when the running-hook version lags the latest installed version.

        Returns an empty string when no drift is detected or when either version
        cannot be determined.
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

    def build_compaction_context(self, *, toplevel: str | None = _UNSET) -> str:  # type: ignore[assignment]
        """Return the PreCompact systemMessage string.

        Returns an empty string when no git toplevel is available.

        Pass ``toplevel`` as a pre-resolved string to skip git discovery.
        Pass ``None`` explicitly to return early without git discovery. Omit
        the parameter to let the service run git discovery itself.
        """
        from dev10x.domain.documents.session_context import (
            SessionContextQuery,
            format_compaction_summary,
        )
        from dev10x.domain.git_context import GitContext

        resolved: str | None = GitContext().toplevel if toplevel is _UNSET else toplevel
        if not resolved:
            return ""
        ctx = SessionContextQuery.gather_compaction(toplevel=resolved)
        return format_compaction_summary(ctx=ctx, plugin_root=self._plugin_root)


__all__ = [
    "SessionService",
    "SessionServiceError",
]
