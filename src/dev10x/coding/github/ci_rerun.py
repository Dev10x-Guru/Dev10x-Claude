"""Bounded CI re-run capability (GH-1674).

Re-runs failed GitHub Actions jobs and re-requests third-party GitHub App
check suites for one PR head, so an agent never needs the raw
``gh api --method POST`` shape that sits on an ask rule.

Dependencies are reached through ``_gateway.<name>`` (ADR-0027 D2).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from dev10x.core.github import _gateway
from dev10x.domain.common.result import ErrorResult, Result, err, ok
from dev10x.domain.dev10x_paths import Dev10xConfigDir
from dev10x.domain.file_locks import locked_json_update

#: Actions runs at or past this ``run_attempt`` are refused. The counter
#: lives on GitHub, so the cap is stateless and survives across sessions
#: and worktrees without a local store. Third-party suites have no such
#: counter, so theirs is kept in :func:`attempts_path` (GH-1724).
MAX_RUN_ATTEMPTS = 3

#: Upper bound on re-runs issued by one call, so a PR with dozens of
#: failing suites cannot fan out into a burst of POSTs.
MAX_RETRIES_PER_CALL = 10

#: GitHub's page size cap, and how many pages a listing may follow before
#: it is reported as ``truncated`` rather than silently cut short.
PAGE_SIZE = 100
MAX_LISTING_PAGES = 10

_ATTEMPTS_FILENAME = "ci-rerun-attempts.json"

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


async def _list_all(*, endpoint: str, key: str, repo: str) -> Result[tuple[list[dict], bool]]:
    """Every item of a paged listing, and whether the page ceiling cut it."""
    items: list[dict[str, Any]] = []
    for page in range(1, MAX_LISTING_PAGES + 1):
        paged = endpoint if page == 1 else f"{endpoint}&page={page}"
        result = await _gateway._gh_api_raw(paged, repo=repo)
        if result.returncode != 0:
            return err(result.stderr.strip())
        page_items = _items(raw=result.stdout, key=key)
        if isinstance(page_items, ErrorResult):
            return page_items
        items.extend(page_items.value)
        if len(page_items.value) < PAGE_SIZE:
            return ok((items, False))
    return ok((items, True))


def attempts_path() -> Path:
    """Where third-party suite re-request counts persist across calls."""
    return Dev10xConfigDir.home() / _ATTEMPTS_FILENAME


def _attempt_key(*, repo: str, pr_number: int | None, sha: str) -> str:
    return f"{repo}#{pr_number}" if pr_number is not None else f"{repo}@{sha}"


def _third_party_attempts(*, key: str) -> dict[str, int]:
    path = attempts_path()
    if not path.exists():
        return {}
    try:
        counts = json.loads(path.read_text()).get(key, {})
    except (OSError, ValueError, AttributeError):
        return {}
    return counts if isinstance(counts, dict) else {}


def _record_third_party_attempt(*, key: str, suite_id: int) -> str | None:
    """Count one re-request; return why it could not be stored, or None.

    The POST already went out, so a store failure is reported rather than
    turned into an error for a re-run that did happen.
    """
    try:
        with locked_json_update(attempts_path()) as data:
            counts = data.setdefault(key, {})
            counts[str(suite_id)] = int(counts.get(str(suite_id), 0)) + 1
    except (OSError, ValueError, AttributeError) as exc:
        return f"could not record the attempt in {attempts_path()}: {exc}"
    return None


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
    re-runs. A third-party suite exposes no attempt counter, so its
    re-requests are counted in :func:`attempts_path`, keyed by repo and PR
    (or head SHA), and it stops at the same cap (GH-1724). Both listings
    are paginated up to ``MAX_LISTING_PAGES``; hitting that ceiling sets
    ``truncated`` instead of silently dropping checks.

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
        ``{"repo", "head_sha", "failed_only", "max_attempts",
        "truncated", "retried": [{"kind", "id", "name",
        "attempt_before", "endpoint"}], "skipped": [{"name", "reason"}],
        "failed": [{"name", "error"}], "warnings": [str]}``. An error is
        returned only when nothing was retried and at least one re-run
        was refused by GitHub.
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

    suites = await _list_all(
        endpoint=f"repos/{resolved_repo}/commits/{sha}/check-suites?per_page={PAGE_SIZE}",
        key="check_suites",
        repo=resolved_repo,
    )
    if isinstance(suites, ErrorResult):
        return suites
    runs = await _list_all(
        endpoint=f"repos/{resolved_repo}/actions/runs?head_sha={sha}&per_page={PAGE_SIZE}",
        key="workflow_runs",
        repo=resolved_repo,
    )
    if isinstance(runs, ErrorResult):
        return runs
    suite_list, suites_truncated = suites.value
    run_list, runs_truncated = runs.value

    runs_by_suite = {run.get("check_suite_id"): run for run in run_list}
    attempt_key = _attempt_key(repo=resolved_repo, pr_number=pr_number, sha=sha)
    third_party_attempts = _third_party_attempts(key=attempt_key)

    retried: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    failed: list[dict[str, str]] = []
    warnings: list[str] = []

    for suite in suite_list:
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
        if is_actions:
            attempt = int((run or {}).get("run_attempt") or 0)
        else:
            attempt = 1 + int(third_party_attempts.get(str(suite.get("id")), 0))
        if attempt >= MAX_RUN_ATTEMPTS:
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
        if not is_actions:
            warning = _record_third_party_attempt(key=attempt_key, suite_id=suite["id"])
            if warning:
                warnings.append(warning)
        retried.append(
            {
                "kind": kind,
                "id": target_id,
                "name": name,
                "attempt_before": attempt,
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
            "truncated": suites_truncated or runs_truncated,
            "retried": retried,
            "skipped": skipped,
            "failed": failed,
            "warnings": warnings,
        }
    )
