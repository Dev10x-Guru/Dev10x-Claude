from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dev10x.domain.documents.task import Task, TaskStatus


@dataclass(frozen=True)
class SessionState:
    timestamp: str = ""
    branch: str = "unknown"
    worktree: str = ""
    session_id: str = ""
    modified_files: list[str] = field(default_factory=list)
    staged_files: list[str] = field(default_factory=list)
    recent_commits: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionState:
        return cls(
            timestamp=data.get("timestamp", ""),
            branch=data.get("branch", "unknown"),
            worktree=data.get("worktree", ""),
            session_id=data.get("session_id", ""),
            modified_files=data.get("modified_files", []),
            staged_files=data.get("staged_files", []),
            recent_commits=data.get("recent_commits", []),
        )

    @classmethod
    def capture(
        cls,
        *,
        session_id: str,
        toplevel: str,
        run_git: Callable[..., str],
        timestamp: str,
    ) -> SessionState:
        """Build a `SessionState` from the live working tree.

        `run_git` is injected (e.g. the SessionStop hook's `_run_git`)
        so this domain object stays free of subprocess access — the
        adapter owns the git invocation, the aggregate owns the field
        shape. File lists are capped at 20 entries to bound the
        persisted payload.
        """
        worktree = Path(toplevel).name if (Path(toplevel) / ".git").is_file() else ""
        return cls(
            timestamp=timestamp,
            branch=run_git("rev-parse", "--abbrev-ref", "HEAD") or "unknown",
            worktree=worktree,
            session_id=session_id,
            modified_files=run_git("diff", "--name-only").splitlines()[:20],
            staged_files=run_git("diff", "--cached", "--name-only").splitlines()[:20],
            recent_commits=run_git("log", "--oneline", "-5").splitlines(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "branch": self.branch,
            "worktree": self.worktree,
            "session_id": self.session_id,
            "modified_files": self.modified_files,
            "staged_files": self.staged_files,
            "recent_commits": self.recent_commits,
        }

    def _age_hours(self) -> int:
        if not self.timestamp:
            return 0
        try:
            file_dt = datetime.fromisoformat(self.timestamp)
            now_dt = datetime.now(UTC)
            return int((now_dt - file_dt).total_seconds() / 3600)
        except (ValueError, TypeError):
            return 0

    def format_for_display(self) -> str:
        if not self.timestamp:
            return ""

        age = self._age_hours()
        stale = f" (STALE — {age}h old, may be outdated)" if age > 24 else ""

        def _file_list(files: list[str]) -> str:
            return "\n".join(f"- {f}" for f in files) if files else "none"

        lines = [f"Prior session state detected{stale}:", f"- Branch: {self.branch}"]
        if self.worktree:
            lines.append(f"- Worktree: {self.worktree}")
        lines.append(f"- Last active: {self.timestamp}")
        lines.append(f"- Session ID: {self.session_id}")
        lines.append(f"\nModified files:\n{_file_list(self.modified_files)}")
        lines.append(f"\nStaged files:\n{_file_list(self.staged_files)}")
        commits = "\n".join(self.recent_commits) if self.recent_commits else "none"
        lines.append(f"\nRecent commits:\n{commits}")
        lines.append(f"\nResume prior session with: claude --resume {self.session_id}")
        return "\n".join(lines)


@dataclass(frozen=True)
class PlanContext:
    work_type: str = ""
    tickets: list[str] = field(default_factory=list)
    routing_table: dict[str, str] = field(default_factory=dict)
    gathered_summary: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PlanContext:
        tickets_raw = data.get("tickets", [])
        tickets = tickets_raw if isinstance(tickets_raw, list) else [tickets_raw]
        routing = data.get("routing_table", {})
        return cls(
            work_type=data.get("work_type", ""),
            tickets=tickets,
            routing_table=routing if isinstance(routing, dict) else {},
            gathered_summary=data.get("gathered_summary", ""),
        )


@dataclass(frozen=True)
class PlanSummary:
    status: str = "unknown"
    branch: str = "unknown"
    last_synced: str = "unknown"
    context: PlanContext = field(default_factory=PlanContext)
    tasks: list[Task] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Tolerate raw-dict task inputs from legacy callers and tests
        # that construct PlanSummary directly. Frozen dataclass requires
        # `object.__setattr__` to mutate the field.
        normalized: list[Task] = []
        for item in self.tasks:
            if isinstance(item, Task):
                normalized.append(item)
            elif isinstance(item, dict):
                normalized.append(Task.from_dict(item))
        object.__setattr__(self, "tasks", normalized)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PlanSummary:
        plan_meta = data.get("plan", {})
        raw_tasks = data.get("tasks", []) or []
        tasks = [Task.from_dict(t) for t in raw_tasks if isinstance(t, dict)]
        return cls(
            status=plan_meta.get("status", "unknown"),
            branch=plan_meta.get("branch", "unknown"),
            last_synced=plan_meta.get("last_synced", "unknown"),
            context=PlanContext.from_dict(data=plan_meta.get("context", {})),
            tasks=tasks,
        )

    @property
    def pending_tasks(self) -> list[Task]:
        return [
            t for t in self.tasks if t.status not in (TaskStatus.COMPLETED, TaskStatus.DELETED)
        ]

    @property
    def has_remaining_tasks(self) -> bool:
        return bool(self.pending_tasks)

    @property
    def pending_decisions(self) -> list[Task]:
        return [t for t in self.pending_tasks if t.metadata.get("decision_needed")]

    def format_for_display(self) -> str:
        completed = sum(1 for t in self.tasks if t.status is TaskStatus.COMPLETED)
        total = len(self.tasks)
        pending = [f"  - [{t.status.value}] #{t.id} {t.subject}" for t in self.pending_tasks]

        lines = [f"Persisted plan detected ({completed}/{total} tasks completed):"]
        lines.append(f"- Plan branch: {self.branch}")
        lines.append(f"- Plan status: {self.status}")
        lines.append(f"- Last synced: {self.last_synced}")

        if pending:
            lines.append("- Remaining tasks:\n" + "\n".join(pending))

        decisions = self.pending_decisions
        if decisions:
            decision_lines = self._format_pending_decisions(decisions=decisions)
            lines.append("- Pending decisions:\n" + "\n".join(decision_lines))

        if self.context.work_type:
            lines.append(f"- Work type: {self.context.work_type}")
        if self.context.tickets:
            lines.append(f"- Tickets: {', '.join(self.context.tickets)}")
        if self.context.routing_table:
            routing_lines = [f"  {k} → {v}" for k, v in self.context.routing_table.items()]
            lines.append("- Skill routing:\n" + "\n".join(routing_lines))
        if self.status == "completed":
            lines.append("- All tasks completed. Plan can be archived.")

        return "\n".join(lines)

    @staticmethod
    def _format_pending_decisions(
        *,
        decisions: list[Task],
    ) -> list[str]:
        lines: list[str] = []
        for t in decisions:
            desc = t.metadata.get("decision_needed", "")
            options = t.metadata.get("options", [])
            line = f"  - #{t.id} {t.subject}: {desc}"
            if options:
                line += f" (options: {', '.join(str(o) for o in options)})"
            lines.append(line)
        return lines

    def format_for_compaction(self) -> str:
        task_lines = []
        for t in self.tasks:
            line = f"- [{t.status.value}] #{t.id} {t.subject}"
            meta = t.metadata
            if meta.get("type"):
                line += f" ({meta['type']})"
            if meta.get("skills"):
                line += f" → {', '.join(meta['skills'])}"
            if meta.get("decision_needed"):
                line += f" ⚠️ DECISION NEEDED: {meta['decision_needed']}"
            task_lines.append(line)

        lines = []
        lines.append(f"\n- **Branch:** {self.branch}")
        lines.append(f"\n- **Plan status:** {self.status}")
        lines.append(f"\n- **Work type:** {self.context.work_type}")

        if task_lines:
            lines.append("\n\n### Tasks\n" + "\n".join(task_lines))

        decisions = self.pending_decisions
        if decisions:
            decision_lines = self._format_pending_decisions(decisions=decisions)
            lines.append(
                "\n\n### Pending Decisions (queued before stop/compaction)\n"
                + "\n".join(decision_lines)
            )

        if self.context.routing_table:
            routing_lines = [f"{k} → {v}" for k, v in self.context.routing_table.items()]
            lines.append(
                "\n\n### Skill Routing Table (from plan context)\n" + "\n".join(routing_lines)
            )
        if self.context.gathered_summary:
            lines.append(
                f"\n\n### Gathered Context (from Phase 2)\n{self.context.gathered_summary}"
            )

        return "## Persisted Plan State" + "".join(lines)
