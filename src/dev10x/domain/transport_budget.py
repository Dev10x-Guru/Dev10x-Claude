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

**The ceiling is not confirmed.** Two deaths were observed at ~1135s and
~1139s elapsed, both comfortably under the 1800s the code budgets
against. If the effective idle ceiling in this harness is nearer 1140s,
`MCP_IDLE_TIMEOUT_SECONDS` is wrong and every budget derived from
`MAX_TOOL_CALL_SECONDS` is merely lucky. GH-1288 item 5 asks for a real
measurement before anyone tunes a constant to that inference, so
`MCP_IDLE_TIMEOUT_SECONDS` keeps the documented value and the margin
below does the defending. Do not lower it to 1140 on the strength of two
data points — instrument the transport first.
"""

from __future__ import annotations

from typing import NamedTuple

# The documented transport idle ceiling (GH-808 F2, GH-1104). Treated as
# an upper bound on what the transport tolerates, not as a measurement.
MCP_IDLE_TIMEOUT_SECONDS = 1800

# What a single tool call may ask for.
#
# This is NOT a measurement of the ceiling, and must not be read as one.
# It is the largest budget defensible on the evidence: both observed
# deaths landed at ~1137s, so a budget above that would have let the
# reported run die exactly as it did, making the clamp cosmetic for the
# case that motivated it. Sitting below the observations costs a suite
# that genuinely needs 18+ minutes — but such a suite was already dying,
# and now gets a timeout verdict it can act on instead of a dropped
# socket.
#
# Raising this needs the GH-1288 item 5 measurement, not an argument that
# some suite would like more room.
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
