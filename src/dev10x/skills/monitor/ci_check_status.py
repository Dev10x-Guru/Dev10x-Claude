#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Check CI status for a PR and return a structured JSON verdict.

Wraps `gh pr checks --json` and summarizes check states into a single
verdict that agents can rely on without parsing text tables. Also checks
the PR's mergeable status so merge conflicts block the verdict.

Usage:
    ci-check-status.py --pr 42 --repo owner/repo
    ci-check-status.py --pr 42 --repo owner/repo --required-only
    ci-check-status.py --pr 42 --repo owner/repo --wait

The --wait flag polls internally until a terminal verdict is
reached (green, failing, or conflicting). This removes polling
logic from the agent — haiku agents no longer need to loop and
can call the script once with --wait to get a definitive answer.

Output (JSON):
    {
        "verdict": "failing",          # "green", "pending", "failing",
                                       # "conflicting", "empty",
                                       # "infra_unavailable"
        "required_verdict": "green",   # same vocabulary, computed over
                                       # required (merge-blocking) checks only
        "mergeable": "MERGEABLE",      # "MERGEABLE", "CONFLICTING", "UNKNOWN"
        "total": 5,
        "pass": 3,
        "fail": 0,
        "pending": 2,
        "skipping": 0,
        "cancel": 0,
        "checks": [
            {"name": "build", "bucket": "pass", "required": True},
            {"name": "lint", "bucket": "fail", "required": False},
            ...
        ]
    }

