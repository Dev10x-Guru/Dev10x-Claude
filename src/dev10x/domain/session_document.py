"""Session Document I/O — file-backed session state and plan readers.

Document archetype: pure I/O over the persisted session state JSON
and the plan YAML. Callers compose these documents into queries
(``dev10x.domain.documents.session_context.SessionContextQuery``) rather than calling
``json.load`` / ``Path.read_text`` directly.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from dev10x.domain.claude_paths import ClaudeDir
from dev10x.domain.file_locks import atomic_write_text  # noqa: F401


def state_path_for_toplevel(*, toplevel: str) -> Path:
    """Return the persisted session state file for a repo toplevel."""
    project_hash = hashlib.md5(toplevel.encode()).hexdigest()
    return ClaudeDir.session_state_dir() / f"{project_hash}.json"


def plan_path_for_toplevel(*, toplevel: str) -> Path:
    """Return the plan YAML file for a repo toplevel."""
    return Path(toplevel) / ".claude" / "session" / "plan.yaml"


def read_json(*, path: Path) -> dict[str, Any]:
    """Read JSON from path; return empty dict on any error."""
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError, OSError):
        return {}


def claim_state_file(*, path: Path) -> dict[str, Any]:
    """Atomically rename the state file to a PID-scoped name, read, then unlink.

    Ensures a SessionStart hook consumes the persisted state exactly once.
    """
    claimed = path.with_suffix(f".{os.getpid()}.claimed")
    try:
        os.rename(path, claimed)
    except FileNotFoundError:
        return {}
    try:
        return read_json(path=claimed)
    finally:
        claimed.unlink(missing_ok=True)


def write_state(*, path: Path, state: dict[str, Any]) -> None:
    """Atomically write session state JSON, ensuring the parent dir is 0700.

    Uses ``atomic_write_text`` so a concurrent ``SessionStart`` reader can
    never observe a half-written state file: the new contents become
    visible only via the final ``os.rename`` in ``atomic_write_text``,
    matching ``claim_state_file`` on the read side.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    atomic_write_text(path, json.dumps(state, indent=2))


def read_plan_summary(*, toplevel: str) -> dict[str, Any]:
    """Read the persisted plan as a dict via the Plan domain object.

    Direct domain → domain access; the previous lazy import into
    ``dev10x.hooks.task_plan_sync`` inverted the dependency direction
    (domain should never reach into hooks). Hooks compose this query
    via the CLI adapter, not the other way around.
    """
    from dev10x.domain.documents.plan import Plan, get_plan_path

    plan_path = get_plan_path(toplevel=toplevel)
    return Plan.load(path=plan_path).to_dict()


__all__ = [
    "state_path_for_toplevel",
    "plan_path_for_toplevel",
    "read_json",
    "claim_state_file",
    "write_state",
    "read_plan_summary",
]
