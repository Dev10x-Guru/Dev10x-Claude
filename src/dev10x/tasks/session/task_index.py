"""Per-repo ephemeral task index for the park family (GH-1009, ADR-0018 D5).

The park/session skills keep a local index of deferred work — park items,
Slack-reminder pointers, PR bookmarks, and the wrap-up continuation prompt —
so ``dev10x:park-discover`` can surface them without scanning every write
path. That index used to live at ``.claude/Dev10x/session.yaml``.

ADR-0018 D2 retired that path, but only the *durable preferences* and *gate
identity* readers were repointed (GH-1001); five skills kept writing the task
index there. That is not a benign exception: every one of them reached the
file with the **Write/Edit tool**, which is exactly what trips Claude Code's
self-settings consent gate — a tool phenomenon that no allow rule can
suppress (ADR-0018 RC-A). So the store moves out of the repo entirely, and
this module becomes its only writer, reached through MCP tools so the write
happens in the server process (the plan-sync precedent ADR-0018 cites).

**Repo-scoped, not worktree-scoped.** The index is keyed off the git common
dir via :func:`~dev10x.session.preset_pin.resolve_repo_identity`, so an item
parked in ``Dev10x-Claude-1`` resurfaces in ``Dev10x-Claude`` and in a
worktree created next month. Keying on the invocation CWD would strand each
deferral in the checkout that happened to create it, which is the opposite of
what "resurfaces next session in the same project" promises.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from dev10x.domain.common.result import ErrorResult, Result, err, ok
from dev10x.domain.dev10x_paths import Dev10xConfigDir
from dev10x.domain.file_locks import CorruptYamlError, locked_yaml_update
from dev10x.session.preset_pin import RepoIdentity, resolve_repo_identity

__all__ = [
    "append_task",
    "read_index",
    "set_session_state",
]


def _identity(*, cwd: str | None) -> Result[RepoIdentity]:
    return resolve_repo_identity(cwd=cwd)


def _store_path(identity: RepoIdentity) -> Path:
    return Dev10xConfigDir.task_index_yaml(repo_name=identity["name"])


def read_index(*, cwd: str | None = None) -> Result[dict[str, Any]]:
    """Read the repo's task index.

    The retired per-checkout ``.claude/Dev10x/session.yaml`` is not consulted:
    its read fallback was removed in 0.112.0 (GH-1771).
    """
    identity_result = _identity(cwd=cwd)
    if isinstance(identity_result, ErrorResult):
        return err(identity_result.error)
    identity = identity_result.value

    path = _store_path(identity)
    content: dict[str, Any] = {}
    if path.is_file():
        try:
            content = yaml.safe_load(path.read_text()) or {}
        except (yaml.YAMLError, OSError) as exc:
            return err(f"task index at {path} is unreadable: {exc}")
        if not isinstance(content, dict):
            return err(f"task index at {path} is not a mapping")
    return ok(_payload(identity=identity, path=path, content=content))


def _payload(
    *,
    identity: RepoIdentity,
    path: Path,
    content: dict[str, Any],
) -> dict[str, Any]:
    return {
        "path": str(path),
        "repo_name": identity["name"],
        "exists": path.is_file(),
        "tasks": content.get("tasks") or [],
        "continuation_prompt": content.get("continuation_prompt"),
        "insights": content.get("insights") or [],
        "branch": content.get("branch"),
        "tickets": content.get("tickets") or [],
        "wrapped_at": content.get("wrapped_at"),
    }


def append_task(*, entry: dict[str, Any], cwd: str | None = None) -> Result[dict[str, Any]]:
    """Append one entry to the repo's task index.

    ``entry`` is the park-family task shape (``subject``, ``status``,
    ``source``, optional ``metadata``). ``subject`` and ``source`` are
    required: an entry without a source cannot be attributed in
    ``park-discover``'s per-writer report, and one without a subject cannot be
    rendered at all.
    """
    missing = [field for field in ("subject", "source") if not entry.get(field)]
    if missing:
        return err(f"task entry is missing required field(s): {', '.join(missing)}")

    identity_result = _identity(cwd=cwd)
    if isinstance(identity_result, ErrorResult):
        return err(identity_result.error)
    identity = identity_result.value

    path = _store_path(identity)
    malformed = False
    try:
        with locked_yaml_update(path) as data:
            data.setdefault("repo", identity["name"])
            tasks = data.setdefault("tasks", [])
            # Guard rather than append blindly: a hand-edited `tasks:` scalar would
            # otherwise raise inside the lock, and an exception escaping the
            # context manager skips the write-back, leaving the sidecar lock as the
            # only trace of the failure.
            malformed = not isinstance(tasks, list)
            if not malformed:
                tasks.append(dict(entry))
                count = len(tasks)
    except CorruptYamlError as exc:
        # ADR-0009: an unreadable store is an operational failure the caller
        # branches on, not an exception that escapes the domain boundary.
        return err(str(exc))

    if malformed:
        return err(f"task index at {path} has a non-list 'tasks' key")

    return ok(
        {
            "path": str(path),
            "repo_name": identity["name"],
            "task_count": count,
        }
    )


def set_session_state(
    *,
    continuation_prompt: str | None = None,
    insights: list[str] | None = None,
    branch: str | None = None,
    tickets: list[str] | None = None,
    wrapped_at: str | None = None,
    cwd: str | None = None,
) -> Result[dict[str, Any]]:
    """Write the wrap-up state onto the repo's task index.

    Only supplied keys are written, so a caller refreshing the continuation
    prompt cannot blank the parked ``tasks`` list. ``wrapped_at`` is passed in
    rather than stamped here — the caller owns the clock, keeping this
    function deterministic under test.

    The ``branch``/``tickets`` pair is a wrap-up **record**, not a gate input:
    the session-adoption gate reads identity from plan-sync (ADR-0018 D2), so
    writing it here influences ``park-discover``'s live-or-stale
    classification (GH-782) and nothing else.
    """
    updates = {
        "continuation_prompt": continuation_prompt,
        "insights": insights,
        "branch": branch,
        "tickets": tickets,
        "wrapped_at": wrapped_at,
    }
    supplied = {key: value for key, value in updates.items() if value is not None}
    if not supplied:
        return err("set_session_state needs at least one field to write")

    identity_result = _identity(cwd=cwd)
    if isinstance(identity_result, ErrorResult):
        return err(identity_result.error)
    identity = identity_result.value

    path = _store_path(identity)
    try:
        with locked_yaml_update(path) as data:
            data.setdefault("repo", identity["name"])
            data.update(supplied)
    except CorruptYamlError as exc:
        return err(str(exc))

    return ok(
        {
            "path": str(path),
            "repo_name": identity["name"],
            "updated_keys": sorted(supplied),
        }
    )
