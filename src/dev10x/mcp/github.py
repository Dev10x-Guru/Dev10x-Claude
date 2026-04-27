"""GitHub MCP tool implementations.

Extracted from cli_server.py — cohesive GitHub API and CLI operations.
Each function takes explicit parameters and returns Result types.
All public functions are async to avoid blocking the MCP event loop.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from dev10x.domain.repository_ref import RepositoryRef
from dev10x.domain.result import ErrorResult, Result, err, ok
from dev10x.mcp.subprocess_utils import (
    async_run,
    async_run_script,
    parse_key_value_output,
)


async def _detect_repo() -> str | None:
    result = await async_run(
        args=["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
        timeout=10,
    )
    if result.returncode == 0:
        return result.stdout.strip()
    return None


async def _gh_api(
    endpoint: str,
    *,
    method: str = "GET",
    fields: dict[str, str | int | list[str]] | None = None,
    jq: str | None = None,
) -> subprocess.CompletedProcess[str]:
    args = ["gh", "api"]
    if method != "GET":
        args.extend(["-X", method])
    if jq:
        args.extend(["--jq", jq])
    if fields:
        for key, value in fields.items():
            if isinstance(value, list):
                for item in value:
                    args.extend(["-f", f"{key}[]={item}"])
            elif isinstance(value, int):
                args.extend(["-F", f"{key}={value}"])
            else:
                args.extend(["-f", f"{key}={value}"])
    args.append(endpoint)

    return await async_run(args=args, timeout=30)


async def _resolve_repo(
    repo: str | None,
) -> Result[RepositoryRef]:
    resolved = repo or await _detect_repo()
    if not resolved:
        return err("Could not detect repository. Provide repo parameter.")
    try:
        return ok(RepositoryRef.parse(resolved))
    except ValueError as exc:
        return err(str(exc))


def _parse_gh_api_result(
    result: subprocess.CompletedProcess[str],
) -> Result[dict[str, Any]]:
    if result.returncode != 0:
        return err(result.stderr.strip())
    try:
        return ok(json.loads(result.stdout))
    except json.JSONDecodeError:
        return ok({"raw_output": result.stdout})


async def detect_tracker(*, ticket_id: str) -> Result[dict[str, Any]]:
    result = await async_run_script(
        "skills/gh-context/scripts/detect-tracker.sh",
        ticket_id,
    )
    if result.returncode != 0:
        return err(result.stderr.strip())
    return ok(parse_key_value_output(result.stdout))


async def pr_detect(*, arg: str) -> Result[dict[str, Any]]:
    result = await async_run_script(
        "skills/gh-context/scripts/gh-pr-detect.sh",
        arg,
    )
    if result.returncode != 0:
        return err(result.stderr.strip())
    return ok(parse_key_value_output(result.stdout))


async def issue_get(
    *,
    number: int,
    repo: str | None = None,
) -> Result[dict[str, Any]]:
    args = [str(number)]
    if repo:
        args.append(repo)
    result = await async_run_script(
        "skills/gh-context/scripts/gh-issue-get.sh",
        *args,
    )
    if result.returncode != 0:
        return err(result.stderr.strip())
    try:
        return ok(json.loads(result.stdout))
    except json.JSONDecodeError:
        return ok(parse_key_value_output(result.stdout))


async def issue_comments(
    *,
    number: int,
    repo: str | None = None,
) -> Result[dict[str, Any]]:
    args = [str(number)]
    if repo:
        args.append(repo)
    result = await async_run_script(
        "skills/gh-context/scripts/gh-issue-comments.sh",
        *args,
    )
    if result.returncode != 0:
        return err(result.stderr.strip())
    try:
        return ok(json.loads(result.stdout))
    except json.JSONDecodeError:
        return ok({"raw_output": result.stdout})


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
    result = await async_run_script(
        "skills/gh-context/scripts/gh-issue-create.sh",
        *args,
    )
    if result.returncode != 0:
        return err(result.stderr.strip())
    try:
        return ok(json.loads(result.stdout))
    except json.JSONDecodeError:
        return ok(parse_key_value_output(result.stdout))


async def _pr_comment_get(
    *,
    resolved_repo: str,
    comment_id: int | str | None = None,
    **_: Any,
) -> Result[dict[str, Any]]:
    if comment_id is None:
        return err("comment_id required for 'get' action")
    result = await _gh_api(f"repos/{resolved_repo}/pulls/comments/{comment_id}")
    return _parse_gh_api_result(result)


async def _pr_comment_list(
    *,
    resolved_repo: str,
    pr_number: int | None = None,
    review_id: int | None = None,
    unresolved_only: bool = False,
    **_: Any,
) -> Result[dict[str, Any]]:
    if pr_number is None:
        return err("pr_number required for 'list' action")
    if unresolved_only:
        return await _list_unresolved_threads(
            resolved_repo=resolved_repo,
            pr_number=pr_number,
        )
    result = await _gh_api(
        f"repos/{resolved_repo}/pulls/{pr_number}/comments?per_page=100",
    )
    parsed = _parse_gh_api_result(result)
    if isinstance(parsed, ErrorResult) or review_id is None:
        return parsed
    if isinstance(parsed.value, list):
        filtered = [c for c in parsed.value if c.get("pull_request_review_id") == review_id]
        return ok(filtered)
    return parsed


async def _list_unresolved_threads(
    *,
    resolved_repo: str,
    pr_number: int,
) -> Result[dict[str, Any]]:
    repo_ref = (
        resolved_repo
        if isinstance(resolved_repo, RepositoryRef)
        else RepositoryRef.parse(str(resolved_repo))
    )
    query = (
        "query { "
        f"repository(owner: {json.dumps(repo_ref.owner)}, "
        f"name: {json.dumps(repo_ref.name)}) "
        f"{{ pullRequest(number: {pr_number}) "
        "{ reviewThreads(first: 100) { nodes { "
        "id isResolved isOutdated "
        "comments(first: 1) { nodes { "
        "databaseId body path line "
        "author { login } "
        "pullRequestReview { databaseId } "
        "} } "
        "} } } } }"
    )
    result = await _gh_api("graphql", fields={"query": query})
    if result.returncode != 0:
        return err(result.stderr.strip())
    data = json.loads(result.stdout)
    threads = (
        data.get("data", {})
        .get("repository", {})
        .get("pullRequest", {})
        .get("reviewThreads", {})
        .get("nodes", [])
    )
    unresolved: list[dict[str, Any]] = []
    for thread in threads:
        if thread.get("isResolved"):
            continue
        comments = thread.get("comments", {}).get("nodes", [])
        first = comments[0] if comments else {}
        unresolved.append(
            {
                "thread_id": thread.get("id"),
                "is_outdated": thread.get("isOutdated"),
                **first,
            }
        )
    return ok({"unresolved_threads": unresolved, "count": len(unresolved)})


async def _pr_comment_reply(
    *,
    resolved_repo: str,
    pr_number: int | None = None,
    comment_id: int | str | None = None,
    body: str | None = None,
    **_: Any,
) -> Result[dict[str, Any]]:
    if pr_number is None or comment_id is None or body is None:
        return err("pr_number, comment_id, and body required for 'reply'")
    try:
        comment_id_int = int(comment_id)
    except (TypeError, ValueError):
        return err(
            f"comment_id must be an integer for 'reply' "
            f"(GitHub rejects strings as in_reply_to). Got: {comment_id!r}"
        )
    result = await _gh_api(
        f"repos/{resolved_repo}/pulls/{pr_number}/comments",
        method="POST",
        fields={"body": body, "in_reply_to": comment_id_int},
    )
    return _parse_gh_api_result(result)


async def _pr_comment_resolve(
    *,
    resolved_repo: str,
    comment_id: int | str | None = None,
    comment_ids: list[str] | None = None,
    **_: Any,
) -> Result[dict[str, Any]]:
    ids_to_resolve: list[str] = []
    if comment_ids:
        ids_to_resolve = comment_ids
    elif comment_id is not None:
        ids_to_resolve = [str(comment_id)]
    else:
        return err("comment_id or comment_ids required for 'resolve' action")

    node_fragments = " ".join(
        f"n{i}: node(id: {json.dumps(cid)}) "
        f"{{ ... on PullRequestReviewComment "
        f"{{ pullRequestReviewThread {{ id }} }} }}"
        for i, cid in enumerate(ids_to_resolve)
    )
    query_result = await _gh_api(
        "graphql",
        fields={"query": f"{{ {node_fragments} }}"},
    )
    if query_result.returncode != 0:
        return err(query_result.stderr.strip())

    query_data = json.loads(query_result.stdout)
    thread_ids: list[str] = []
    errors: list[str] = []
    for i, cid in enumerate(ids_to_resolve):
        node = query_data.get("data", {}).get(f"n{i}")
        thread = node.get("pullRequestReviewThread") if node else None
        if thread and thread["id"].startswith("PRRT_"):
            thread_ids.append(thread["id"])
        else:
            errors.append(
                f"Could not find thread for comment {cid}. "
                "The resolve action requires a GraphQL node_id, not a REST "
                "integer ID. Use the node_id field from a comment response."
            )

    if not thread_ids:
        return err("; ".join(errors))

    resolve_fragments = " ".join(
        f"r{i}: resolveReviewThread(input: {{threadId: {json.dumps(tid)}}}) "
        f"{{ thread {{ id isResolved }} }}"
        for i, tid in enumerate(thread_ids)
    )
    result = await _gh_api(
        "graphql",
        fields={"query": f"mutation {{ {resolve_fragments} }}"},
    )

    if result.returncode != 0:
        return err(result.stderr.strip())

    response: dict[str, Any] = json.loads(result.stdout)
    if errors:
        response["warnings"] = errors
    return ok(response)


_PR_COMMENT_ACTIONS: dict[str, Any] = {
    "get": _pr_comment_get,
    "list": _pr_comment_list,
    "reply": _pr_comment_reply,
    "resolve": _pr_comment_resolve,
}


_MINIMIZE_CLASSIFIERS = frozenset(
    {"ABUSE", "DUPLICATE", "OFF_TOPIC", "OUTDATED", "RESOLVED", "SPAM"}
)


async def minimize_comments(
    *,
    node_ids: list[str],
    classifier: str = "OUTDATED",
    repo: str | None = None,
) -> Result[dict[str, Any]]:
    if not node_ids:
        return err("node_ids required (non-empty list of GraphQL node IDs)")
    if classifier not in _MINIMIZE_CLASSIFIERS:
        valid = ", ".join(sorted(_MINIMIZE_CLASSIFIERS))
        return err(f"Invalid classifier: {classifier!r}. Must be one of: {valid}")
    repo_result = await _resolve_repo(repo)
    if isinstance(repo_result, ErrorResult):
        return repo_result

    fragments = " ".join(
        f"m{i}: minimizeComment(input: "
        f"{{subjectId: {json.dumps(nid)}, classifier: {classifier}}}) "
        f"{{ minimizedComment {{ isMinimized minimizedReason }} }}"
        for i, nid in enumerate(node_ids)
    )
    result = await _gh_api(
        "graphql",
        fields={"query": f"mutation {{ {fragments} }}"},
    )
    if result.returncode != 0:
        return err(result.stderr.strip())
    return ok(json.loads(result.stdout))


async def resolve_review_thread(
    *,
    thread_ids: list[str] | None = None,
    comment_ids: list[str] | None = None,
    repo: str | None = None,
) -> Result[dict[str, Any]]:
    if thread_ids:
        invalid = [tid for tid in thread_ids if not tid.startswith("PRRT_")]
        if invalid:
            return err(
                f"Invalid thread IDs (must start with PRRT_): {invalid}. "
                "Use comment_ids for GraphQL node IDs that need thread lookup."
            )
        resolve_fragments = " ".join(
            f"r{i}: resolveReviewThread(input: {{threadId: {json.dumps(tid)}}}) "
            f"{{ thread {{ id isResolved }} }}"
            for i, tid in enumerate(thread_ids)
        )
        result = await _gh_api(
            "graphql",
            fields={"query": f"mutation {{ {resolve_fragments} }}"},
        )
        if result.returncode != 0:
            return err(result.stderr.strip())
        return ok(json.loads(result.stdout))

    if comment_ids:
        repo_result = await _resolve_repo(repo)
        if isinstance(repo_result, ErrorResult):
            return repo_result
        return await _pr_comment_resolve(
            resolved_repo=repo_result.value,
            comment_ids=comment_ids,
        )

    return err("Provide either thread_ids (PRRT_...) or comment_ids (GraphQL node IDs).")


async def pr_comments(
    *,
    action: str,
    pr_number: int | None = None,
    comment_id: int | str | None = None,
    comment_ids: list[str] | None = None,
    body: str | None = None,
    review_id: int | None = None,
    unresolved_only: bool = False,
    repo: str | None = None,
) -> Result[dict[str, Any]]:
    repo_result = await _resolve_repo(repo)
    if isinstance(repo_result, ErrorResult):
        return repo_result

    handler = _PR_COMMENT_ACTIONS.get(action)
    if handler is None:
        supported = ", ".join(_PR_COMMENT_ACTIONS)
        return err(f"Unknown action: {action}. Supported: {supported}")

    return await handler(
        resolved_repo=repo_result.value,
        pr_number=pr_number,
        comment_id=comment_id,
        comment_ids=comment_ids,
        body=body,
        review_id=review_id,
        unresolved_only=unresolved_only,
    )


async def pr_comment_reply(
    *,
    pr_number: int,
    comment_id: int,
    body: str,
    repo: str | None = None,
) -> Result[dict[str, Any]]:
    repo_result = await _resolve_repo(repo)
    if isinstance(repo_result, ErrorResult):
        return repo_result
    resolved_repo = repo_result.value

    try:
        comment_id_int = int(comment_id)
    except (TypeError, ValueError):
        return err(
            f"comment_id must be an integer "
            f"(GitHub rejects strings as in_reply_to). Got: {comment_id!r}"
        )

    result = await _gh_api(
        f"repos/{resolved_repo}/pulls/{pr_number}/comments",
        method="POST",
        fields={"body": body, "in_reply_to": comment_id_int},
    )

    return _parse_gh_api_result(result)


async def request_review(
    *,
    pr_number: int,
    reviewers: list[str],
    team: bool | None = None,
    repo: str | None = None,
) -> Result[dict[str, Any]]:
    repo_result = await _resolve_repo(repo)
    if isinstance(repo_result, ErrorResult):
        return repo_result
    resolved_repo = repo_result.value

    fields: dict[str, str | list[str]] = {}
    if team:
        fields["team_reviewers"] = [r.split("/")[-1] for r in reviewers]
    else:
        fields["reviewers"] = reviewers

    result = await _gh_api(
        f"repos/{resolved_repo}/pulls/{pr_number}/requested_reviewers",
        method="POST",
        fields=fields,
    )

    return _parse_gh_api_result(result)


async def detect_base_branch(
    *,
    base: str | None = None,
    force: bool = False,
) -> Result[dict[str, Any]]:
    args: list[str] = []
    if base:
        args.extend(["--base", base])
    if force:
        args.append("--force")

    result = await async_run_script(
        "skills/gh-pr-create/scripts/detect-base-branch.sh",
        *args,
    )

    if result.returncode != 0:
        return err(result.stderr.strip())

    parsed = parse_key_value_output(result.stdout)
    return ok(
        {
            "base_branch": parsed.get("BASE_BRANCH", ""),
            "has_develop": bool(parsed.get("DEV_BRANCH", "")),
        }
    )


async def verify_pr_state(*, force: bool = False) -> Result[dict[str, Any]]:
    args: list[str] = []
    if force:
        args.append("--force")

    result = await async_run_script(
        "skills/gh-pr-create/scripts/verify-state.sh",
        *args,
    )

    if result.returncode != 0:
        return err(result.stderr.strip())

    return ok(parse_key_value_output(result.stdout))


async def pre_pr_checks(*, base_branch: str | None = None) -> Result[dict[str, Any]]:
    args: list[str] = []
    if base_branch:
        args.append(base_branch)

    result = await async_run_script(
        "skills/gh-pr-create/scripts/pre-pr-checks.sh",
        *args,
    )

    if result.returncode != 0:
        return err(result.stderr.strip(), output=result.stdout.strip())

    return ok({"success": True, "output": result.stdout.strip()})


async def create_pr(
    *,
    title: str,
    job_story: str,
    issue_id: str,
    fixes_url: str | None = None,
    base_branch: str | None = None,
) -> Result[dict[str, Any]]:
    args = [title, job_story, issue_id]
    args.append(fixes_url or "")
    args.append(base_branch or "")

    result = await async_run_script(
        "skills/gh-pr-create/scripts/create-pr.sh",
        *args,
    )

    if result.returncode != 0:
        return err(result.stderr.strip())

    lines = result.stdout.strip().split("\n")
    pr_number = lines[-1]
    url = next((line for line in lines if line.startswith("http")), f"PR #{pr_number}")
    return ok({"pr_number": int(pr_number), "url": url})


async def generate_commit_list(
    *,
    pr_number: int,
    base_branch: str | None = None,
) -> Result[dict[str, Any]]:
    args = [str(pr_number)]
    if base_branch:
        args.append(base_branch)

    result = await async_run_script(
        "skills/gh-pr-create/scripts/generate-commit-list.sh",
        *args,
    )

    if result.returncode != 0:
        return err(result.stderr.strip())

    return ok({"commit_list": result.stdout.strip()})


async def post_summary_comment(
    *,
    issue_id: str,
    summary_text: str,
) -> Result[dict[str, Any]]:
    result = await async_run_script(
        "skills/gh-pr-create/scripts/post-summary-comment.sh",
        issue_id,
        summary_text,
    )

    if result.returncode != 0:
        return err(result.stderr.strip())

    return ok({"success": True, "output": result.stdout.strip()})


async def pr_notify(
    *,
    pr_number: int,
    repo: str,
    action: str = "prepare",
    channel: str | None = None,
    message: str | None = None,
    message_file: str | None = None,
    reviewer: str | None = None,
    skip_slack: bool = False,
    skip_reviewers: bool = False,
    skip_checklist: bool = False,
) -> Result[dict[str, Any]]:
    plugin_root = Path(__file__).parents[3]
    script_path = plugin_root / "skills" / "gh-pr-monitor" / "scripts" / "pr-notify.py"

    if not script_path.exists():
        return err(f"Script not found: {script_path}")

    args = [
        "uv",
        "run",
        "--script",
        str(script_path),
        action,
        "--pr",
        str(pr_number),
        "--repo",
        repo,
    ]

    if action == "send":
        if channel:
            args.extend(["--channel", channel])
        if message:
            args.extend(["--message", message])
        if message_file:
            args.extend(["--message-file", message_file])
        if reviewer:
            args.extend(["--reviewer", reviewer])
        if skip_slack:
            args.append("--skip-slack")
        if skip_reviewers:
            args.append("--skip-reviewers")
        if skip_checklist:
            args.append("--skip-checklist")

    proc = await async_run(args=args, timeout=60)

    if proc.returncode != 0:
        return err(proc.stderr.strip())

    try:
        return ok(json.loads(proc.stdout))
    except json.JSONDecodeError:
        return ok({"success": True, "output": proc.stdout.strip()})


async def check_top_level_comments(
    *,
    pr_number: int,
    repo: str,
) -> Result[dict[str, Any]]:
    result = await async_run_script(
        "skills/gh-pr-merge/scripts/check-top-level-comments.sh",
        *repo.split("/"),
        str(pr_number),
    )
    if result.returncode != 0:
        return err(result.stderr.strip())
    try:
        findings = json.loads(result.stdout)
    except json.JSONDecodeError:
        return err(f"Invalid JSON output: {result.stdout[:200]}")
    return ok({"findings": findings, "count": len(findings)})


async def unresolved_threads(
    *,
    repo: str,
    limit: int = 200,
) -> Result[dict[str, Any]]:
    result = await async_run_script(
        "skills/gh-pr-doctor/scripts/gh-unresolved-threads.py",
        "--repo",
        repo,
        "--limit",
        str(limit),
    )
    if result.returncode != 0:
        return err(result.stderr.strip())
    try:
        prs = json.loads(result.stdout)
    except json.JSONDecodeError:
        return err(f"Invalid JSON output: {result.stdout[:200]}")
    return ok({"prs": prs, "count": len(prs)})
