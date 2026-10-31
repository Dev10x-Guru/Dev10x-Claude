"""Bounded CI re-run capability (GH-1674).

Re-runs failed GitHub Actions jobs and re-requests third-party GitHub App
check suites for one PR head, so an agent never needs the raw
``gh api --method POST`` shape that sits on an ask rule.

Dependencies are reached through ``_gateway.<name>`` (ADR-0027 D2).
"""

from __future__ import annotations

import json
import re
from typing import Any

from dev10x.core.github import _gateway
from dev10x.domain.common.result import ErrorResult, Result, err, ok

#: Actions runs at or past this ``run_attempt`` are refused. The counter
#: lives on GitHub, so the cap is stateless and survives across sessions
#: and worktrees without a local store.
MAX_RUN_ATTEMPTS = 3

#: Upper bound on re-runs issued by one call, so a PR with dozens of
#: failing suites cannot fan out into a burst of POSTs.
MAX_RETRIES_PER_CALL = 10

_FAILED_CONCLUSIONS = frozenset(
    {"failure", "timed_out", "cancelled", "action_required", "startup_failure"}
)
_ACTIONS_APP_SLUG = "github-actions"
_SHA_PATTERN = re.compile(r"[0-9a-f]{7,40}", re.IGNORECASE)


def _items(*, raw: str, key: str) -> Result[list[dict[str, Any]]]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return err(f"could not parse the '{key}' listing as JSON")
    items = payload.get(key) if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return err(f"unexpected '{key}' listing shape from GitHub")
    return ok([item for item in items if isinstance(item, dict)])


async def _head_sha(*, repo: str, pr_number: int) -> Result[str]:
    result = await _gateway._gh_api_raw(
        f"repos/{repo}/pulls/{pr_number}", jq=".head.sha", repo=repo
    )
    sha = result.stdout.strip()
    if result.returncode != 0 or not sha:
        return err(result.stderr.strip() or f"could not resolve head SHA for PR {pr_number}")
    return ok(sha)


def _matches(*, wanted: list[str] | None, names: list[str]) -> bool:
    if not wanted:
        return True
    lowered = {name.lower() for name in names if name}
    return any(item.lower() in lowered for item in wanted)


