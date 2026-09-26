"""Milestone capability (ADR-0027).

Dependencies are reached through ``_gateway.<name>`` (ADR-0027 D2), so a
test patches ``dev10x.github._gateway.<name>`` and intercepts every caller.
"""

from __future__ import annotations

import json
from typing import Any

from dev10x.domain.common.result import ErrorResult, Result, err, ok
from dev10x.github import _gateway


async def _resolve_milestone_number(
    *,
    milestone: str,
    repo_ref: str,
) -> Result[int]:
    """Resolve a milestone title (or numeric string) to its number.

    The REST endpoint that assigns a milestone takes a number, but
    callers know the title (GH-1098). A numeric string is passed
    through so a caller holding the number does not pay a lookup.
    """
    if milestone.isdigit():
        return ok(int(milestone))

    result = await _gateway._gh_api_raw(f"repos/{repo_ref}/milestones?state=all&per_page=100")
    if result.returncode != 0:
        return err(result.stderr.strip())
    try:
        entries = json.loads(result.stdout)
    except json.JSONDecodeError:
        return err(f"Could not parse milestones for {repo_ref}.")

    for entry in entries:
        if entry.get("title") == milestone:
            return ok(int(entry["number"]))
    return err(
        f"No milestone titled {milestone!r} in {repo_ref}. "
        "Pass the milestone number, or create it with milestone_create."
    )


async def milestone_close(
    *,
    number: int,
    repo: str | None = None,
) -> Result[dict[str, Any]]:
    repo_result = await _gateway._resolve_repo(repo)
    if isinstance(repo_result, ErrorResult):
        return err(repo_result.error)
    repo_ref = repo_result.value

    result = await _gateway._gh_api_raw(
        f"repos/{repo_ref}/milestones/{number}",
        method="PATCH",
        fields={"state": "closed"},
    )

    if result.returncode != 0:
        return err(result.stderr.strip())

    url = f"https://github.com/{repo_ref}/milestone/{number}"
    return ok({"number": number, "state": "closed", "url": url})


async def milestone_create(
    *,
    title: str,
    description: str | None = None,
    due_on: str | None = None,
    repo: str | None = None,
) -> Result[dict[str, Any]]:
    """Create a GitHub milestone (GH-220).

    Wraps ``gh api repos/{r}/milestones --method POST``.

    Args:
        title: Milestone title (required, must be unique within repo).
        description: Optional milestone description.
        due_on: Optional ISO-8601 timestamp for the due date.
        repo: Repository (owner/repo). Auto-detected if omitted.

    Returns:
        On success: ``{"number": int, "title": str, "url": str}``.
    """
    repo_result = await _gateway._resolve_repo(repo)
    if isinstance(repo_result, ErrorResult):
        return err(repo_result.error)
    repo_ref = repo_result.value

    fields: dict[str, str | int | list[str]] = {"title": title}
    if description is not None:
        fields["description"] = description
    if due_on is not None:
        fields["due_on"] = due_on

    result = await _gateway._gh_api_raw(
        f"repos/{repo_ref}/milestones",
        method="POST",
        fields=fields,
    )
    if result.returncode != 0:
        return err(result.stderr.strip())
    try:
        data = json.loads(result.stdout) if result.stdout.strip() else {}
    except json.JSONDecodeError:
        return err(f"Invalid JSON from GitHub API: {result.stdout[:200]}")
    number = int(data.get("number", 0))
    return ok(
        {
            "number": number,
            "title": data.get("title", title),
            "url": f"https://github.com/{repo_ref}/milestone/{number}",
        }
    )


async def milestone_reopen(
    *,
    number: int,
    repo: str | None = None,
) -> Result[dict[str, Any]]:
    """Re-open a closed GitHub milestone (GH-850).

    Symmetric to ``milestone_close``. Wraps
    ``gh api -X PATCH repos/{repo}/milestones/{N} -f state=open``.

    Args:
        number: Milestone number to re-open.
        repo: Repository (owner/repo). Auto-detected if omitted.

    Returns:
        On success: ``{"number": int, "state": "open", "url": str}``.
    """
    repo_result = await _gateway._resolve_repo(repo)
    if isinstance(repo_result, ErrorResult):
        return err(repo_result.error)
    repo_ref = repo_result.value

    result = await _gateway._gh_api_raw(
        f"repos/{repo_ref}/milestones/{number}",
        method="PATCH",
        fields={"state": "open"},
    )

    if result.returncode != 0:
        return err(result.stderr.strip())

    url = f"https://github.com/{repo_ref}/milestone/{number}"
    return ok({"number": number, "state": "open", "url": url})


