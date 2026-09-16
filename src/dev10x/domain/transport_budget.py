"""How long one MCP tool call may run before the transport gives up.

GH-1288: the `plugin:Dev10x:cli` server died mid-session and took every
in-flight background task with it — a `run_tests` call at 18m59s and an
unrelated `ci_check_status` started thirteen minutes later, killed in the
same instant. A per-call timeout would have ended only the call that
overran; the transport went away.

Before this module the ceiling existed only as prose, in two docstrings
that `ci_check_status` budgets itself against. Nothing stopped another
long-running tool from being written without that reasoning — and
`run_tests` was exactly that tool: `timeout` defaulted to 600 but
accepted any larger value with no clamp, and the call that died had been
handed 1500. So the number lives here now, once, and the tools import it
rather than restating it.

`ci_check_status` was the tool that proved the point. It reaches the
transport by a different path — a subprocess cap summed inline from
`initial_wait + poll_interval * max_polls + 60` — so the shared constant
never reached it: its default cap was 1320s, above both observed deaths,
and `max_polls=500` bought a four-hour one. It budgets through
`polls_within_budget` now, which is why that function exists rather than
a second `clamp_tool_timeout` call: capping the subprocess alone would
kill the poll loop mid-iteration and hand the caller a non-zero exit
instead of the verdict it waited for.

**GH-1305: `MCP_IDLE_TIMEOUT_SECONDS=1800` is now a documented, not
inferred, value.** Claude Code's own MCP docs
(https://code.claude.com/docs/en/mcp, "Idle Timeout") state the
client-side idle-abort window defaults to 30 minutes for stdio servers
(the `plugin:Dev10x:cli` transport here) with no per-server `timeout`
override configured in `.claude-plugin/plugin.json`, confirmed against
the installed harness (`claude --version` → 2.1.273, i.e. past the
2.1.203 release that extended idle-timeout coverage to stdio servers —
before that release stdio servers were exempt entirely). No probe was
needed: the number was already published, which is exactly what GH-1305
asked to check first.

That documented figure does **not** explain the two ~1137s deaths GH-1288
reports, and it should not be read as if it does. Idle-timeout is a
per-call client-side abort of a call that sent no response/progress for
the idle window; the GH-1288 deaths took down the whole server process,
including calls that were themselves mid-progress, and (if they predate
the harness's 2.1.203 stdio coverage) may have happened while stdio
servers were exempt from idle-timeout altogether. These are two distinct
failure modes with two distinct ceilings, and `MAX_TOOL_CALL_SECONDS`
below defends against the GH-1288 crash symptom specifically, not
against idle-timeout — which is why it sits so far under the now-
confirmed 1800s. Raising it would need the GH-1288 crash's root cause
understood, not merely a taller idle-timeout ceiling to spend.

**A related, separate anomaly (GH-1305, unresolved):** a `run_tests` call
with the default `timeout=600` was observed by the client as "no response
or progress for 2345s" before aborting — well past both `timeout=600` and
`MAX_TOOL_CALL_SECONDS`. Reading `runner.async_run`'s `asyncio.wait_for`
handling confirms the kill-and-reap path is correct in this codebase: a
`TimeoutError` synchronously kills the process tree, reaps it, and
returns — there is no logic path here that leaves a clamped call
outstanding. The likeliest explanation is that a second full-suite run
was in flight on the same host at the time (noted in GH-1305), which
would starve the single-threaded event loop of CPU and delay when its
timer callback actually runs — a soft-realtime property of asyncio, not
a defect in this module. This was not reproduced, so it is recorded
rather than "fixed": GH-1358 tracks it, with the timestamps that would
confirm or rule out the event-loop-starvation hypothesis if it recurs.
"""

from __future__ import annotations

from typing import NamedTuple

# The client-side MCP idle-abort ceiling (GH-808 F2, GH-1104, confirmed
# GH-1305). This is the documented default for a *stdio* MCP server with
# no per-server `timeout` override (see `.claude-plugin/plugin.json`),
# per https://code.claude.com/docs/en/mcp "Idle Timeout" — checked
# against the installed harness version (>= 2.1.203, which is when idle
# timeout coverage was extended to stdio servers at all). It is a
# confirmed value, not an inference from observed deaths.
MCP_IDLE_TIMEOUT_SECONDS = 1800

# What a single tool call may ask for.
#
# This is NOT the idle-timeout ceiling above, and must not be read as
# one — it defends against a *different, still-unexplained* failure:
# GH-1288's whole-server crash, observed twice at ~1137s elapsed, which
# took down every in-flight call rather than aborting just the one that
# overran. A budget above that would have let the reported run die
# exactly as it did, making the clamp cosmetic for the case that
# motivated it. Sitting below the observations costs a suite that
# genuinely needs 18+ minutes — but such a suite was already dying, and
# now gets a timeout verdict it can act on instead of a dropped socket.
#
# GH-1305 confirmed `MCP_IDLE_TIMEOUT_SECONDS` above but did NOT explain
# the GH-1288 deaths — they may predate stdio idle-timeout coverage
# entirely, or be an unrelated crash. Raising this needs the GH-1288
# crash's root cause understood, not a taller idle-timeout ceiling to
# spend against it.
MAX_TOOL_CALL_SECONDS = 1080


class ClampedTimeout(NamedTuple):
    """A requested timeout and what it was actually allowed to be."""

    seconds: float
    requested: float

    @property
    def was_clamped(self) -> bool:
        return self.seconds < self.requested


def clamp_tool_timeout(requested: float) -> ClampedTimeout:
    """Hold a tool call's timeout below the transport's patience.

    Returning the request alongside the effective value lets a caller say
    which happened: a suite that genuinely needs longer than the
    transport allows is a different problem from one that hung, and
    `Connection closed` conflates them.
    """
    return ClampedTimeout(seconds=min(requested, MAX_TOOL_CALL_SECONDS), requested=requested)


class ClampedPolls(NamedTuple):
    """A requested poll count and how many the budget actually affords."""

    polls: int
    requested: int

    @property
    def was_clamped(self) -> bool:
        return self.polls < self.requested


def polls_within_budget(
    *,
    requested: int,
    poll_interval: float,
    initial_wait: float,
    overhead: float,
) -> ClampedPolls:
    """How many polls a waiting tool may take and still report back.

    Clamping only the outer subprocess timeout would trade one opaque
    failure for another: the poll loop would be killed mid-iteration and
    the caller would read a non-zero exit where it expected a verdict.
    The loop has to be told to stop early enough to answer, so the poll
    count comes down with the cap rather than after it.

    `overhead` is whatever the caller spends outside the loop — process
    start-up, a final probe — and is charged against the budget so the
    margin protects the whole call, not just its polling.
    """
    if poll_interval <= 0:
        return ClampedPolls(polls=requested, requested=requested)
    room = MAX_TOOL_CALL_SECONDS - initial_wait - overhead
    affordable = int(room // poll_interval)
    return ClampedPolls(polls=max(0, min(requested, affordable)), requested=requested)
