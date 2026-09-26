"""Issue capability (ADR-0027).

Dependencies are reached through ``_gateway.<name>`` (ADR-0027 D2), so a
test patches ``dev10x.github._gateway.<name>`` and intercepts every caller.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from dev10x.domain.common.result import ErrorResult, Result, SuccessResult, err, ok
from dev10x.github import _gateway
from dev10x.subprocess_utils import parse_key_value_output


async def issue_get(
    *,
    number: int,
    repo: str | None = None,
) -> Result[dict[str, Any]]:
    args = [str(number)]
    if repo:
        args.append(repo)
    return await _gateway._run_and_parse(
        "skills/gh-context/scripts/gh-issue-get.sh",
        *args,
        fallback=parse_key_value_output,
    )


async def issue_comments(
    *,
    number: int,
    repo: str | None = None,
) -> Result[dict[str, Any]]:
    args = [str(number)]
    if repo:
        args.append(repo)
    return await _gateway._run_and_parse(
        "skills/gh-context/scripts/gh-issue-comments.sh",
        *args,
    )


async def issue_create(
    *,
    title: str,
    body: str | None = None,
    labels: list[str] | None = None,
    milestone: str | None = None,
    repo: str | None = None,
) -> Result[dict[str, Any]]:
    args = [title]
    if body:
        args.extend(["--body", body])
    if labels:
        for label in labels:
            args.extend(["--label", label])
    if milestone:
        args.extend(["--milestone", milestone])
    if repo:
        args.extend(["--repo", repo])
    return await _gateway._run_and_parse(
        "skills/gh-context/scripts/gh-issue-create.sh",
        *args,
        fallback=parse_key_value_output,
    )


async def _issue_result(
    *,
    number: int,
    raw_url: str,
    repo: str | None,
    state: str | None = None,
) -> dict[str, Any]:
    """Assemble the ``{number, [state], url}`` payload for issue mutations.

    Resolves the canonical issue URL from ``repo``; when the repo cannot
    be resolved the ``gh`` command's own stdout (``raw_url``) is used as
    the URL. Shared by issue_edit/close/reopen, whose repo-resolution +
    URL-building tail was copy-pasted 3× (GH-838). ``state`` is omitted
    from the payload when ``None`` so ``issue_edit`` keeps its
    stateless ``{number, url}`` shape.
    """
    payload: dict[str, Any] = {"number": number}
    if state is not None:
        payload["state"] = state
    repo_result = await _gateway._resolve_repo(repo)
    if isinstance(repo_result, ErrorResult):
        payload["url"] = raw_url
    else:
        payload["url"] = f"https://github.com/{repo_result.value}/issues/{number}"
    return payload


async def issue_edit(
    *,
    number: int,
    title: str | None = None,
    body: str | None = None,
    milestone: str | None = None,
    labels: list[str] | None = None,
    repo: str | None = None,
) -> Result[dict[str, Any]]:
    """Edit a GitHub issue's metadata (GH-220).

    Wraps ``gh issue edit``. Accepts partial updates (any subset of
    title, body, milestone, labels).

    Args:
        number: Issue number to edit.
        title: New title (optional).
        body: New body text (optional). Written to a temp file to avoid
            heredoc/quoting issues at the subprocess boundary.
        milestone: Milestone title to assign (optional). Pass empty
            string to clear.
        labels: Labels to ADD (optional). Each entry is passed via
            ``--add-label``, which only ever adds — it never removes
            or replaces the issue's existing labels (GH-1322). Use
            ``issue_labels(action="remove", ...)`` to remove a label,
            or ``issue_labels(action="list", ...)`` to read the
            current set.
        repo: Repository (owner/repo). Auto-detected if omitted.

    Returns:
        On success: ``{"number": int, "url": str}``.
    """
    if title is None and body is None and milestone is None and not labels:
        return err("issue_edit requires at least one of: title, body, milestone, labels")

    args = ["gh", "issue", "edit", str(number)]
    if title is not None:
        args.extend(["--title", title])
    body_path: Path | None = None
    if body is not None:
        fd_path = tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        )
        fd_path.write(body)
        fd_path.close()
        body_path = Path(fd_path.name)
        args.extend(["--body-file", str(body_path)])
    if milestone is not None:
        args.extend(["--milestone", milestone])
    if labels:
        for label in labels:
            args.extend(["--add-label", label])
    if repo:
        args.extend(["--repo", repo])

    try:
        result = await _gateway.async_run(args=args, timeout=30)
    finally:
        if body_path is not None:
            body_path.unlink(missing_ok=True)

    if result.returncode != 0:
        return err(result.stderr.strip())

    return ok(await _issue_result(number=number, raw_url=result.stdout.strip(), repo=repo))


# gh's --reason wants the space spelling "not planned"; the wrapper takes the
# underscore spelling and translates at the gh boundary (GH-674).
_CLOSE_REASON_GH_VALUE: dict[str, str] = {
    "completed": "completed",
    "not_planned": "not planned",
}


async def issue_close(
    *,
    number: int,
    reason: str = "completed",
    comment: str | None = None,
    repo: str | None = None,
) -> Result[dict[str, Any]]:
    """Close a GitHub issue (GH-268, GH-674).

    Wraps ``gh issue close N --reason <reason> [--comment <body>]``.

    Args:
        number: Issue number to close.
        reason: ``"completed"`` (default) or ``"not_planned"``.
        comment: Optional final closing comment (Markdown supported).
        repo: Repository (owner/repo). Auto-detected if omitted.

    Returns:
        On success: ``{"number": int, "state": "closed", "url": str}``.
    """
    if reason not in _CLOSE_REASON_GH_VALUE:
        valid = ", ".join(repr(key) for key in _CLOSE_REASON_GH_VALUE)
        return err(f"reason must be one of {valid}, got: {reason!r}")

    repo_result = await _gateway._resolve_repo(repo)
    if isinstance(repo_result, SuccessResult):
        pr_probe = await _gateway._gh_api(f"repos/{repo_result.value}/issues/{number}")
        if isinstance(pr_probe, SuccessResult) and pr_probe.value.get("pull_request") is not None:
            return err(f"{number} is a pull request; use pr_close")

    args = ["gh", "issue", "close", str(number), "--reason", _CLOSE_REASON_GH_VALUE[reason]]
    if repo:
        args.extend(["--repo", repo])
    if comment is not None:
        args.extend(["--comment", comment])

    result = await _gateway.async_run(args=args, timeout=30)
    if result.returncode != 0:
        return err(result.stderr.strip())

    return ok(
        await _issue_result(
            number=number, raw_url=result.stdout.strip(), repo=repo, state="closed"
        )
    )


async def issue_reopen(
    *,
    number: int,
    repo: str | None = None,
) -> Result[dict[str, Any]]:
    """Reopen a closed GitHub issue (GH-268).

    Wraps ``gh issue reopen N``.

    Args:
        number: Issue number to reopen.
        repo: Repository (owner/repo). Auto-detected if omitted.

    Returns:
        On success: ``{"number": int, "state": "open", "url": str}``.
    """
    args = ["gh", "issue", "reopen", str(number)]
    if repo:
        args.extend(["--repo", repo])

    result = await _gateway.async_run(args=args, timeout=30)
    if result.returncode != 0:
        return err(result.stderr.strip())

    return ok(
        await _issue_result(number=number, raw_url=result.stdout.strip(), repo=repo, state="open")
    )


def _resolve_comment_body(*, body: str | None, body_file: str | None) -> Result[str]:
    """Resolve a comment body from inline text or a file path (GH-484).

    ``body`` is literal text — there is no ``@file`` / ``--body-file``
    expansion at this boundary, so passing ``body="@/path.md"`` posts the
    literal path string. To post the *contents* of a file, pass
    ``body_file`` instead.

    Args:
        body: Inline literal comment text, or ``None``.
        body_file: Path to a file whose contents become the body, or
            ``None``. Mutually exclusive with ``body``.

    Returns:
        ``ok(text)`` with the resolved body, or ``err(...)`` when both or
        neither source is supplied, or the file does not exist.
    """
    if body_file is not None:
        if body is not None:
            return err("Pass either 'body' or 'body_file', not both.")
        path = Path(body_file).expanduser()
        if not path.is_file():
            return err(f"body_file not found: {body_file}")
        return ok(path.read_text(encoding="utf-8"))
    if body is None:
        return err("Provide either 'body' (inline text) or 'body_file' (path).")
    return ok(body)


async def issue_comment(
    *,
    number: int,
    body: str | None = None,
    repo: str | None = None,
    body_file: str | None = None,
) -> Result[dict[str, Any]]:
    """Post a comment on a GitHub issue (GH-220).

    Wraps ``gh issue comment N --body-file <tmp>``. Body is written
    to a temp file to avoid heredoc/quoting issues.

    ``body`` is literal text — there is no ``@file`` expansion. To post
    the contents of a file, pass ``body_file`` instead (GH-484).

    Args:
        number: Issue number to comment on.
        body: Comment body (Markdown supported). Literal text.
        repo: Repository (owner/repo). Auto-detected if omitted.
        body_file: Path to a file whose contents become the body.
            Mutually exclusive with ``body``.

    Returns:
        On success: ``{"url": str}`` — the comment permalink.
    """
    body_result = _resolve_comment_body(body=body, body_file=body_file)
    if isinstance(body_result, ErrorResult):
        return body_result
    resolved_body = body_result.value

    fd = tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8")
    fd.write(resolved_body)
    fd.close()
    body_path = Path(fd.name)

    args = ["gh", "issue", "comment", str(number), "--body-file", str(body_path)]
    if repo:
        args.extend(["--repo", repo])

    try:
        result = await _gateway.async_run(args=args, timeout=30)
    finally:
        body_path.unlink(missing_ok=True)

    if result.returncode != 0:
        return err(result.stderr.strip())

    return ok({"url": result.stdout.strip()})


async def issue_comment_edit(
    *,
    comment_id: int,
    body: str | None = None,
    repo: str | None = None,
    body_file: str | None = None,
) -> Result[dict[str, Any]]:
    """Edit an existing GitHub issue or PR comment body (GH-283).

    Symmetric to ``issue_comment`` (POST) but uses PATCH against
    ``/repos/{owner}/{repo}/issues/comments/{id}``. Works on issue
    comments *and* PR issue-level comments (same endpoint).

    Body is written to a temp file to avoid heredoc/quoting issues at
    the gh CLI boundary, matching the ``issue_comment`` pattern.

    ``body`` is literal text — there is no ``@file`` expansion. To
    replace with the contents of a file, pass ``body_file`` (GH-484).

    Args:
        comment_id: Numeric ID of the comment to edit (from the
            ``/comments/<id>`` URL fragment).
        body: New body text (full replacement, not a delta). Literal text.
        repo: Repository (owner/repo). Auto-detected if omitted.
        body_file: Path to a file whose contents become the new body.
            Mutually exclusive with ``body``.

    Returns:
        On success: ``{"id": int, "body": str, "html_url": str}``.
    """
    body_result = _resolve_comment_body(body=body, body_file=body_file)
    if isinstance(body_result, ErrorResult):
        return body_result
    resolved_body = body_result.value

    repo_result = await _gateway._resolve_repo(repo)
    if isinstance(repo_result, ErrorResult):
        return repo_result
    canonical_repo = str(repo_result.value)

    fd = tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8")
    fd.write(resolved_body)
    fd.close()
    body_path = Path(fd.name)

    endpoint = f"/repos/{canonical_repo}/issues/comments/{comment_id}"
    args = [
        "gh",
        "api",
        "-X",
        "PATCH",
        "-F",
        f"body=@{body_path}",
        endpoint,
    ]

    try:
        result = await _gateway.async_run(args=args, timeout=30)
    finally:
        body_path.unlink(missing_ok=True)

    if result.returncode != 0:
        return err(result.stderr.strip())

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return err(f"Invalid JSON from GitHub API: {result.stdout[:200]}")

    return ok(
        {
            "id": payload.get("id", comment_id),
            "body": payload.get("body", ""),
            "html_url": payload.get("html_url", ""),
        }
    )


async def issue_comment_delete(
    *,
    comment_id: int,
    repo: str | None = None,
) -> Result[dict[str, Any]]:
    """Delete a GitHub issue or PR comment (GH-283).

    Uses DELETE against ``/repos/{owner}/{repo}/issues/comments/{id}``.
    Works on issue comments *and* PR issue-level comments.

    Args:
        comment_id: Numeric ID of the comment to delete.
        repo: Repository (owner/repo). Auto-detected if omitted.

    Returns:
        On success: ``{"deleted": True, "comment_id": int}``.
    """
    repo_result = await _gateway._resolve_repo(repo)
    if isinstance(repo_result, ErrorResult):
        return repo_result
    canonical_repo = str(repo_result.value)

    endpoint = f"/repos/{canonical_repo}/issues/comments/{comment_id}"
    result = await _gateway.async_run(
        args=["gh", "api", "-X", "DELETE", endpoint],
        timeout=30,
    )

    if result.returncode != 0:
        return err(result.stderr.strip())

    return ok({"deleted": True, "comment_id": comment_id})


async def issue_list(
    *,
    repo: str | None = None,
    state: str = "open",
    milestone: str | None = None,
    labels: list[str] | None = None,
    limit: int = 30,
    search: str | None = None,
) -> Result[dict[str, Any]]:
    """List GitHub issues (GH-220).

    Wraps ``gh issue list ... --json
    number,title,labels,milestone,state,url``.

    Args:
        repo: Repository (owner/repo). Auto-detected if omitted.
        state: Filter by state: ``open`` (default), ``closed``, ``all``.
        milestone: Filter by milestone title or number.
        labels: Filter by labels (issues matching ALL labels).
        limit: Max results to return (default 30).
        search: Free-text search filter passed via ``--search``.

    Returns:
        ``{"issues": [{number, title, labels, milestone, state, url}, ...]}``.
    """
    args = [
        "gh",
        "issue",
        "list",
        "--state",
        state,
        "--limit",
        str(limit),
        "--json",
        "number,title,labels,milestone,state,url",
    ]
    if repo:
        args.extend(["--repo", repo])
    if milestone:
        args.extend(["--milestone", milestone])
    if labels:
        for label in labels:
            args.extend(["--label", label])
    if search:
        args.extend(["--search", search])

    result = await _gateway.async_run(args=args, timeout=30)
    if result.returncode != 0:
        return err(result.stderr.strip())
    try:
        issues = json.loads(result.stdout) if result.stdout.strip() else []
    except json.JSONDecodeError:
        return err(f"Invalid JSON output: {result.stdout[:200]}")
    return ok({"issues": issues})


async def triage_roster(*, repo: str | None = None) -> Result[dict[str, Any]]:
    """Return the open milestones and label roster for filing triage (GH-1102).

    The filing tools already accept ``milestone`` and ``labels``, but no
    filing flow ever populated them: a 2026-08-30 sweep found 11 of 16 open
    issues unmilestoned and 10 of 13 unlabeled, all filed through those
    wrappers. A flow cannot choose from a taxonomy it cannot see, so this
    is the read that makes ``Dev10x:ticket-create``'s triage step possible.

    One composite call rather than separate milestone/label tools — a
    caller triaging a new ticket always wants both, and ADR-0006 shapes
    this server's surface to Dev10x workflows rather than to REST
    endpoints.

    Args:
        repo: Repository (owner/repo). Auto-detected if omitted.

    Returns:
        ``{"milestones": [{number, title, description}, ...],
           "labels": [{name, description}, ...]}``.
    """
    milestone_args = ["gh", "api", "--paginate"]
    label_args = ["gh", "label", "list", "--limit", "100", "--json", "name,description"]
    if repo:
        milestone_path = f"repos/{repo}/milestones?state=open&per_page=100"
        label_args.extend(["--repo", repo])
    else:
        # gh expands the {owner}/{repo} placeholders from the CWD's remote.
        milestone_path = "repos/{owner}/{repo}/milestones?state=open&per_page=100"
    milestone_args.append(milestone_path)

    milestone_result = await _gateway.async_run(args=milestone_args, timeout=30)
    if milestone_result.returncode != 0:
        return err(milestone_result.stderr.strip())

    label_result = await _gateway.async_run(args=label_args, timeout=30)
    if label_result.returncode != 0:
        return err(label_result.stderr.strip())

    try:
        raw_milestones = (
            json.loads(milestone_result.stdout) if milestone_result.stdout.strip() else []
        )
        raw_labels = json.loads(label_result.stdout) if label_result.stdout.strip() else []
    except json.JSONDecodeError:
        return err("Invalid JSON output from milestone or label lookup")

    return ok(
        {
            "milestones": [
                {
                    "number": m.get("number"),
                    "title": m.get("title"),
                    "description": m.get("description") or "",
                }
                for m in raw_milestones
            ],
            "labels": [
                {"name": label.get("name"), "description": label.get("description") or ""}
                for label in raw_labels
            ],
        }
    )
