from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


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
    tasks: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PlanSummary:
        plan_meta = data.get("plan", {})
        return cls(
            status=plan_meta.get("status", "unknown"),
            branch=plan_meta.get("branch", "unknown"),
            last_synced=plan_meta.get("last_synced", "unknown"),
            context=PlanContext.from_dict(data=plan_meta.get("context", {})),
            tasks=data.get("tasks", []),
        )

    @property
    def pending_tasks(self) -> list[dict[str, Any]]:
        return [t for t in self.tasks if t.get("status") not in ("completed", "deleted")]

    @property
    def pending_decisions(self) -> list[dict[str, Any]]:
        return [t for t in self.pending_tasks if t.get("metadata", {}).get("decision_needed")]

    def format_for_display(self) -> str:
        completed = sum(1 for t in self.tasks if t.get("status") == "completed")
        total = len(self.tasks)
        pending = [
            f"  - [{t.get('status')}] #{t.get('id')} {t.get('subject')}"
            for t in self.pending_tasks
        ]

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
        decisions: list[dict[str, Any]],
    ) -> list[str]:
        lines: list[str] = []
        for t in decisions:
            meta = t.get("metadata", {})
            desc = meta.get("decision_needed", "")
            options = meta.get("options", [])
            line = f"  - #{t.get('id')} {t.get('subject')}: {desc}"
            if options:
                line += f" (options: {', '.join(str(o) for o in options)})"
            lines.append(line)
        return lines

    def format_for_compaction(self) -> str:
        task_lines = []
        for t in self.tasks:
            line = f"- [{t.get('status')}] #{t.get('id')} {t.get('subject')}"
            meta = t.get("metadata", {})
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
