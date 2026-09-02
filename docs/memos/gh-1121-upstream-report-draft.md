# DRAFT — upstream report: MCP stdio connection dies mid-session

> **STATUS: NOT FILED. Draft only.**
>
> This is prepared text for a report against the harness's MCP client.
> Filing it is outward-facing publication and is the supervisor's call,
> not an agent's. Nothing here has been sent anywhere. Review, edit,
> and file manually — or tell the agent to, explicitly.
>
> Prepared for GH-1121 item 1.

---

## Summary

A long-lived MCP stdio server connection is dropped by the client
mid-session, with no error surfaced to the agent and no way to
re-establish it from inside the session. Two distinct presentations,
both reproducible on runs of 60+ minutes.

The server side implements no timeout, keepalive, or ping on this
connection, so the disconnect originates in the client or the
transport beneath it.

## Environment

- Client: Claude Code harness MCP client (stdio transport)
- Server: local stdio MCP server, Python, `mcp` SDK 1.x
  (`FastMCP.run(transport="stdio")`)
- Server exposes ~86 tools under a single `plugin:<name>:cli` server
- Sessions run unattended for 8–18 hours

## Presentation 1 — deferred tools vanish after 60–90 minutes

Three independent subagent sessions in one run lost access to tools
they had **already loaded and already successfully called**. Calls that
had worked minutes earlier began failing as tool-not-found.

Recovery that works: re-issuing the original `ToolSearch` select-query
once re-resolves the deferred tools. So the server process is alive and
reachable — only the client's resolved tool state was lost.

Timing: 60–90+ minutes into each session. Independent sessions, same
window.

## Presentation 2 — entire server surface lost, unrecoverable in-session

~18 hours into a run, a top-level session lost **all 86 tools** at
once. The server appeared in the failed-to-connect list.

Critically, the Presentation 1 recovery does not apply: these tools
were pre-loaded at session start, never deferred, so a
`ToolSearch` select-query returns "No matching deferred tools found" —
there is no deferred entry to re-resolve. There is no in-session path
back. Recovery required a human running `/mcp` interactively.

Preceding conditions: two 5-hour platform quota pauses and long idle
stretches. Consistent with an idle timeout on a connection held across
session pauses, though we cannot confirm the mechanism from outside.

## Presentation 3 — a state-changing call is silently lost

The most damaging of the three, and the reason this is a correctness
issue rather than only an availability one.

After a connection drop and a successful tool re-resolution, a
subsequent write call (updating a pull request body) **never took
effect and returned no error**. The agent believed the write had
landed. It was caught only by re-reading the object afterwards.

This appears undetectable from either end by construction: if the
transport drops mid-call, the server's response is never delivered, so
no error can be produced server-side, and the client cannot distinguish
"never arrived" from "arrived and returned nothing".

## What we ruled out on our side

- No timeout, keepalive, or ping is implemented in our server. The two
  things that resemble it are unrelated: a session-*storage* TTL, and a
  UNIX-socket `PING`/`PONG` probe for whether a helper daemon process
  is up. Neither touches the client↔server hop.
- The server process itself stays alive — proven by Presentation 1,
  where re-resolution succeeds without restarting anything.

## What would help most

1. **Surface the disconnect to the agent as an error.** Today it
   presents as tools quietly missing, or as a write that silently does
   nothing. Either is far harder to handle than an explicit
   "connection lost" the agent can branch on.
2. **A client-side reconnect, or a documented way to trigger one from
   inside a session.** `/mcp` works but requires a human, which defeats
   unattended operation.
3. **If there is an idle timeout, document its duration** and whether
   traffic resets it — including whether a server-initiated
   `ping` (`ServerSession.send_ping` in the Python SDK) counts. We are
   willing to emit keepalive traffic from our side, but cannot tell
   whether it would have any effect.
4. **At-most-once or acknowledged delivery for state-changing calls**,
   or any signal distinguishing "not delivered" from "delivered, empty
   response". Presentation 3 is silent data loss without it.

## Impact

Unattended overnight runs are the primary casualty. The role that lost
its surface in Presentation 2 was the only one permitted to run merge
gates, so verified, ready-to-merge work queued until a human returned
the next morning. Presentation 3 is worse in kind: it produces state
that differs from what the agent recorded, with nothing anywhere
indicating a failure.
