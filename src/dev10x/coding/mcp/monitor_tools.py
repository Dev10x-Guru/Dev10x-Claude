"""Monitor MCP tool registrations (split from github_tools.py, GH-585)."""

from __future__ import annotations

from dev10x.domain.common.result import to_wire
from dev10x.mcp._app import server


@server.tool()
async def ci_check_status(
    pr_number: int,
    repo: str | None = None,
    required_only: bool = False,
    wait: bool = False,
    poll_interval: int = 30,
    initial_wait: int = 60,
    max_polls: int = 40,
    wait_out_pending: bool = True,
    wait_for: list[str] | None = None,
    cwd: str | None = None,
) -> dict:
    """Check CI status for a PR and return a structured verdict.

    Args:
        pr_number: PR number
        repo: Repository in owner/repo format. Auto-detected from cwd if omitted.
        required_only: Only check required status checks
        wait: Poll until terminal verdict (green/failing/conflicting)
        poll_interval: Seconds between polls (default 30)
        initial_wait: Initial wait before first poll (default 60)
        max_polls: Maximum number of polls to request. A request is
            granted only as far as ``MAX_TOOL_CALL_SECONDS`` affords
            (GH-1288), so the default 40 is served as 32: an in-loop poll
            budget of 990s and a subprocess cap of 1080s. Asking for more
            does not buy more — the ceiling is the transport's patience,
            not this tool's willingness — so a PR needing longer coverage
            is re-checked with a second call rather than one long one.
        wait_out_pending: Under ``wait``, keep polling through a failed
            NON-required check until no leg is pending (default True,
            GH-1065). A failed REQUIRED check still returns immediately.
            Set False for the old return-on-first-failure behaviour.
        wait_for: Check names that must settle before the wait ends, even
            when a REQUIRED check has already failed (GH-1138). On any
            branch carrying ``fixup!`` commits the required
            ``git-history-linting`` leg fails by design until squash, so
            "required red + advisory legs pending" is routine — and
            ``wait_out_pending`` does not cover it. Pass the bot legs
            (e.g. ``["claude-review", "hygiene-review"]``) when the next
            step would invalidate what they anchor to, such as a groom
            that force-pushes the SHAs their comments reference. A named
            check that never registers keeps the wait alive until the poll
            budget ends and is listed in ``unregistered`` (GH-1679).
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with verdict (green/pending/failing/conflicting/empty/
        infra_unavailable), mergeable status, and check details. A
        ``wait=true`` call that exhausts its budget while checks never
        register returns ``infra_unavailable`` — the caller re-invokes or
        escalates rather than treating it as a transient pending. A
        ``failing`` verdict from a ``wait_out_pending`` run names the failed
        leg in ``checks`` and reports ``pending: 0``, so the caller can tell
        an advisory red apart from an unfinished run. ``checks_source``
        (GH-1376) says where the list came from — ``confirmed-zero`` when a
        zero was corroborated against the Actions runs API, ``runs-api``
        when that cross-check overturned a false "no checks reported", and
        ``gh-pr-checks`` otherwise. A cross-check that cannot be made
        returns an error carrying ``undetermined: true``, never a zero.
        A ``green`` is cross-checked the same way (GH-1679): any run for
        the head SHA still queued or in progress turns it into ``pending``
        with ``checks_source: "runs-api-pending"`` and the run names in
        ``running_runs``, because ``gh pr checks`` lists a partial set
        right after a push.
        ``is_draft`` is read alongside ``mergeable``; on a draft with
        skipped checks a ``verdict_caveat`` says the verdict is not real
        (GH-1604).
        ``disabled_checks`` names the skipped ``claude-review`` /
        ``hygiene-review`` checks that were switched off on purpose — the
        ``skip-claude-review`` label, or ``CLAUDE_REVIEW_ENABLED=false`` as a
        repo or org Actions variable — and ``review_disabled_reason`` says
        which (GH-1764). Read it instead of probing labels and variables:
        a name in ``skipping_checks`` but not in ``disabled_checks`` is a
        review that never fired.
    """
    from dev10x import monitor as mon
    from dev10x.subprocess_utils import use_cwd

    with use_cwd(cwd):
        return to_wire(
            await mon.ci_check_status(
                pr_number=pr_number,
                repo=repo,
                required_only=required_only,
                wait=wait,
                poll_interval=poll_interval,
                initial_wait=initial_wait,
                max_polls=max_polls,
                wait_out_pending=wait_out_pending,
                wait_for=wait_for,
            )
        )