Verdict logic (applies to both `verdict` and `required_verdict`):
    - "conflicting" → PR has merge conflicts (regardless of CI status)
    - "empty"       → no checks found (GitHub hasn't registered suites yet)
    - "failing"     → at least one check failed
    - "pending"     → at least one check is pending (none failing)
    - "green"       → all non-skipping checks passed and no conflicts
    - "infra_unavailable" → only from --wait: checks never registered across
                      the full poll budget (likely a hosted-runner/infra
                      outage), distinct from a transient "empty"/"pending"

Required vs advisory (GH-658): `verdict` blends required (merge-blocking)
and advisory (non-required) checks into one signal, so a red advisory
check reads as "failing" even when the host's required-checks auto-merge
would proceed. `required_verdict` is the same computation restricted to
checks the host marks required (sourced from `gh pr checks --required`),
plus a per-check `required: bool`. A caller — e.g. gh-pr-merge Check 2 —
branches on `required_verdict` to tell a true merge blocker from an
advisory red without a manual per-job log fetch. When the host reports
no required checks, `required_verdict` is "empty".
"""

import argparse
import json
import subprocess
import sys
import time

from dev10x.domain.common.repository_ref import RepositoryRef

# Bound every gh subprocess so a wedged CLI cannot hang the poll loop
# indefinitely (GH-824), matching pr_notify.py / slack_review_request.py.
_SUBPROCESS_TIMEOUT_SECONDS = 30


def fetch_mergeable(
    *,
    pr_number: int,
    repo: str,
) -> str:
    cmd = [
        "gh",
        "pr",
        "view",
        str(pr_number),
        "--repo",
        repo,
        "--json",
        "mergeable",
        "-q",
        ".mergeable",
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT_SECONDS
    )
    if result.returncode != 0:
        return "UNKNOWN"
    return result.stdout.strip() or "UNKNOWN"


def get_checks(
    *,
    pr_number: int,
    repo: str,
    required_only: bool = False,
) -> list[dict]:
    cmd = [
        "gh",
        "pr",
        "checks",
        str(pr_number),
        "--repo",
        repo,
        "--json",
        "name,bucket,state",
    ]
    if required_only:
        cmd.append("--required")
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT_SECONDS
    )
    if result.returncode != 0:
        print(json.dumps({"error": f"gh pr checks failed: {result.stderr.strip()}"}))
        sys.exit(1)
    return json.loads(result.stdout)


def get_required_names(
    *,
    pr_number: int,
    repo: str,
) -> set[str]:
    """Names of the required (merge-blocking) checks for the PR.

    Sourced from `gh pr checks --required` (the `--json` output has no
    `isRequired` field). Tolerant by design: a repo with no branch
    protection returns no required checks, which must annotate as
    "all advisory" rather than abort the verdict — so any non-zero exit
    or unparseable output yields an empty set.
    """
    cmd = [
        "gh",
        "pr",
        "checks",
        str(pr_number),
        "--repo",
        repo,
        "--required",
        "--json",
        "name",
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT_SECONDS
    )
    if result.returncode != 0 or not result.stdout.strip():
        return set()
    try:
        return {check.get("name") for check in json.loads(result.stdout)}
    except json.JSONDecodeError:
        return set()


def get_annotated_checks(
    *,
    pr_number: int,
    repo: str,
    required_only: bool = False,
) -> list[dict]:
    """Fetch checks and tag each with `required` (merge-blocking) status.

    When `required_only` is set every returned check is required by
    definition; otherwise required-ness is resolved by name against
    `get_required_names`.
    """
    checks = get_checks(pr_number=pr_number, repo=repo, required_only=required_only)
    if required_only:
        for check in checks:
            check["required"] = True
        return checks
    required_names = get_required_names(pr_number=pr_number, repo=repo)
    for check in checks:
        check["required"] = check.get("name") in required_names
    return checks


def _summarize(checks: list[dict]) -> tuple[str, dict[str, int]]:
    """Bucket a check list and derive its verdict (ignores conflicts)."""
    counts: dict[str, int] = {
        "pass": 0,
        "fail": 0,
        "pending": 0,
        "skipping": 0,
        "cancel": 0,
    }
    for check in checks:
        bucket = check.get("bucket", "pending")
        if bucket in counts:
            counts[bucket] += 1
        else:
            counts["pending"] += 1

    non_skipping = counts["pass"] + counts["fail"] + counts["pending"] + counts["cancel"]

    if not checks:
        verdict = "empty"
    elif counts["fail"] > 0:
        verdict = "failing"
    elif counts["pending"] > 0 or counts["cancel"] > 0:
        verdict = "pending"
    elif non_skipping == 0:
        verdict = "empty"
    else:
        verdict = "green"

    return verdict, counts


def compute_verdict(
    *,
    checks: list[dict],
    mergeable: str = "UNKNOWN",
) -> dict:
    verdict, counts = _summarize(checks)
    required_verdict, _ = _summarize([c for c in checks if c.get("required")])

    if mergeable == "CONFLICTING":
        verdict = "conflicting"
        required_verdict = "conflicting"

    return {
        "verdict": verdict,
        "required_verdict": required_verdict,
        "mergeable": mergeable,
        "total": len(checks),
        **counts,
        "checks": [
            {
                "name": c.get("name", "unknown"),
                "bucket": c.get("bucket", "pending"),
                "required": bool(c.get("required", False)),
            }
            for c in checks
        ],
    }


def poll_until_terminal(
    *,
    pr_number: int,
    repo: str,
    required_only: bool = False,
    poll_interval: int = 30,
    initial_wait: int = 60,
    max_polls: int = 40,
) -> dict:
    """Poll CI until a terminal verdict (green, failing, conflicting).

    Waits `initial_wait` seconds for checks to register after a push,
    then polls every `poll_interval` seconds. Returns the final verdict
    dict. This removes polling logic from the agent — the script handles
    all waiting internally.

    The default budget (`initial_wait 60 + poll_interval 30 * max_polls 40`
    = 1320s) is kept below the ~1800s MCP idle-timeout so a `wait=true`
    call returns a verdict rather than being torn down mid-poll (GH-808 F2).
    A caller needing longer coverage re-invokes rather than raising the
    budget past that ceiling.
    """
    print(
        f"Waiting {initial_wait}s for checks to register...",
        file=sys.stderr,
        flush=True,
    )
    time.sleep(initial_wait)

    for attempt in range(1, max_polls + 1):
        checks = get_annotated_checks(
            pr_number=pr_number,
            repo=repo,
            required_only=required_only,
        )
        mergeable = fetch_mergeable(pr_number=pr_number, repo=repo)
        result = compute_verdict(checks=checks, mergeable=mergeable)
        verdict = result["verdict"]

        print(
            f"[poll {attempt}/{max_polls}] verdict={verdict} "
            f"pass={result['pass']} fail={result['fail']} "
            f"pending={result['pending']}",
            file=sys.stderr,
            flush=True,
        )

        if verdict in ("green", "failing", "conflicting"):
            return result

        if attempt < max_polls:
            time.sleep(poll_interval)

    # Budget exhausted with no terminal verdict (GH-808 F2). If the final poll
    # is still "empty" — no checks registered (or all skipping) after the whole
    # budget — GitHub never scheduled real runners, a hosted-runner/infra
    # outage rather than a normal "still pending" state (in practice check-runs
    # do not un-register, so an empty final poll means empty throughout).
    # Surface it as a distinct verdict so the caller can escalate (ask the
    # user, retry later) instead of reading it as a transient pending. A
    # "pending" budget-exhaustion is left as-is.
    if result["verdict"] == "empty":
        result["verdict"] = "infra_unavailable"
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Check CI status for a PR")
    parser.add_argument("--pr", type=int, required=True, help="PR number")
    parser.add_argument("--repo", required=True, help="owner/repo")
    parser.add_argument(
        "--required-only",
        action="store_true",
        help="Only check required status checks",
    )
    parser.add_argument(
        "--wait",
        action="store_true",
        help="Poll until terminal verdict (green/failing/conflicting)",
    )
    parser.add_argument(
        "--poll-interval",
        type=int,
        default=30,
        help="Seconds between polls (default: 30)",
    )
    parser.add_argument(
        "--initial-wait",
        type=int,
        default=60,
        help="Seconds to wait before first poll (default: 60)",
    )
    parser.add_argument(
        "--max-polls",
        type=int,
        default=40,
        help="Max poll attempts before giving up (default: 40, keeping the "
        "total wait under the ~1800s MCP idle-timeout)",
    )
    args = parser.parse_args()

    try:
        repo = str(RepositoryRef.parse(args.repo))
    except ValueError as exc:
        parser.error(str(exc))

    if args.wait:
        result = poll_until_terminal(
            pr_number=args.pr,
            repo=repo,
            required_only=args.required_only,
            poll_interval=args.poll_interval,
            initial_wait=args.initial_wait,
            max_polls=args.max_polls,
        )
    else:
        checks = get_annotated_checks(
            pr_number=args.pr,
            repo=repo,
            required_only=args.required_only,
        )
        mergeable = fetch_mergeable(
            pr_number=args.pr,
            repo=repo,
        )
        result = compute_verdict(checks=checks, mergeable=mergeable)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
