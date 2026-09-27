"""Pull request capability (ADR-0027).

Dependencies are reached through ``_gateway.<name>`` and sibling
capabilities through ``<module>.<name>`` (ADR-0027 D2), so a test patches
``dev10x.github._gateway.<name>`` / ``dev10x.github.pulls.pr_get`` and
intercepts every caller — including ``merge``'s read-back.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from dev10x.domain.common.result import ErrorResult, Result, err, ok
from dev10x.domain.pr_body import (
    fixes_references,
    has_fixes_trailer,
    job_story_error,
    normalize_pr_body,
)
from dev10x.github import _gateway, milestones
from dev10x.subprocess_utils import parse_key_value_output

# Branch names that are never a legitimate PR head — HEAD on one of these
# when opening a PR signals a wrong/unbound working directory (GH-873 F1).
_BASE_BRANCH_NAMES = frozenset({"develop", "development", "main", "master", "trunk"})


async def pr_get(
    *,
    number: int,
    repo: str | None = None,
) -> Result[dict[str, Any]]:
    """Get GitHub PR details as a structured payload (GH-267).

    Wraps ``gh pr view --json …`` so agents have a routed alternative
    to the hook-blocked ``gh pr view`` invocation. The payload includes
    ``reviews`` and ``headRefOid`` (GH-917) so approval-state prechecks
    resolve human-vs-bot and current-vs-stale approvals through this tool.
    """
    args = [str(number)]
    if repo:
        args.append(repo)
    return await _gateway._run_and_parse(
        "skills/gh-context/scripts/gh-pr-get.sh",
        *args,
        fallback=parse_key_value_output,
    )


async def _set_pr_milestone(
    *,
    pr_number: int,
    milestone: str,
    repo_ref: str,
) -> Result[int]:
    """Assign a milestone to a PR (GH-1098).

    A PR is an issue as far as milestones are concerned: the
    ``pulls/{n}`` endpoint has no ``milestone`` field, so the write
    goes through ``issues/{n}``. ``gh pr edit --milestone`` is avoided
    for the same reason ``create_pr``'s second pass avoids it — the
    GraphQL Projects-classic deprecation warning exits non-zero even
    on success (GH-41).
    """
    number_result = await milestones._resolve_milestone_number(
        milestone=milestone, repo_ref=repo_ref
    )
    if isinstance(number_result, ErrorResult):
        return err(number_result.error)
    number = number_result.value

    result = await _gateway._gh_api_raw(
        f"repos/{repo_ref}/issues/{pr_number}",
        method="PATCH",
        fields={"milestone": number},
    )
    if result.returncode != 0:
        return err(result.stderr.strip())
    return ok(number)


async def create_pr(
    *,
    title: str,
    issue_id: str,
    job_story: str = "",
    body: str | None = None,
    head: str | None = None,
    milestone: str | None = None,
    fixes_url: str | None = None,
    base_branch: str | None = None,
    closes: list[int] | None = None,
    draft: bool = True,
    head_repo: str | None = None,
    repo: str | None = None,
) -> Result[dict[str, Any]]:
    # Assert-or-refuse against a wrong/unbound CWD (GH-873 F1). A
    # worktree-isolated swarm child that omits `cwd=` resolves to the
    # long-lived MCP process's own CWD (the orchestrator's), which is
    # typically the base branch — create-pr.sh would then push that base
    # branch and open a PR from it (a stray-branch failure). HEAD on a base
    # branch is never a legitimate PR source, so refuse loudly and name the
    # cause instead of silently pushing the wrong branch. GitContext resolves
    # through the effective-CWD seam, so an explicit `cwd=` (bound by the MCP
    # wrapper's use_cwd) is honoured here.
    from dev10x.domain.git_context import GitContext

    # The Job Story markers are checked on whatever text actually
    # becomes the PR body (GH-1073): with `body=` the caller supplies
    # the whole body, so validating `job_story` would police a string
    # that never reaches GitHub.
    story_error = job_story_error(job_story=body if body is not None else job_story)
    if story_error:
        return err(f"create_pr: {story_error}")

    # A body override skips the template assembly, so the arguments that
    # only feed that template would be dropped in silence — the same
    # silent-drop this parameter exists to fix. Refuse the combination.
    if body is not None:
        ignored = [name for name, value in (("fixes_url", fixes_url), ("closes", closes)) if value]
        if ignored:
            return err(
                "create_pr: body= supplies the whole PR body, so "
                f"{' and '.join(ignored)} would be dropped. Put the "
                "Fixes: / Closes: lines in body= itself, or drop body= "
                "and pass job_story= instead."
            )

    # Assert-or-refuse against a wrong/unbound CWD (GH-873 F1) — see the
    # note above. An explicit `head=` names the branch outright, so the
    # check applies to that instead of the resolved CWD (GH-1073).
    current_branch = head or await asyncio.to_thread(lambda: GitContext().branch)
    if current_branch in _BASE_BRANCH_NAMES:
        if head:
            return err(
                f"Refusing to create a PR from base branch '{current_branch}' "
                "(GH-873 F1): head= names a base branch. Pass the feature "
                "branch you want the PR opened from."
            )
        return err(
            f"Refusing to create a PR from base branch '{current_branch}' "
            "(GH-873 F1): HEAD is on a base branch, which usually means the "
            "call resolved to the wrong working directory. Pass an explicit "
            "cwd= (the worktree path) so the PR is created from your feature "
            "branch, not the base."
        )

    args = [title, job_story, issue_id]
    args.append(
        ""
        if body is not None
        else fixes_references(issue_id=issue_id, fixes_url=fixes_url, closes=closes)
    )
    args.append(base_branch or "")
    args.append(",".join(str(n) for n in closes) if closes else "")
    args.append("true" if draft else "false")
    args.append(head_repo or "")
    args.append(normalize_pr_body(body=body) if body is not None else "")
    args.append(head or "")
    args.append(repo or "")

    result = await _gateway.async_run_script(
        "skills/gh-pr-create/scripts/create-pr.sh",
        *args,
    )

    if result.returncode != 0:
        return err(result.stderr.strip())

    lines = result.stdout.strip().split("\n")
    pr_number = lines[-1]
    url = next((line for line in lines if line.startswith("http")), f"PR #{pr_number}")
    payload: dict[str, Any] = {"pr_number": int(pr_number), "url": url}

    # Carries the resolved repo forward to the read-back below, so the
    # two calls cannot disagree about which repository this PR is in.
    # Stays None on the no-milestone path rather than forcing an extra
    # resolution round-trip — pr_get auto-detects from the same bound
    # CWD that create-pr.sh just used.
    resolved_repo = repo

    if milestone is not None:
        repo_result = await _gateway._resolve_repo(repo)
        if isinstance(repo_result, ErrorResult):
            return err(repo_result.error)
        resolved_repo = str(repo_result.value)
        milestone_result = await _set_pr_milestone(
            pr_number=payload["pr_number"],
            milestone=milestone,
            repo_ref=resolved_repo,
        )
        if isinstance(milestone_result, ErrorResult):
            # The PR is already open at this point, so an error naming
            # only the milestone failure strands it — name the PR too so
            # the caller can retry, comment on, or close it.
            return err(
                f"PR #{payload['pr_number']} ({payload['url']}) was created, "
                f"but assigning milestone {milestone!r} failed: "
                f"{milestone_result.error}"
            )
        payload["milestone"] = milestone_result.value

    # Read the trailer back off GitHub (GH-1274). Deriving one is not
    # proof it arrived — a write is a request, not a receipt (GH-1099) —
    # so only a fresh read settles it.
    verified = await pr_get(number=payload["pr_number"], repo=resolved_repo)
    if isinstance(verified, ErrorResult):
        # The PR exists and may well be fine; an unreadable verification
        # is not evidence of a bad body, so flag it rather than fail it.
        payload["fixes_trailer_verified"] = False
        payload["warning"] = (
            f"PR #{payload['pr_number']} was created but its body could not be "
            f"read back to confirm the Fixes: trailer: {verified.error}"
        )
        return ok(payload)

    if not has_fixes_trailer(body=str(verified.value.get("body", ""))):
        # Named like the milestone failure above: the PR is already open,
        # so an error that does not identify it strands it.
        return err(
            f"PR #{payload['pr_number']} ({payload['url']}) was created, but its "
            "body carries no Fixes: trailer — the hygiene bot will reject it and "
            "no linked issue will close on merge. Add the trailer with update_pr."
        )

    payload["fixes_trailer_verified"] = True
    return ok(payload)


async def update_pr(
    *,
    pr_number: int,
    body: str | None = None,
    title: str | None = None,
    base_branch: str | None = None,
    milestone: str | None = None,
    repo: str | None = None,
) -> Result[dict[str, Any]]:
    if body is None and title is None and base_branch is None and milestone is None:
        return err("update_pr requires at least one of: body, title, base_branch, milestone")

    repo_result = await _gateway._resolve_repo(repo)
    if isinstance(repo_result, ErrorResult):
        return err(repo_result.error)
    repo_ref = repo_result.value

    fields: dict[str, str | int | list[str]] = {}
    if body is not None:
        fields["body"] = normalize_pr_body(body=body)
    if title is not None:
        fields["title"] = title
    if base_branch is not None:
        fields["base"] = base_branch

    if fields:
        result = await _gateway._gh_api_raw(
            f"repos/{repo_ref}/pulls/{pr_number}",
            method="PATCH",
            fields=fields,
        )

        if result.returncode != 0:
            return err(result.stderr.strip())

    url = f"https://github.com/{repo_ref}/pull/{pr_number}"
    payload: dict[str, Any] = {"pr_number": pr_number, "url": url}

    if milestone is not None:
        milestone_result = await _set_pr_milestone(
            pr_number=pr_number,
            milestone=milestone,
            repo_ref=str(repo_ref),
        )
        if isinstance(milestone_result, ErrorResult):
            return err(milestone_result.error)
        payload["milestone"] = milestone_result.value

    if not fields:
        return ok(payload)

    # GH-1424: the payload used to be built entirely from the arguments,
    # so a PATCH the transport dropped read back as a completed write
    # (GH-1099). `.claude/rules/mcp-tools.md` names `update_pr` as needing
    # this; only `create_pr` actually did it.
    verified = await pr_get(number=pr_number, repo=str(repo_ref))
    if isinstance(verified, ErrorResult):
        payload["write_verified"] = False
        payload["warning"] = (
            f"PR #{pr_number} was updated but could not be read back to "
            f"confirm the change: {verified.error}"
        )
        return ok(payload)

    unapplied = _unapplied_pr_fields(sent=fields, observed=verified.value)
    if unapplied:
        return err(
            f"PR #{pr_number} ({url}) reports {', '.join(sorted(unapplied))} "
            f"unchanged after the update — the write did not land. Retry "
            f"update_pr rather than assuming the PR carries the new content."
        )

    payload["write_verified"] = True
    return ok(payload)


def _normalized_for_comparison(text: str) -> str:
    """Compare PR text ignoring differences GitHub introduces itself.

    GitHub stores bodies with CRLF line endings and may drop trailing
    whitespace, so a byte-exact comparison against what was sent reports
    a dropped write on every successful call.
    """
    return text.replace("\r\n", "\n").strip()


def _unapplied_pr_fields(
    *,
    sent: dict[str, str | int | list[str]],
    observed: dict[str, Any],
) -> set[str]:
    """Which of the PATCHed fields the PR does not actually carry.

    ``base`` is deliberately not checked: it is reported as
    ``baseRefName`` and a retarget can be refused server-side for
    reasons a caller cannot act on by retrying.
    """
    checked = {"body": "body", "title": "title"}
    return {
        field
        for field, observed_key in checked.items()
        if field in sent
        and _normalized_for_comparison(str(sent[field]))
        != _normalized_for_comparison(str(observed.get(observed_key, "")))
    }


async def pr_ready(
    *,
    pr_number: int,
    repo: str | None = None,
    undo: bool = False,
) -> Result[dict[str, Any]]:
    """Flip a PR between draft and ready-for-review via ``gh pr ready`` (GH-779).

    The ``draft`` flag is not PATCHable through the pulls endpoint, so
    :func:`update_pr` cannot un-draft a PR — un-drafting needs the
    dedicated GraphQL mutation that ``gh pr ready`` wraps. Symmetric to
    :func:`merge_pr`: the subprocess launches from the MCP server, so
    the PreToolUse hook that blocks raw ``gh pr ready`` Bash calls does
    not apply. Repos whose CI skips draft PRs must mark ready BEFORE
    monitoring CI, or the monitor polls a PR that never registers checks.

    ``undo=True`` converts a published PR back to draft (GH-931 finding 2).
    Raw ``gh pr ready --undo`` is hook-blocked like every other form, so
    without this parameter the un-publish direction had no available path
    at all — and un-publishing is the *safe* direction, the correct
    response to spotting a problem after marking ready.

    Args:
        pr_number: PR number to flip.
        repo: Repository (owner/repo). Auto-detected if omitted.
        undo: Convert back to draft instead of marking ready.

    Returns:
        ok({"pr_number", "url", "repo", "draft"}) on success, err(...) otherwise.
    """
    repo_result = await _gateway._resolve_repo(repo)
    if isinstance(repo_result, ErrorResult):
        return err(repo_result.error)
    repo_ref = repo_result.value

    args = ["gh", "pr", "ready", str(pr_number), "--repo", str(repo_ref)]
    if undo:
        args.append("--undo")

    result = await _gateway.async_run(args=args, timeout=30)

    if result.returncode != 0:
        return err(result.stderr.strip() or result.stdout.strip())

    url = f"https://github.com/{repo_ref}/pull/{pr_number}"
    payload: dict[str, Any] = {"pr_number": pr_number, "url": url, "repo": str(repo_ref)}

    # GH-1424: `draft` used to be the `undo` argument echoed back, so it
    # could never disagree with the request and carried no information
    # about what GitHub did — while looking exactly like confirmation.
    # A write is a request, not a receipt (GH-1099): only a fresh read
    # settles it. GH-958 makes this load-bearing, since a force-push
    # silently returns a published PR to draft.
    verified = await pr_get(number=pr_number, repo=str(repo_ref))
    if isinstance(verified, ErrorResult):
        # The flip may well have landed; an unreadable verification is not
        # evidence that it did not. Report the request, flagged as unread.
        payload["draft"] = undo
        payload["draft_verified"] = False
        payload["warning"] = (
            f"PR #{pr_number} draft state could not be read back to confirm "
            f"the flip: {verified.error}"
        )
        return ok(payload)

    observed = bool(verified.value.get("isDraft"))
    if observed != undo:
        wanted = "draft" if undo else "ready for review"
        return err(
            f"PR #{pr_number} ({url}) is still "
            f"{'a draft' if observed else 'published'} after asking to make it "
            f"{wanted} — the write did not land. Retry pr_ready; a merge "
            f"attempted now fails with 'Pull Request is still a draft'."
        )

    payload["draft"] = observed
    payload["draft_verified"] = True
    return ok(payload)


async def pr_close(
    *,
    pr_number: int,
    comment: str | None = None,
    repo: str | None = None,
) -> Result[dict[str, Any]]:
    """Close a pull request via ``gh pr close`` (GH-924).

    Mirrors :func:`issue_close`'s shape — including the optional
    closing ``comment`` — so retiring a stale/superseded PR is one
    routed MCP call instead of the two-step "comment, then raw
    ``gh pr close``" workaround this issue was filed to eliminate.
    ``issue_close`` cannot be reused for this: `gh issue close`
    rejects a pull-request number outright.

    Args:
        pr_number: PR number to close.
        comment: Optional closing comment (Markdown supported),
            posted before the close so the rationale survives even
            if the close itself fails.
        repo: Repository (owner/repo). Auto-detected if omitted.

    Returns:
        On success: ``{"pr_number": int, "state": "closed", "url": str}``.
    """
    repo_result = await _gateway._resolve_repo(repo)
    if isinstance(repo_result, ErrorResult):
        return err(repo_result.error)
    repo_ref = repo_result.value

    if comment is not None:
        comment_result = await _gateway._gh_api_raw(
            f"repos/{repo_ref}/issues/{pr_number}/comments",
            method="POST",
            fields={"body": comment},
            repo=str(repo_ref),
            as_bot=True,
        )
        if comment_result.returncode != 0:
            return err(comment_result.stderr.strip() or comment_result.stdout.strip())

    result = await _gateway.async_run(
        args=["gh", "pr", "close", str(pr_number), "--repo", str(repo_ref)],
        timeout=30,
    )
    if result.returncode != 0:
        return err(result.stderr.strip() or result.stdout.strip())

    url = f"https://github.com/{repo_ref}/pull/{pr_number}"
    return ok({"pr_number": pr_number, "state": "closed", "url": url})


async def pr_list(
    *,
    repo: str | None = None,
    state: str = "open",
    limit: int = 30,
    search: str | None = None,
) -> Result[dict[str, Any]]:
    """List GitHub pull requests (GH-1359).

    Wraps ``gh pr list ... --json
    number,title,state,headRefName,isDraft,mergedAt,url``, mirroring
    :func:`issue_list`'s shape. `dev10x:diag-friction` filed this after
    finding no ``pr_list`` MCP tool and no ``gh pr list`` rule in
    ``command-skill-map.yaml`` — listing PRs had nowhere to go but raw
    ``gh pr list``, uncatalogued and prompting on every call.

    Args:
        repo: Repository (owner/repo). Auto-detected if omitted.
        state: Filter by state: ``open`` (default), ``closed``, ``merged``,
            ``all``.
        limit: Max results to return (default 30).
        search: Free-text search filter passed via ``--search``.

    Returns:
        ``{"prs": [{number, title, state, headRefName, isDraft,
        mergedAt, url}, ...]}``.
    """
    if state not in ("open", "closed", "merged", "all"):
        return err(f"Invalid PR state {state!r}: must be 'open', 'closed', 'merged', or 'all'.")

    args = [
        "gh",
        "pr",
        "list",
        "--state",
        state,
        "--limit",
        str(limit),
        "--json",
        "number,title,state,headRefName,isDraft,mergedAt,url",
    ]
    if repo:
        args.extend(["--repo", repo])
    if search:
        args.extend(["--search", search])

    result = await _gateway.async_run(args=args, timeout=30)
    if result.returncode != 0:
        return err(result.stderr.strip())
    try:
        prs = json.loads(result.stdout) if result.stdout.strip() else []
    except json.JSONDecodeError:
        return err(f"Invalid JSON output: {result.stdout[:200]}")
    return ok({"prs": prs})
