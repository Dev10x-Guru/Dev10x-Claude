"""PR and issue label capability (ADR-0027).

Dependencies are reached through ``_gateway.<name>`` (ADR-0027 D2), so a
test patches ``dev10x.github._gateway.<name>`` and intercepts every caller.
"""

from __future__ import annotations

import json
from typing import Any

from dev10x.domain.common.result import ErrorResult, Result, err, ok
from dev10x.github import _gateway

#: Actions :func:`pr_labels` accepts. One tool with an action selector
#: rather than three siblings, mirroring ``pr_comments`` — it keeps a
#: single row in the availability table and one shape to remember.
PR_LABEL_ACTIONS = ("list", "add", "remove")


def _loads_or_empty(raw: str) -> Any:
    """Parse a labels response, degrading to ``[]`` on garbage.

    Only used on the write responses, where the parsed body is a
    convenience — the caller already knows the resulting set from the
    request it just made, so an unparseable body falls back to that
    computed set rather than failing a write that succeeded.
    """
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return []


def _label_names(payload: Any) -> list[str]:
    """Extract label names from a GitHub labels array.

    The labels endpoints answer with an array of label objects, not a
    mapping — so this never goes through :func:`_gh_api`, whose
    ``Result[dict]`` contract would carry the bare list to the MCP
    boundary and die in ``dict(<list of dicts>)`` (the GH-993 failure
    mode). Names are the only field any caller needs.
    """
    if not isinstance(payload, list):
        return []
    return [item["name"] for item in payload if isinstance(item, dict) and "name" in item]


async def _current_label_names(*, resolved_repo: str, pr_number: int) -> Result[list[str]]:
    result = await _gateway._gh_api_raw(
        f"repos/{resolved_repo}/issues/{pr_number}/labels",
        repo=resolved_repo,
    )
    if result.returncode != 0:
        return err(result.stderr.strip())
    try:
        return ok(_label_names(json.loads(result.stdout)))
    except json.JSONDecodeError:
        return err(f"unparseable labels response for {resolved_repo}#{pr_number}")


async def pr_labels(
    *,
    pr_number: int,
    action: str = "list",
    labels: list[str] | None = None,
    repo: str | None = None,
) -> Result[dict[str, Any]]:
    """List, add, or remove labels on a PR (GH-1008).

    The durable-signal surface the stand-by clearance gate needs: a
    `review:cleared` label survives the session that set it, so a later
    session re-entering the gate on the same PR reads the clearance
    instead of re-asking. Labels live on the *issue* side of a PR, hence
    the ``/issues/{n}/labels`` endpoints.

    Idempotent in both directions. ``add`` is naturally so (GitHub
    ignores a label already present); ``remove`` is made so by
    intersecting against the current set first, because
    ``DELETE .../labels/{name}`` 404s on a label that is not attached —
    and a gate clearing a label it never set must not surface that as a
    failure.

    Args:
        pr_number: PR number (its issue number, for label routing).
        action: One of ``list`` / ``add`` / ``remove``.
        labels: Label names. Required for ``add`` and ``remove``,
            ignored for ``list``.
        repo: Repository (owner/repo). Auto-detected if omitted.

    Returns:
        On success: ``{"pr_number": int, "action": str, "labels":
        [name, ...], "changed": [name, ...]}`` where ``labels`` is the
        set after the call and ``changed`` names only what this call
        actually added or removed (empty when the call was a no-op).
    """
    if action not in PR_LABEL_ACTIONS:
        return err(f"unknown action {action!r}; expected one of {list(PR_LABEL_ACTIONS)}")
    if action != "list" and not labels:
        return err(f"action {action!r} needs a non-empty 'labels' list")

    repo_result = await _gateway._resolve_repo(repo)
    if isinstance(repo_result, ErrorResult):
        return repo_result
    resolved_repo = str(repo_result.value)

    current_result = await _current_label_names(resolved_repo=resolved_repo, pr_number=pr_number)
    if isinstance(current_result, ErrorResult):
        return current_result
    current = current_result.value

    if action == "list":
        return ok({"pr_number": pr_number, "action": action, "labels": current, "changed": []})

    requested = list(dict.fromkeys(labels or []))
    if action == "add":
        changed = [name for name in requested if name not in current]
        if not changed:
            return ok({"pr_number": pr_number, "action": action, "labels": current, "changed": []})
        result = await _gateway._gh_api_raw(
            f"repos/{resolved_repo}/issues/{pr_number}/labels",
            method="POST",
            fields={"labels": changed},
            repo=resolved_repo,
        )
        if result.returncode != 0:
            return err(result.stderr.strip())
        return ok(
            {
                "pr_number": pr_number,
                "action": action,
                "labels": _label_names(_loads_or_empty(result.stdout)) or current + changed,
                "changed": changed,
            }
        )

    changed = [name for name in requested if name in current]
    # GH-1446: also the narrow window for the read-modify-write below. A
    # PUT replaces the whole set, so a no-op remove that still issued one
    # could clobber a label another writer added since `current` was read.
    if not changed:
        return ok({"pr_number": pr_number, "action": action, "labels": current, "changed": []})

    # GH-1446: one PUT of the surviving set, mirroring the `add` branch's
    # single POST. The old loop paid a subprocess AND an HTTP round trip
    # per label — a real N+1, on a hot path: `Dev10x:git-groom` clears
    # `review:cleared` after EVERY force-push (GH-1008).
    #
    # The idempotence contract survives: `changed` is already intersected
    # against `current`, so a label that was never attached is absent from
    # `remaining` and no 404 is possible.
    #
    # Trade-off worth knowing: unlike a per-label DELETE, a PUT is a
    # read-modify-write, so a label added by another process between the
    # read above and this write is dropped. The window is one round trip
    # and the only routine writer is git-groom, but this is a lost-update
    # shape — do not widen it by removing the `changed` guard above.
    removing = set(changed)
    remaining = [name for name in current if name not in removing]
    result = await _gateway._gh_api_raw(
        f"repos/{resolved_repo}/issues/{pr_number}/labels",
        method="PUT",
        fields={"labels": remaining},
        repo=resolved_repo,
    )
    if result.returncode != 0:
        return err(result.stderr.strip())
    return ok(
        {
            "pr_number": pr_number,
            "action": action,
            "labels": _label_names(_loads_or_empty(result.stdout)) or remaining,
            "changed": changed,
        }
    )