async def ci_rerun(
    *,
    pr_number: int | None = None,
    head_sha: str | None = None,
    checks: list[str] | None = None,
    failed_only: bool = True,
    repo: str | None = None,
) -> Result[dict[str, Any]]:
    """Re-run CI for a PR head, bounded and reported (GH-1674).

    GitHub Actions suites go through ``actions/runs/{id}/rerun-failed-jobs``
    (or ``/rerun`` when ``failed_only`` is false); every other check suite
    is a third-party GitHub App and is re-requested through
    ``check-suites/{id}/rerequest``.

    Bounds: the repository is the caller's (never inferred from a URL),
    an Actions run whose ``run_attempt`` is already ``MAX_RUN_ATTEMPTS``
    is skipped, and one call issues at most ``MAX_RETRIES_PER_CALL``
    re-runs. A third-party suite exposes no attempt counter, so only the
    per-call bound applies to it.

    Args:
        pr_number: PR whose head SHA is targeted. Exactly one of
            ``pr_number`` / ``head_sha`` is required.
        head_sha: Commit SHA to target directly.
        checks: Case-insensitive names to restrict to; matched against
            the workflow name, the app name and the app slug.
        failed_only: Only re-run suites that failed (default). When
            false, completed Actions runs are re-run in full.
        repo: Repository (owner/repo). Auto-detected if omitted.

    Returns:
        ``{"repo", "head_sha", "failed_only", "max_attempts", "retried":
        [{"kind", "id", "name", "attempt_before", "endpoint"}],
        "skipped": [{"name", "reason"}], "failed": [{"name",
        "error"}]}``. An error is returned only when nothing was
        retried and at least one re-run was refused by GitHub.
    """
    if (pr_number is None) == (head_sha is None):
        return err("pass exactly one of 'pr_number' or 'head_sha'")
    if pr_number is not None and pr_number <= 0:
        return err(f"pr_number must be positive, got {pr_number}")
    if head_sha is not None and not head_sha.strip():
        return err("head_sha must not be empty")

    repo_result = await _gateway._resolve_repo(repo)
    if isinstance(repo_result, ErrorResult):
        return repo_result
    resolved_repo = str(repo_result.value)

    sha = head_sha or ""
    if pr_number is not None:
        sha_result = await _head_sha(repo=resolved_repo, pr_number=pr_number)
        if isinstance(sha_result, ErrorResult):
            return sha_result
        sha = sha_result.value

    if not _SHA_PATTERN.fullmatch(sha):
        return err(f"head_sha must be 7-40 hex characters, got {sha!r}")

    suites_result = await _gateway._gh_api_raw(
        f"repos/{resolved_repo}/commits/{sha}/check-suites?per_page=100", repo=resolved_repo
    )
    if suites_result.returncode != 0:
        return err(suites_result.stderr.strip())
    runs_result = await _gateway._gh_api_raw(
        f"repos/{resolved_repo}/actions/runs?head_sha={sha}&per_page=100", repo=resolved_repo
    )
    if runs_result.returncode != 0:
        return err(runs_result.stderr.strip())

    runs = _items(raw=runs_result.stdout, key="workflow_runs")
    if isinstance(runs, ErrorResult):
        return runs
    suites = _items(raw=suites_result.stdout, key="check_suites")
    if isinstance(suites, ErrorResult):
        return suites

    runs_by_suite = {run.get("check_suite_id"): run for run in runs.value}

    retried: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    failed: list[dict[str, str]] = []

    for suite in suites.value:
        app = suite.get("app") or {}
        run = runs_by_suite.get(suite.get("id"))
        is_actions = app.get("slug") == _ACTIONS_APP_SLUG
        name = str((run or {}).get("name") or app.get("name") or suite.get("id"))
        if not _matches(wanted=checks, names=[name, app.get("name", ""), app.get("slug", "")]):
            continue
        if suite.get("status") != "completed":
            skipped.append({"name": name, "reason": "still running"})
            continue
        if failed_only and suite.get("conclusion") not in _FAILED_CONCLUSIONS:
            skipped.append({"name": name, "reason": "not failed"})
            continue
        if is_actions and run is None:
            skipped.append({"name": name, "reason": "no workflow run found for suite"})
            continue
        attempt = int((run or {}).get("run_attempt") or 0)
        if is_actions and attempt >= MAX_RUN_ATTEMPTS:
            skipped.append({"name": name, "reason": f"retry cap reached (attempt {attempt})"})
            continue
        if len(retried) >= MAX_RETRIES_PER_CALL:
            skipped.append({"name": name, "reason": "per-call retry limit reached"})
            continue

        if is_actions:
            suffix = "rerun-failed-jobs" if failed_only else "rerun"
            endpoint = f"repos/{resolved_repo}/actions/runs/{(run or {})['id']}/{suffix}"
            kind, target_id = "actions-run", (run or {})["id"]
        else:
            endpoint = f"repos/{resolved_repo}/check-suites/{suite['id']}/rerequest"
            kind, target_id = "check-suite", suite["id"]

        post = await _gateway._gh_api_raw(endpoint, method="POST", repo=resolved_repo)
        if post.returncode != 0:
            failed.append({"name": name, "error": post.stderr.strip()})
            continue
        retried.append(
            {
                "kind": kind,
                "id": target_id,
                "name": name,
                "attempt_before": attempt if is_actions else None,
                "endpoint": endpoint,
            }
        )

    if failed and not retried:
        return err(f"GitHub refused every re-run: {failed}")
    return ok(
        {
            "repo": resolved_repo,
            "head_sha": sha,
            "failed_only": failed_only,
            "max_attempts": MAX_RUN_ATTEMPTS,
            "retried": retried,
            "skipped": skipped,
            "failed": failed,
        }
    )
