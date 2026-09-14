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

**The ceiling is not confirmed.** Two deaths were observed at ~1135s and
~1139s elapsed, both comfortably under the 1800s the code budgets
against. If the effective idle ceiling in this harness is nearer 1140s,
then `ci_check_status`'s own 1320s subprocess cap sits above it too and
would fail the same way on a slow-CI PR. GH-1288 item 5 asks for a real
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