async def milestone_edit(
    *,
    number: int,
    title: str | None = None,
    description: str | None = None,
    state: str | None = None,
    due_on: str | None = None,
    repo: str | None = None,
) -> Result[dict[str, Any]]:
    """Edit a GitHub milestone's title, description, state, or due date (GH-850).

    Generalizes ``milestone_close``/``milestone_reopen``: wraps
    ``gh api -X PATCH repos/{repo}/milestones/{N}`` with any subset of
    editable fields. Use for renames, description edits, due-date
    changes, or state transitions (``state="open"``/``"closed"``).

    Args:
        number: Milestone number to edit.
        title: New milestone title (optional).
        description: New milestone description (optional).
        state: New state — ``"open"`` or ``"closed"`` (optional).
        due_on: New ISO-8601 due-date timestamp (optional).
        repo: Repository (owner/repo). Auto-detected if omitted.

    Returns:
        On success: ``{"number": int, "title": str, "state": str, "url": str}``.
    """
    if state is not None and state not in ("open", "closed"):
        return err(f"Invalid milestone state {state!r}: must be 'open' or 'closed'.")

    fields: dict[str, str | int | list[str]] = {}
    if title is not None:
        fields["title"] = title
    if description is not None:
        fields["description"] = description
    if state is not None:
        fields["state"] = state
    if due_on is not None:
        fields["due_on"] = due_on

    if not fields:
        return err("milestone_edit requires at least one field to change.")

    repo_result = await _gateway._resolve_repo(repo)
    if isinstance(repo_result, ErrorResult):
        return err(repo_result.error)
    repo_ref = repo_result.value

    result = await _gateway._gh_api_raw(
        f"repos/{repo_ref}/milestones/{number}",
        method="PATCH",
        fields=fields,
    )
    if result.returncode != 0:
        return err(result.stderr.strip())
    try:
        data = json.loads(result.stdout) if result.stdout.strip() else {}
    except json.JSONDecodeError:
        return err(f"Invalid JSON from GitHub API: {result.stdout[:200]}")

    return ok(
        {
            "number": number,
            "title": data.get("title", title),
            "state": data.get("state", state),
            "url": f"https://github.com/{repo_ref}/milestone/{number}",
        }
    )


async def milestone_list(
    *,
    repo: str | None = None,
    state: str = "open",
) -> Result[dict[str, Any]]:
    """List GitHub milestones (GH-1319).

    Wraps ``gh api --paginate repos/{r}/milestones``, the general-purpose
    counterpart to ``triage_roster``'s open-milestone read — GH-1100 E4
    found the roster's only other path was raw ``gh api``, which the
    skill-redirect hook steers away from with nowhere sanctioned to land.

    Args:
        repo: Repository (owner/repo). Auto-detected if omitted.
        state: Filter by state: ``open`` (default), ``closed``, ``all``.

    Returns:
        ``{"milestones": [{number, title, state, description}, ...]}``.
    """
    if state not in ("open", "closed", "all"):
        return err(f"Invalid milestone state {state!r}: must be 'open', 'closed', or 'all'.")

    args = ["gh", "api", "--paginate"]
    if repo:
        path = f"repos/{repo}/milestones?state={state}&per_page=100"
    else:
        # gh expands the {owner}/{repo} placeholders from the CWD's remote.
        path = f"repos/{{owner}}/{{repo}}/milestones?state={state}&per_page=100"
    args.append(path)

    result = await _gateway.async_run(args=args, timeout=30)
    if result.returncode != 0:
        return err(result.stderr.strip())
    try:
        raw_milestones = json.loads(result.stdout) if result.stdout.strip() else []
    except json.JSONDecodeError:
        return err(f"Invalid JSON output from milestone lookup: {result.stdout[:200]}")

    return ok(
        {
            "milestones": [
                {
                    "number": m.get("number"),
                    "title": m.get("title"),
                    "state": m.get("state"),
                    "description": m.get("description") or "",
                }
                for m in raw_milestones
            ],
        }
    )
