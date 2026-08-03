"""Per-repo ephemeral task index for the park family (GH-1009, ADR-0018 D5).

The park/session skills keep a local index of deferred work — park items,
Slack-reminder pointers, PR bookmarks, and the wrap-up continuation prompt —
so ``Dev10x:park-discover`` can surface them without scanning every write
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

import logging
import os
from pathlib import Path
from typing import Any

import yaml

from dev10x.domain.common.result import ErrorResult, Result, err, ok
from dev10x.domain.dev10x_paths import Dev10xConfigDir
from dev10x.domain.file_locks import locked_yaml_update
from dev10x.session.preset_pin import RepoIdentity, resolve_repo_identity
from dev10x.subprocess_utils import effective_cwd

log = logging.getLogger(__name__)

#: Retired location, still read when the rehomed store is absent. Kept for
#: one release so an existing checkout's parked items are not silently lost;
#: `Dev10x:plugin-doctor` deletes it once parity is confirmed.
LEGACY_RELATIVE_PATH = Path(".claude") / "Dev10x" / "session.yaml"

#: Keys the task index owns. Anything else in a legacy file belongs to the
#: retired durable-prefs/gate-identity roles and is deliberately NOT carried
#: forward — folding `friction_level` in here would resurrect the very
#: ambiguity GH-1001 removed.
INDEX_KEYS = ("tasks", "continuation_prompt", "insights", "branch", "tickets", "wrapped_at")

__all__ = [
    "INDEX_KEYS",
    "LEGACY_RELATIVE_PATH",
    "append_task",
    "read_index",
    "set_session_state",
]


def _identity(*, cwd: str | None) -> Result[RepoIdentity]:
    return resolve_repo_identity(cwd=cwd)


def _store_path(identity: RepoIdentity) -> Path:
    return Dev10xConfigDir.task_index_yaml(repo_name=identity["name"])


def _legacy_candidates(*, identity: RepoIdentity, cwd: str | None) -> list[Path]:
    """Legacy files worth reading, most-specific first.

    The retired store was per-*checkout*, so a repo with worktrees may hold
    several. Probe the invocation's own tree before the main checkout: an item
    parked from this worktree is the one the caller most likely expects back.
    """
    roots: list[str] = []
    # An explicit `cwd` wins, then the bound effective CWD, and only then the
    # process CWD (GH-979). A bare `os.getcwd()` here would probe the
    # long-lived MCP server's startup directory whenever the caller passed no
    # cwd, so a park in a worktree would look for its legacy file under
    # whatever tree the daemon happened to start in.
    invocation = cwd or effective_cwd() or os.getcwd()
    for root in (invocation, identity["root"]):
        if root and root not in roots:
            roots.append(root)
    return [Path(root) / LEGACY_RELATIVE_PATH for root in roots]


def _read_legacy(*, identity: RepoIdentity, cwd: str | None) -> tuple[dict[str, Any], Path | None]:
    """Return index-owned keys from the first readable legacy file.

    A malformed legacy file yields empty content rather than raising: it is a
    best-effort fallback on a path nothing writes any more, and failing the
    read would block the caller from parking anything new.
    """
    for candidate in _legacy_candidates(identity=identity, cwd=cwd):
        if not candidate.is_file():
            continue
        try:
            loaded = yaml.safe_load(candidate.read_text()) or {}
        except (yaml.YAMLError, OSError) as exc:
            log.debug("legacy task index unreadable: %s", candidate, exc_info=exc)
            continue
        if not isinstance(loaded, dict):
            continue
        carried = {key: loaded[key] for key in INDEX_KEYS if key in loaded}
        if carried:
            return carried, candidate
    return {}, None


def read_index(*, cwd: str | None = None) -> Result[dict[str, Any]]:
    """Read the repo's task index, falling back to the retired location.

    ``legacy_read`` tells the caller the content came from the retired
    per-checkout file and has not been rehomed yet — the next write folds it
    forward. ``Dev10x:park-discover`` surfaces this so a supervisor can see
    why an item is still living in the old place.
    """
    identity_result = _identity(cwd=cwd)
    if isinstance(identity_result, ErrorResult):
        return err(identity_result.error)
    identity = identity_result.value

    path = _store_path(identity)
    if path.is_file():
        try:
            content = yaml.safe_load(path.read_text()) or {}
        except (yaml.YAMLError, OSError) as exc:
            return err(f"task index at {path} is unreadable: {exc}")
        if not isinstance(content, dict):
            return err(f"task index at {path} is not a mapping")
        return ok(_payload(identity=identity, path=path, content=content, legacy_path=None))

    carried, legacy_path = _read_legacy(identity=identity, cwd=cwd)
    return ok(_payload(identity=identity, path=path, content=carried, legacy_path=legacy_path))


def _payload(
    *,
    identity: RepoIdentity,
    path: Path,
    content: dict[str, Any],
    legacy_path: Path | None,
) -> dict[str, Any]:
    return {
        "path": str(path),
        "repo_name": identity["name"],
        "exists": path.is_file(),
        "legacy_read": legacy_path is not None,
        "legacy_path": str(legacy_path) if legacy_path else None,
        "tasks": content.get("tasks") or [],
        "continuation_prompt": content.get("continuation_prompt"),
        "insights": content.get("insights") or [],
        "branch": content.get("branch"),
        "tickets": content.get("tickets") or [],
        "wrapped_at": content.get("wrapped_at"),
    }


def _fold_legacy_forward(
    *,
    data: dict[str, Any],
    identity: RepoIdentity,
    cwd: str | None,
) -> Path | None:
    """Seed an empty store from the retired file, inside the write lock.

    Without this, the first append after the rehome would write a store
    holding only the new entry and orphan everything parked before it. Runs
    under the caller's lock, so two racing appends cannot both seed.
    """
    if data:
        return None
    carried, legacy_path = _read_legacy(identity=identity, cwd=cwd)
    data.update(carried)
    return legacy_path


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
    with locked_yaml_update(path) as data:
        folded = _fold_legacy_forward(data=data, identity=identity, cwd=cwd)
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

    if malformed:
        return err(f"task index at {path} has a non-list 'tasks' key")

    return ok(
        {
            "path": str(path),
            "repo_name": identity["name"],
            "task_count": count,
            "folded_legacy": str(folded) if folded else None,
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
    with locked_yaml_update(path) as data:
        folded = _fold_legacy_forward(data=data, identity=identity, cwd=cwd)
        data.setdefault("repo", identity["name"])
        data.update(supplied)

    return ok(
        {
            "path": str(path),
            "repo_name": identity["name"],
            "updated_keys": sorted(supplied),
            "folded_legacy": str(folded) if folded else None,
        }
    )
