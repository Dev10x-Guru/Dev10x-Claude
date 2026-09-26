"""Bulk milestone and issue capability (ADR-0027).

Sibling capabilities are reached as module attributes (ADR-0027 D2), so a
test patches ``dev10x.github.issues.issue_create`` or
``dev10x.github.milestones.milestone_create`` and intercepts the bulk
path too. The modules are aliased because ``milestones`` and ``issues``
are also the batch parameter names.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from dev10x.domain.common.result import ErrorResult, Result, err, ok
from dev10x.github import issues as issue_ops
from dev10x.github import milestones as milestone_ops


async def _bulk_execute(
    *,
    entries: list[dict[str, Any]],
    empty_error: str,
    identity_key: str,
    result_key: str,
    validate: Callable[[dict[str, Any]], str | None],
    perform: Callable[[dict[str, Any]], Awaitable[Result[dict[str, Any]]]],
    on_success: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]] | None = None,
) -> Result[dict[str, Any]]:
    """Run a per-entry GitHub operation across a batch (GH-222, GH-583).

    Shared skeleton for the ``*_bulk_*`` wrappers: guard the empty
    batch, iterate without short-circuiting, and split outcomes into
    ``result_key`` (successes) and ``failed`` so the caller sees the
    full batch result.

    Args:
        entries: Batch of per-operation dicts.
        empty_error: Error returned when ``entries`` is empty.
        identity_key: Field naming an entry in its ``failed`` record
            (e.g. ``"title"`` or ``"number"``).
        result_key: Key holding the successes (e.g. ``"created"``).
        validate: Returns an error message for an invalid entry, or
            ``None`` when the entry is well-formed.
        perform: Runs the per-entry operation, returning a ``Result``.
        on_success: Optional post-processor for a success payload
            (e.g. to backfill a field the per-entry call omits).
    """
    if not entries:
        return err(empty_error)

    succeeded: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    for entry in entries:
        validation_error = validate(entry)
        if validation_error is not None:
            failed.append({identity_key: entry.get(identity_key), "error": validation_error})
            continue
        result = await perform(entry)
        if isinstance(result, ErrorResult):
            failed.append({identity_key: entry.get(identity_key), "error": result.error})
        else:
            value = on_success(entry, result.value) if on_success else result.value
            succeeded.append(value)
    return ok({result_key: succeeded, "failed": failed})


async def milestones_bulk_create(
    *,
    milestones: list[dict[str, Any]],
    repo: str | None = None,
) -> Result[dict[str, Any]]:
    """Create multiple GitHub milestones in one call (GH-222).

    Iterates milestone_create per entry; collects per-milestone
    successes and failures. The call does not short-circuit on
    individual failures so the caller sees the full batch outcome.

    Args:
        milestones: List of dicts; each entry accepts ``title`` (required),
            ``description`` (optional), and ``due_on`` (optional).
        repo: Repository (owner/repo). Auto-detected if omitted.

    Returns:
        On success: ``{"created": [{title, number, url}, ...],
        "failed": [{title, error}, ...]}``. The wrapper never
        errors as long as at least one entry was attempted; entry-
        level failures land in ``failed``.
    """
    return await _bulk_execute(
        entries=milestones,
        empty_error="milestones_bulk_create requires at least one milestone",
        identity_key="title",
        result_key="created",
        validate=lambda entry: None if entry.get("title") else "missing title",
        perform=lambda entry: milestone_ops.milestone_create(
            title=entry["title"],
            description=entry.get("description"),
            due_on=entry.get("due_on"),
            repo=repo,
        ),
    )


async def issues_bulk_create(
    *,
    issues: list[dict[str, Any]],
    repo: str | None = None,
) -> Result[dict[str, Any]]:
    """Create multiple GitHub issues in one call (GH-222).

    Iterates issue_create per entry; collects per-issue successes
    and failures. Use for batch project scaffolding (e.g.,
    Dev10x:project-scope creating N tickets).

    Args:
        issues: List of dicts; each entry accepts ``title`` (required),
            ``body`` (optional), ``labels`` (optional list of str),
            ``milestone`` (optional).
        repo: Repository (owner/repo). Auto-detected if omitted.

    Returns:
        ``{"created": [{number, url, title}, ...],
        "failed": [{title, error}, ...]}``.
    """

    def _backfill_title(entry: dict[str, Any], value: dict[str, Any]) -> dict[str, Any]:
        payload = dict(value)
        payload.setdefault("title", entry["title"])
        return payload

    return await _bulk_execute(
        entries=issues,
        empty_error="issues_bulk_create requires at least one issue",
        identity_key="title",
        result_key="created",
        validate=lambda entry: None if entry.get("title") else "missing title",
        perform=lambda entry: issue_ops.issue_create(
            title=entry["title"],
            body=entry.get("body"),
            labels=entry.get("labels"),
            milestone=entry.get("milestone"),
            repo=repo,
        ),
        on_success=_backfill_title,
    )


async def issues_bulk_edit(
    *,
    edits: list[dict[str, Any]],
    repo: str | None = None,
) -> Result[dict[str, Any]]:
    """Edit multiple GitHub issues in one call (GH-222).

    Iterates issue_edit per entry; collects per-issue successes
    and failures. Use for batch milestone reassignment, label
    additions, or title/body fixes across many issues.

    Args:
        edits: List of dicts; each entry requires ``number`` and at
            least one of ``title``, ``body``, ``milestone``, ``labels``.
        repo: Repository (owner/repo). Auto-detected if omitted.

    Returns:
        ``{"edited": [{number, url}, ...],
        "failed": [{number, error}, ...]}``.
    """
    return await _bulk_execute(
        entries=edits,
        empty_error="issues_bulk_edit requires at least one edit",
        identity_key="number",
        result_key="edited",
        validate=lambda entry: (
            None if isinstance(entry.get("number"), int) else "missing or non-integer number"
        ),
        perform=lambda entry: issue_ops.issue_edit(
            number=entry["number"],
            title=entry.get("title"),
            body=entry.get("body"),
            milestone=entry.get("milestone"),
            labels=entry.get("labels"),
            repo=repo,
        ),
    )
