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

Under --wait, a failed NON-required check does not end the wait
while other legs are still pending (GH-1065): the caller cannot
act on "failing, 3 pending", so returning it just hands the
polling back. The loop settles the remaining legs first and then
returns the full verdict with the failed leg named. A failed
REQUIRED check still returns immediately — it blocks the merge
regardless. --no-wait-out-pending restores the old early return.

Output (JSON):
    {
        "verdict": "failing",          # "green", "pending", "failing",
                                       # "conflicting", "empty",
                                       # "infra_unavailable"
        "required_verdict": "green",   # same vocabulary, computed over
                                       # required (merge-blocking) checks only
        "checks_source": "gh-pr-checks",  # "gh-pr-checks", "runs-api",
                                       # "confirmed-zero" — where the list came
                                       # from, so an "empty" verdict says
                                       # whether the zero was corroborated
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
no required checks, `required_verdict` is "empty" — this is a normal
terminal value on a repo with no required status checks configured
(e.g. ADR-0024 in this repo), not a sign that required checks are
still pending. A merge decision branches on the blended `verdict`,
not `required_verdict`; `required_verdict` only disambiguates a
`verdict: "failing"` into a true blocker vs. an advisory red (GH-1381).

Corroborated zeros (GH-1376): `gh pr checks` under-reports, so a zero
read is cross-checked against the Actions runs API for the PR's head SHA
before it is reported, and `checks_source` names the source. The extra
two API calls are paid ONLY on the zero path — never on a call that has
checks to report — so the common poll costs exactly what it did before.
A runs-API call that cannot be made degrades to an `undetermined` error,
never to a zero and never to a green.
"""

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import NoReturn

from dev10x.domain.common.repository_ref import RepositoryRef

# Bound every gh subprocess so a wedged CLI cannot hang the poll loop
# indefinitely (GH-824), matching pr_notify.py / slack_review_request.py.
_SUBPROCESS_TIMEOUT_SECONDS = 30

# Where a check list came from, reported as `checks_source` so a caller
# can tell a corroborated zero from an uncorroborated one (GH-1376).
SOURCE_GH_CLI = "gh-pr-checks"
SOURCE_RUNS_API = "runs-api"
SOURCE_CONFIRMED_ZERO = "confirmed-zero"

# `gh pr checks` says this on stderr, and exits non-zero, when it sees no
# checks — the same sentence for a PR that genuinely has none and for one
# whose checks it failed to see (GH-1376).
_NO_CHECKS_STDERR = "no checks reported"

_RUNS_PAGE_SIZE = 50

# GitHub run conclusions that are not "this check passed". Anything not
# named here and not a success-shaped conclusion is read as a failure,
# so a conclusion this map has never heard of never reads as green.
_CONCLUSION_BUCKETS = {
    "success": "pass",
    "neutral": "pass",
    "skipped": "skipping",
    "cancelled": "cancel",
    "stale": "cancel",
}


@dataclass(frozen=True)
class ChecksRead:
    """A check list plus where it came from (GH-1376).

    `source` is the difference between "GitHub told us there are zero
    checks and the runs API agrees" and "one API said zero" — a
    distinction the caller of a zero verdict has to be able to make,
    because merging on the first is fine and merging on the second is
    merging blind.
    """

    checks: list[dict]
    source: str


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


def read_checks(
    *,
    pr_number: int,
    repo: str,
    required_only: bool = False,
) -> ChecksRead:
    """Fetch the PR's checks, corroborating a zero read before returning it.

    GH-1376: `gh pr checks` under-reports. PR #1372 had a completed,
    successful `PR Hygiene Review` run that the runs API listed and the
    CLI did not — persistently, across two sessions. Because this wrapper
    is the only sanctioned CI-wait path, that read is load-bearing: an
    agent told "no checks will ever register" either merges believing CI
    cannot run, or waits for something it has been told will never come.
    A zero is therefore checked against a second source before it is
    reported, and the payload says which source produced it.

    `required_only` reads are exempt: an empty required set is the
    NORMAL state on an unprotected base (ADR-0024), and the runs API
    cannot tell which of the runs it lists the host marks required, so
    corroborating there would invent required checks.
    """
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
    # GH-1192: `gh pr checks` signals the VERDICT through its exit code —
    # 8 when checks are pending, 1 when some failed — and still writes the
    # requested JSON to stdout. Treating any non-zero exit as a call
    # failure aborted on every PR that had anything other than all-green
    # checks, and did so with empty stderr, so the caller received
    # `{"error": ""}`: no cause, and indistinguishable from success to
    # anything branching on truthiness. Parseable stdout IS the answer.
    parsed = _parse_checks_json(result.stdout)
    if parsed:
        return ChecksRead(checks=parsed, source=SOURCE_GH_CLI)
    if parsed == [] or _NO_CHECKS_STDERR in result.stderr.lower():
        if required_only:
            return ChecksRead(checks=[], source=SOURCE_GH_CLI)
        return corroborate_zero_checks(pr_number=pr_number, repo=repo)
    if result.returncode != 0:
        _abort(_gh_checks_failure(result))
    _abort(f"gh pr checks returned unparseable output: {result.stdout[:200]}")


def get_checks(
    *,
    pr_number: int,
    repo: str,
    required_only: bool = False,
) -> list[dict]:
    return read_checks(
        pr_number=pr_number,
        repo=repo,
        required_only=required_only,
    ).checks


def _abort(message: str, **extra: object) -> NoReturn:
    """Emit a stdout error blob and exit non-zero.

    Errors go to stdout because this script's stdout is what the MCP
    wrapper parses — a caller must never have to read two channels to
    learn a call failed.
    """
    print(json.dumps({"error": message, **extra}))
    sys.exit(1)


def corroborate_zero_checks(
    *,
    pr_number: int,
    repo: str,
) -> ChecksRead:
    """Second-source a "no checks" read against the Actions runs API.

    Three outcomes, and the third is the point: a runs-API call that
    itself fails must degrade to "could not determine" rather than to
    either a confirmed zero or a green. An unreadable second source is
    not evidence about the first.
    """
    head = fetch_head_ref(pr_number=pr_number, repo=repo)
    if head is None:
        _abort(
            "gh pr checks reported no checks and the PR's head ref could not be "
            "read to corroborate it — undetermined, not zero checks",
            undetermined=True,
        )
    branch, head_sha = head
    runs = fetch_branch_runs(repo=repo, branch=branch)
    if runs is None:
        _abort(
            "gh pr checks reported no checks and the Actions runs API could not "
            f"be reached to corroborate it for '{branch}' — undetermined, not "
            "zero checks",
            undetermined=True,
        )
    at_head = [run for run in runs if run.get("head_sha") == head_sha]
    if not at_head:
        return ChecksRead(checks=[], source=SOURCE_CONFIRMED_ZERO)
    return ChecksRead(checks=checks_from_runs(at_head), source=SOURCE_RUNS_API)


def fetch_head_ref(
    *,
    pr_number: int,
    repo: str,
) -> tuple[str, str] | None:
    """The PR's `(head branch, head SHA)`, or None when unreadable."""
    cmd = [
        "gh",
        "pr",
        "view",
        str(pr_number),
        "--repo",
        repo,
        "--json",
        "headRefName,headRefOid",
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT_SECONDS
    )
    if result.returncode != 0:
        return None
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    branch = payload.get("headRefName")
    head_sha = payload.get("headRefOid")
    if not branch or not head_sha:
        return None
    return branch, head_sha


def fetch_branch_runs(
    *,
    repo: str,
    branch: str,
) -> list[dict] | None:
    """Workflow runs the Actions API lists for `branch`, or None on failure.

    An empty list means the API answered and saw nothing; None means it
    did not answer. Collapsing the two is the bug this whole path exists
    to avoid.
    """
    cmd = [
        "gh",
        "api",
        f"repos/{repo}/actions/runs?branch={branch}&per_page={_RUNS_PAGE_SIZE}",
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT_SECONDS
    )
    if result.returncode != 0:
        return None
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    runs = payload.get("workflow_runs") if isinstance(payload, dict) else None
    return runs if isinstance(runs, list) else None


def checks_from_runs(runs: list[dict]) -> list[dict]:
    """Shape workflow runs like `gh pr checks` entries, newest run per name.

    The runs API lists newest first and a re-run adds a row rather than
    replacing one, so the first occurrence of a name is the current one.
    """
    checks: list[dict] = []
    seen: set[str] = set()
    for run in runs:
        name = run.get("name") or "unknown"
        if name in seen:
            continue
        seen.add(name)
        checks.append({"name": name, "bucket": _run_bucket(run), "state": run.get("status")})
    return checks


def _run_bucket(run: dict) -> str:
    if run.get("status") != "completed":
        return "pending"
    return _CONCLUSION_BUCKETS.get(run.get("conclusion") or "", "fail")


def _parse_checks_json(stdout: str) -> list[dict] | None:
    """Return the decoded check list, or ``None`` when stdout is not one."""
    if not stdout.strip():
        return None
    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, list) else None


