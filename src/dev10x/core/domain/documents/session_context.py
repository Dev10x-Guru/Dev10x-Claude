"""SessionContextQuery — single source of truth for session-context assembly.

Query archetype: gathers the data both ``session_reload`` (SessionStart
additionalContext) and ``context_compact`` (PreCompact systemMessage)
need into one dataclass. Eliminates the duplicated multi-context
assembly previously inlined in ``build_reload_context`` and
``context_compact`` (audit memo Finding I3).
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from dev10x.domain.documents.session_state import PlanSummary, SessionState
from dev10x.domain.documents.session_yaml import SessionYamlDocument
from dev10x.domain.friction_level import FrictionLevel
from dev10x.domain.git_context import GitContext
from dev10x.domain.session_document import (
    claim_state_file,
    plan_path_for_toplevel,
    read_plan_summary,
    state_path_for_toplevel,
)
from dev10x.domain.session_rules import DecisionGuidanceRule


def _run_git_safe(git: GitContext, *args: str) -> str:
    try:
        return git.run(*args)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


@dataclass(frozen=True)
class SessionContextQuery:
    """Aggregated session context for reload + compaction hooks."""

    toplevel: str
    branch: str = "unknown"
    worktree_name: str = ""
    session_state: SessionState | None = None
    plan_exists: bool = False
    plan: PlanSummary | None = None
    friction_level: FrictionLevel = field(default_factory=FrictionLevel.default)
    modified_files: list[str] = field(default_factory=list)
    staged_files: list[str] = field(default_factory=list)
    untracked_files: list[str] = field(default_factory=list)
    recent_commits: str = ""

    @classmethod
    def gather_reload(cls, *, toplevel: str) -> SessionContextQuery:
        """Gather context for SessionStart reload — consumes state file once."""
        state = claim_state_file(path=state_path_for_toplevel(toplevel=toplevel))
        plan_path = plan_path_for_toplevel(toplevel=toplevel)
        plan_exists = plan_path.exists()
        plan = (
            PlanSummary.from_dict(data=read_plan_summary(toplevel=toplevel))
            if plan_exists
            else None
        )
        friction_level = SessionYamlDocument(toplevel=toplevel).read_friction_level()

        return cls(
            toplevel=toplevel,
            session_state=SessionState.from_dict(data=state) if state else None,
            plan_exists=plan_exists,
            plan=plan,
            friction_level=friction_level,
        )

    @classmethod
    def gather_compaction(cls, *, toplevel: str) -> SessionContextQuery:
        """Gather context for PreCompact — reads git state, plan, friction."""
        git = GitContext(cwd=toplevel)
        branch = git.branch

        worktree_name = ""
        if (Path(toplevel) / ".git").is_file():
            worktree_name = Path(toplevel).name

        modified = _run_git_safe(git, "diff", "--name-only").splitlines()[:20]
        staged = _run_git_safe(git, "diff", "--cached", "--name-only").splitlines()[:20]
        untracked = _run_git_safe(git, "ls-files", "--others", "--exclude-standard").splitlines()[
            :10
        ]
        recent_commits = _run_git_safe(git, "log", "--oneline", "-5")

        plan_path = plan_path_for_toplevel(toplevel=toplevel)
        plan_exists = plan_path.exists()
        plan = (
            PlanSummary.from_dict(data=read_plan_summary(toplevel=toplevel))
            if plan_exists
            else None
        )
        friction_level = SessionYamlDocument(toplevel=toplevel).read_friction_level()

        return cls(
            toplevel=toplevel,
            branch=branch,
            worktree_name=worktree_name,
            plan_exists=plan_exists,
            plan=plan,
            friction_level=friction_level,
            modified_files=modified,
            staged_files=staged,
            untracked_files=untracked,
            recent_commits=recent_commits,
        )


def _format_files(*, files: list[str]) -> str:
    return "\n".join(f"- {f}" for f in files if f)


def format_reload_context(*, ctx: SessionContextQuery) -> str:
    """Render a SessionContextQuery as the SessionStart additionalContext."""

    if ctx.session_state is None and ctx.plan is None:
        return ""

    parts: list[str] = []
    if ctx.session_state is not None:
        state_text = ctx.session_state.format_for_display()
        if state_text:
            parts.append(state_text)
    if ctx.plan is not None:
        plan_text = ctx.plan.format_for_display()
        if plan_text:
            parts.append(plan_text)
        guidance = DecisionGuidanceRule(plan=ctx.plan, friction_level=ctx.friction_level).apply()
        if guidance:
            parts.append(guidance)
    return "\n\n".join(parts)


def format_compaction_summary(*, ctx: SessionContextQuery, plugin_root: Path) -> str:
    """Render a SessionContextQuery as the PreCompact systemMessage body."""

    essentials_file = plugin_root / ".claude" / "rules" / "essentials.md"
    essentials = essentials_file.read_text() if essentials_file.exists() else ""

    summary = f"# Post-Compaction Context Recovery\n\n## Git State\n- **Branch:** {ctx.branch}"
    if ctx.worktree_name:
        summary += f"\n- **Worktree:** {ctx.worktree_name}"
    summary += f"\n- **Working directory:** {ctx.toplevel}"
    if ctx.modified_files:
        summary += f"\n\n### Modified files (unstaged)\n{_format_files(files=ctx.modified_files)}"
    if ctx.staged_files:
        summary += f"\n\n### Staged files\n{_format_files(files=ctx.staged_files)}"
    if ctx.untracked_files:
        summary += f"\n\n### Untracked files\n{_format_files(files=ctx.untracked_files)}"
    if ctx.recent_commits:
        summary += f"\n\n### Recent commits\n```\n{ctx.recent_commits}\n```"
    if essentials:
        summary += f"\n\n## Essential Conventions (from essentials.md)\n{essentials}"

    if ctx.plan is not None:
        summary += "\n\n" + ctx.plan.format_for_compaction()
        if not ctx.plan.context.routing_table:
            recovery_file = plugin_root / "references" / "compaction-recovery.md"
            if recovery_file.exists():
                summary += f"\n\n{recovery_file.read_text()}"
        guidance = DecisionGuidanceRule(plan=ctx.plan, friction_level=ctx.friction_level).apply()
        if guidance:
            summary += f"\n\n### Resume Guidance\n{guidance}"
        summary += (
            "\n\n> Reconstructed from persisted plan file. Use TaskList to verify\n"
            "> current session state. If tasks are missing, recreate them from\n"
            "> this list. Use the routing table above for all shipping actions."
        )
    return summary


__all__ = ["SessionContextQuery", "format_reload_context", "format_compaction_summary"]