@server.tool()
async def pr_wait(
    pr_number: int,
    until: str,
    repo: str | None = None,
    poll_interval: int = 30,
    max_polls: int = 40,
    since_sha: str | None = None,
    bot: str | None = None,
    cwd: str | None = None,
) -> dict:
    """Block until a PR condition holds, cannot hold, or the budget ends (GH-1833).

    Args:
        pr_number: PR number
        until: One of merged, closed, merged_or_closed, head_changed,
            approved, bot_at_head. ``closed`` means closed WITHOUT merge;
            ``merged_or_closed`` accepts either.
        repo: Repository in owner/repo format. Auto-detected from cwd if omitted.
        poll_interval: Seconds between polls (default 30, floor 5)
        max_polls: Polls to request. Granted only as far as
            ``MAX_TOOL_CALL_SECONDS`` affords (GH-1288), so the default 40
            at 30s is served as 34. Asking for more does not buy more — a
            longer wait is a second call or a background Monitor.
        since_sha: Baseline head for ``head_changed``; defaults to the
            head read on the first poll.
        bot: Bot login for ``bot_at_head`` (``[bot]`` suffix optional).
            When omitted, any bot-authored PR review at the head counts.
        cwd: Effective working directory (GH-979).

    Returns:
        ``met`` / ``timed_out`` / ``unreachable`` booleans, ``observed``
        (state, merged, head_sha, plus the condition's own evidence),
        ``polls`` / ``polls_granted`` / ``polls_requested`` /
        ``budget_clamped``, and ``probe_errors`` for polls that could not
        read the PR. ``unreachable`` ends the wait early when the PR left
        the state the condition needs — merged while waiting for
        ``closed``, closed while waiting for an approval.
    """
    from dev10x.coding.monitor import pr_wait as pw
    from dev10x.subprocess_utils import use_cwd

    with use_cwd(cwd):
        return to_wire(
            await pw.pr_wait(
                pr_number=pr_number,
                until=until,
                repo=repo,
                poll_interval=poll_interval,
                max_polls=max_polls,
                since_sha=since_sha,
                bot=bot,
            )
        )


@server.tool()
async def wait_for(
    kind: str,
    target: str,
    timeout: float = 300,
    pattern: str | None = None,
    poll_interval: float = 2.0,
    expect_status: int | None = None,
    cwd: str | None = None,
) -> dict:
    """Block until a local condition holds or the timeout ends (GH-1833).

    Args:
        kind: One of file, file_text, regex, http, process_gone, time.
        target: Path for file / file_text / regex (relative to ``cwd``);
            http(s) URL for http; PID or ``pgrep -f`` pattern for
            process_gone; ISO-8601 timestamp for time (naive means UTC).
        timeout: Seconds to wait (default 300). Clamped to
            ``MAX_TOOL_CALL_SECONDS``; ``clamped`` says when it was.
        pattern: Literal text for file_text, regex for regex.
        poll_interval: Seconds between probes (default 2).
        expect_status: Exact HTTP status for http; any 2xx/3xx when omitted.
        cwd: Effective working directory (GH-979).

    Returns:
        ``met``, ``timed_out``, ``unreachable``, ``observed`` (what the
        last probe saw), ``polls``, ``elapsed``, ``timeout``,
        ``timeout_requested`` and ``clamped``. Never an exit code: a
        condition that did not hold is ``met: false``, not an error.
        ``unreachable: true`` means the probe could never succeed (no
        ``pgrep``, a pattern ``pgrep`` rejects, a target that is not a
        readable regular file) and the wait ended early (GH-1852); a
        refused HTTP connection keeps waiting.
    """
    from dev10x.coding.monitor import wait_for as wf
    from dev10x.subprocess_utils import use_cwd

    with use_cwd(cwd):
        return to_wire(
            await wf.wait_for(
                kind=kind,
                target=target,
                timeout=timeout,
                pattern=pattern,
                poll_interval=poll_interval,
                expect_status=expect_status,
            )
        )