def _gh_checks_failure(result: subprocess.CompletedProcess[str]) -> str:
    """A never-empty diagnostic for a genuinely failed `gh pr checks` call.

    `gh` exits non-zero with no stderr in several situations, so the exit
    code has to carry the message when nothing else can.
    """
    stderr = result.stderr.strip()
    if stderr:
        return f"gh pr checks failed (exit {result.returncode}): {stderr}"
    stdout = result.stdout.strip()
    if stdout:
        return f"gh pr checks failed (exit {result.returncode}): {stdout[:200]}"
    return f"gh pr checks failed (exit {result.returncode}) with no output"


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
) -> ChecksRead:
    """Fetch checks and tag each with `required` (merge-blocking) status.

    When `required_only` is set every returned check is required by
    definition; otherwise required-ness is resolved by name against
    `get_required_names`. The read's `source` is carried through so the
    verdict can report where a zero came from (GH-1376).
    """
    read = read_checks(pr_number=pr_number, repo=repo, required_only=required_only)
    if required_only:
        for check in read.checks:
            check["required"] = True
        return read
    required_names = get_required_names(pr_number=pr_number, repo=repo)
    for check in read.checks:
        check["required"] = check.get("name") in required_names
    return read


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
    checks_source: str = SOURCE_GH_CLI,
) -> dict:
    verdict, counts = _summarize(checks)
    required_verdict, _ = _summarize([c for c in checks if c.get("required")])

    if mergeable == "CONFLICTING":
        verdict = "conflicting"
        required_verdict = "conflicting"

    return {
        "verdict": verdict,
        "required_verdict": required_verdict,
        "checks_source": checks_source,
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


SETTLED_BUCKETS = frozenset({"pass", "fail", "skipping", "cancel"})


def unsettled_named_checks(*, result: dict, wait_for: list[str]) -> list[str]:
    """Names from ``wait_for`` that have not reached a terminal bucket.

    A named check that has not registered yet counts as unsettled — that
    is the state a caller waiting for a bot leg most needs to sit
    through. The poll budget, not this function, bounds a leg that never
    appears at all.
    """
    buckets = {check["name"]: check["bucket"] for check in result["checks"]}
    return [name for name in wait_for if buckets.get(name) not in SETTLED_BUCKETS]


def is_terminal(
    *,
    result: dict,
    wait_out_pending: bool = True,
    wait_for: list[str] | None = None,
) -> bool:
    """Whether a poll result ends the wait.

    ``green`` and ``conflicting`` always do. ``failing`` is where GH-1065
    lives: the blended verdict flips the moment ANY check fails, required or
    not, so one red advisory check ended the wait while every other leg was
    still pending. Pending is not green, so that early return gave the caller
    nothing to act on — only a reason to poll again by hand, which is exactly
    the work ``wait=true`` exists to absorb.

    With ``wait_out_pending`` (the default) a blended failure is terminal only
    once nothing is outstanding. A REQUIRED failure stays terminal on sight:
    it blocks the merge no matter how the remaining legs land.

    ``wait_for`` (GH-1138) names checks that must settle before the wait
    ends, and it OUTRANKS the required-failure early return. That early
    return is correct for a caller deciding whether to merge, and wrong
    for the one this parameter serves: on any branch carrying ``fixup!``
    commits the required ``git-history-linting`` leg fails *by design*
    until squash, so "required red + advisory legs pending" is a routine
    mid-review state. A caller that must not groom until the review bots
    have anchored their comments got an instant ``failing`` there and no
    way to keep waiting — which is how a 20-line hand-rolled
    ``while … gh pr checks … sleep 30`` loop ended up dispatched through
    a tool no Dev10x hook validates. ``conflicting`` still returns
    immediately: nothing further will run.
    """
    verdict = result["verdict"]
    if verdict == "conflicting":
        return True
    if wait_for:
        return not unsettled_named_checks(result=result, wait_for=wait_for)
    if verdict == "green":
        return True
    if verdict != "failing":
        return False
    if not wait_out_pending:
        return True
    if result["required_verdict"] == "failing":
        return True
    return result["pending"] == 0 and result["cancel"] == 0


def probe_once(
    *,
    pr_number: int,
    repo: str,
    required_only: bool = False,
) -> dict:
    """Fetch checks and mergeability once and derive the verdict."""
    read = get_annotated_checks(
        pr_number=pr_number,
        repo=repo,
        required_only=required_only,
    )
    mergeable = fetch_mergeable(pr_number=pr_number, repo=repo)
    return compute_verdict(checks=read.checks, mergeable=mergeable, checks_source=read.source)


def poll_until_terminal(
    *,
    pr_number: int,
    repo: str,
    required_only: bool = False,
    poll_interval: int = 30,
    initial_wait: int = 60,
    max_polls: int = 40,
    wait_out_pending: bool = True,
    wait_for: list[str] | None = None,
) -> dict:
    """Poll CI until a terminal verdict (green, failing, conflicting).

    Probes once up front and returns immediately when the verdict is
    already terminal (GH-1088) — a call made after CI finished costs one
    API round trip, not `initial_wait`. Otherwise waits `initial_wait`
    seconds for checks to register after a push, then polls every
    `poll_interval` seconds. Returns the final verdict dict. This removes
    polling logic from the agent — the script handles all waiting
    internally.

    `wait_out_pending` (default True, GH-1065) keeps polling through a
    failed NON-required check until no leg is pending, then returns the
    full verdict with the failed leg named in `checks`. Pass False for the
    pre-GH-1065 behaviour of returning on the first blended failure. Either
    way the poll budget still bounds the loop, so a leg that never settles
    ends the wait rather than hanging it.

    `wait_for` (GH-1138) names checks that must settle before the wait
    ends, even when a REQUIRED check has already failed — the state every
    branch carrying `fixup!` commits is in, since `git-history-linting`
    fails by design until squash. Use it when the next step would
    invalidate what the pending legs anchor to (grooming force-pushes the
    SHAs review-bot comments reference). The poll budget bounds it like
    every other wait.

    The poll budget is kept below the MCP idle-timeout so a `wait=true`
    call returns a verdict rather than being torn down mid-poll (GH-808
    F2). `dev10x.monitor` no longer trusts its caller for that: it asks
    `polls_within_budget` how many polls `MAX_TOOL_CALL_SECONDS` affords
    and passes that number here, so `--max-polls` arrives already
    reduced (GH-1288). At the defaults it grants 32, making the in-loop
    budget `60 + 30 * 31` = 990s — ×31, not ×32, because the loop skips
    the sleep after the final poll — under a distinct 1080s subprocess
    cap. Do not read the cap as the poll budget; they are two ceilings
    (GH-1104). A caller needing longer coverage re-invokes rather than
    raising the budget past the transport's patience.
    """
    # Fast path (GH-1088): a caller that reaches this after CI already
    # finished should not pay `initial_wait` for a verdict that is already
    # decided. Probe before sleeping. An unregistered check set summarizes
    # as "empty", which `is_terminal` rejects, so a genuine post-push call
    # still falls through to the wait below.
    result = probe_once(pr_number=pr_number, repo=repo, required_only=required_only)
    if is_terminal(result=result, wait_out_pending=wait_out_pending):
        print(
            f"[fast-path] verdict={result['verdict']} already terminal — not waiting",
            file=sys.stderr,
            flush=True,
        )
        return result

    print(
        f"Waiting {initial_wait}s for checks to register...",
        file=sys.stderr,
        flush=True,
    )
    time.sleep(initial_wait)

    for attempt in range(1, max_polls + 1):
        result = probe_once(pr_number=pr_number, repo=repo, required_only=required_only)
        verdict = result["verdict"]

        print(
            f"[poll {attempt}/{max_polls}] verdict={verdict} "
            f"pass={result['pass']} fail={result['fail']} "
            f"pending={result['pending']}",
            file=sys.stderr,
            flush=True,
        )

        if is_terminal(result=result, wait_out_pending=wait_out_pending, wait_for=wait_for):
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
    parser.add_argument(
        "--no-wait-out-pending",
        dest="wait_out_pending",
        action="store_false",
        help="End the wait on the first failing check even while other legs "
        "are pending (pre-GH-1065 behaviour)",
    )
    parser.add_argument(
        "--wait-for",
        action="append",
        default=None,
        metavar="CHECK",
        help="Keep polling until this check settles, even if a REQUIRED "
        "check has already failed (repeatable, GH-1138). Use when the "
        "next step invalidates what the pending legs anchor to.",
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
            wait_out_pending=args.wait_out_pending,
            wait_for=args.wait_for,
        )
    else:
        result = probe_once(
            pr_number=args.pr,
            repo=repo,
            required_only=args.required_only,
        )

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
