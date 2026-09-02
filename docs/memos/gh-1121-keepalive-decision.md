# Decision — server-side keepalive for the MCP stdio hop

GH-1121 item 2: *decide whether a server-side keepalive is worth
attempting from our end.* This is the written decision. It is not code,
and it deliberately does not re-open reconnect-on-demand — that was
settled in `skills/foreman/references/mcp-connectivity.md` and the
reasoning there stands: we cannot reconnect a transport we do not own.

Keepalive is a different question. We *do* own the server process, so
emitting traffic from our side is at least ours to attempt.

## Decision

**Attempt it — but as an opt-in experiment behind a flag, defaulting
OFF, and only together with the measurement that can falsify it. Do not
ship it on by default on the strength of the theory alone.**

## Why not simply "no"

The capability is present and cheap. The pinned SDK (`mcp>=1.0,<2`)
exposes a server-initiated ping:

```
mcp/server/session.py:443  async def send_ping(self) -> types.EmptyResult
```

with `PingRequest` at `mcp/types.py:712`. Those line numbers are from
the installed `mcp` package as resolved for the servers' PEP 723
headers, not from a path inside this repo — `mcp` is a uv-script
dependency, so a fresh checkout resolves it on first server run rather
than vendoring it. MCP's `ping` is defined for
either party to send. So this is not a "we'd have to build a mechanism"
problem — the mechanism exists, and a periodic call to it is a small
amount of code.

Given that, refusing outright would be declining a cheap shot at the
most plausible mechanism behind the failure (idle timeout on a
connection held across long blocking calls and platform pauses).

## Why not simply "yes, ship it"

Three reasons it must not default ON:

1. **We cannot observe the thing it targets.** We do not know that a
   client idle timeout exists, what its duration is, or which side
   closes the connection. Every statement about the mechanism in our
   own docs is marked "suspected". Shipping a permanent mitigation for
   an unconfirmed cause is how a codebase accumulates cargo.

2. **It is unfalsifiable without a soak.** The failure takes 60–90
   minutes to appear at the low end and ~18 hours at the high end.
   Turning on a ping and observing "no drop today" proves nothing —
   the runs that did not drop already outnumber the ones that did.
   Item 3 of GH-1121 (verify against a 60–90+ minute cycle) is not a
   separate follow-up here; it is the *precondition* for calling this
   a fix.

3. **Unsolicited traffic against an unknown client is not risk-free.**
   The client's tolerance of server-initiated requests is undocumented
   from our side. A ping stream every session, forever, could be
   ignored (no benefit, small noise), or could interact badly with a
   client that does not expect it. Defaulting OFF means the blast
   radius of being wrong is limited to whoever opts in.

## What to build, in order

1. **Measurement first.** Record, per session, the wall-clock gap
   between successive successful tool calls and whether the next call
   after a long gap failed. That is enough to establish whether
   failures cluster after idle periods and roughly where the boundary
   is. Without this number the keepalive interval is a guess.

2. **Then the flag.** An env-gated periodic `send_ping` from a
   background task in the server, default OFF, interval derived from
   step 1 (comfortably under the observed boundary).

3. **Then the soak.** Paired 60–90+ minute idle runs, ping-on vs
   ping-off, enough repetitions to say something. Only a difference
   here promotes the flag to default ON.

## What this does not change

The containment already shipped stays exactly as it is, and remains the
real protection regardless of how the experiment lands:

- Worker-side single `ToolSearch` re-resolution, then report-and-stop.
- Watchdog surface loss has no in-session recovery — gate reads may
  fall back to sanctioned `gh api`, merges queue rather than
  improvise, and the supervisor is asked.
- **A state-changing call is a request, not a receipt** — re-read the
  field you set. A keepalive, even a working one, would reduce the
  frequency of dropped writes without ever making that rule optional.

If the soak shows no effect, the answer becomes a documented "no", and
this memo is the record of why it was worth the hour to find out.