async def issue_labels(
    *,
    number: int,
    action: str = "list",
    labels: list[str] | None = None,
    repo: str | None = None,
) -> Result[dict[str, Any]]:
    """List, add, or remove labels on an issue (GH-1322).

    Mirrors ``pr_labels`` (GH-1008): one tool with an ``action``
    selector instead of separate add/remove endpoints, on the same
    idempotence contract — ``add`` skips labels already present and
    ``remove`` intersects against the current set first, so clearing a
    label that was never set is a no-op rather than a 404. That
    idempotence is what lets a caller invoke either write
    unconditionally instead of probing first.

    Supersedes ``issue_edit(labels=...)`` for label writes: that
    parameter's docstring claimed "replacement label list" semantics,
    but it only ever calls ``gh issue edit --add-label`` — additive,
    never a replace and never a remove.

    Args:
        number: Issue number.
        action: One of ``list`` / ``add`` / ``remove``.
        labels: Label names. Required for ``add`` and ``remove``,
            ignored for ``list``.
        repo: Repository (owner/repo). Auto-detected if omitted.

    Returns:
        On success: ``{"number": int, "action": str, "labels":
        [name, ...], "changed": [name, ...]}`` where ``labels`` is the
        set after the call and ``changed`` names only what this call
        actually added or removed (empty when the call was a no-op).
    """
    if action not in PR_LABEL_ACTIONS:
        return err(f"unknown action {action!r}; expected one of {list(PR_LABEL_ACTIONS)}")
    if action != "list" and not labels:
        return err(f"action {action!r} needs a non-empty 'labels' list")

    repo_result = await _gateway._resolve_repo(repo)
    if isinstance(repo_result, ErrorResult):
        return repo_result
    resolved_repo = str(repo_result.value)

    current_result = await _current_label_names(resolved_repo=resolved_repo, pr_number=number)
    if isinstance(current_result, ErrorResult):
        return current_result
    current = current_result.value

    if action == "list":
        return ok({"number": number, "action": action, "labels": current, "changed": []})

    requested = list(dict.fromkeys(labels or []))
    if action == "add":
        changed = [name for name in requested if name not in current]
        if not changed:
            return ok({"number": number, "action": action, "labels": current, "changed": []})
        result = await _gateway._gh_api_raw(
            f"repos/{resolved_repo}/issues/{number}/labels",
            method="POST",
            fields={"labels": changed},
            repo=resolved_repo,
        )
        if result.returncode != 0:
            return err(result.stderr.strip())
        return ok(
            {
                "number": number,
                "action": action,
                "labels": _label_names(_loads_or_empty(result.stdout)) or current + changed,
                "changed": changed,
            }
        )

    changed = [name for name in requested if name in current]
    remaining = current
    for name in changed:
        result = await _gateway._gh_api_raw(
            f"repos/{resolved_repo}/issues/{number}/labels/{name}",
            method="DELETE",
            repo=resolved_repo,
        )
        if result.returncode != 0:
            return err(result.stderr.strip())
        remaining = _label_names(_loads_or_empty(result.stdout)) or [
            existing for existing in remaining if existing != name
        ]
    return ok(
        {
            "number": number,
            "action": action,
            "labels": remaining,
            "changed": changed,
        }
    )
