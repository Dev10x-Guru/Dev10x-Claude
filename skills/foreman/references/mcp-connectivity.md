# MCP connectivity loss (GH-1063, GH-1072, GH-1099)

The MCP surface a role proved at start does not hold for that role's
whole life. This file is the single home for what dies, which role it
strands, and what containment is available — `tool-surface.md`
§ "MCP connectivity is not permanent" is the short pointer into it.

## The transport is not ours (GH-1072)

The call chain is:

```
agent → harness MCP client → our stdio server → dev10x wrapper → subprocess
```

What dies is the **first** hop, harness-client ↔ our-stdio-server. Our
"wrapper layer" sits behind that hop, wrapping subprocess calls.

Dev10x implements no timeout, keepalive, or ping on that connection —
`servers/cli_server.py` and `src/dev10x/mcp/` contain no transport
liveness handling at all. The two things that look like it are not:
`session_store.py`'s TTL is session-*storage* expiry, and
`daemon.py`'s `PING`/`PONG` is a UNIX-socket probe for whether the
daemon **process** is up. The ~1800s ceiling quoted throughout these
docs is a number we *stay under*, never one we enforce.

**Therefore "reconnect-on-demand in the wrapper layer" — the fix as
originally specified in GH-1072 and GH-1099 ask 1 — is not
implementable in this repo.** A layer cannot reconnect a transport it
does not own. Both issues hedge toward exactly this branch; the code
puts us on it. What remains in-repo is (a) shrinking the exposure
window, (b) the containment below, and (c) an upstream report against
the harness client with the 60–90min reproduction.

Shrinking the window is real work, not a consolation: the suspected
mechanism is an idle timeout on a connection held across a long
blocking call, and `ci_check_status(wait=true)` is the longest such
call we make. GH-1088 removed an unconditional 60s `initial_wait` paid
even when CI had already finished. That narrows the window; it does
not close it.

## Three failure surfaces, not one

| Surface | Who is stranded | Documented containment |
|---|---|---|
| Worker loses loaded tools after ~60–90min | crew worker | re-run the exact `ToolSearch` select-query ONCE, then report-and-stop |
| Top-level session loses the whole surface | watchdog / foreman | **no self-recovery path** — see below |
| A write drops mid-call and reports nothing | any role | assume it did not land; re-read before depending on it |

### Worker surface loss (GH-1063)

Three independent crew workers in the 2026-08-23 run lost their Dev10x
surface after 60–90+ minutes — `create_pr` and `push_safe` became
unreachable on tools they had already loaded *and already used*. Two
had pushed and lost only the final PR/verify step; the third wedged
pre-PR with a branch on origin and no PR, needing a fresh-spawn
takeover to finish a chunk that was substantively done.

The mitigation is worker-side and cheap, and it works: re-run the
exact select-query once, then report and stop if the tool is still
gone. It is a mitigation, not a fix — it costs a round trip, depends
on the worker following it, and does nothing for a call that fails
mid-operation. It is baked into `crew-prompt-template.md` § 2.

A worker that instead reads "tool not found" as "this operation is
impossible" improvises raw CLI for a gated operation — the exact
failure the surface split exists to prevent.

### Watchdog surface loss — worse, and unrecoverable in-session (GH-1099)

~18h into the 2026-08-29/30 night run, the **top-level** session lost
all 86 `mcp__plugin_Dev10x_cli__*` tools — pre-loaded at session
start, not deferred — with `plugin:Dev10x:cli` listed among
failed-to-connect servers. The drop followed two 5h platform quota
pauses and long idle stretches, consistent with idle-timeout on a
connection held across session pauses.

**The worker-side mitigation does not transfer.** A `ToolSearch`
select-query returned "No matching deferred tools found": the
top-level session's tools were never deferred, so there is no deferred
entry to re-resolve. Recovery required the human running `/mcp`.

That is run-ending under `foreman`, because the watchdog is the only
role allowed to run the merge gate (`merge_pr`, `pr_get`,
`ci_check_status`) and the rule for MCP-unavailable is "STOP and ask
the user". Overnight that means every gate-passed PR queues until
morning — two gate-verified PRs sat blocked that night until the
supervisor happened to be present.

Containment, in the order it was actually used:

1. **Gate READS fall back to sanctioned `gh api`** — reads are
   idempotent and verifiable, so a raw read is a smaller risk than a
   stalled gate. Record the substitution in the manifest.
2. **Merges queue; they do not improvise.** `merge_pr` is a
   state-changing gated operation — never hand-roll `gh pr merge` to
   route around a dead surface.
3. **Ask the supervisor via `AskUserQuestion`** naming the PRs held
   and why, so a present human can run `/mcp` and unblock the queue.

Do not plan a night run on the assumption that the watchdog can
recover its own surface. It cannot.

### Dropped writes are not acknowledged (GH-1099 ask 2)

A worker's connection dropped mid-`push_safe`; the single permitted
`ToolSearch` retry restored the surface. But a **subsequent
`update_pr` call was silently lost** — no error payload, PR body never
updated. The worker caught it only by re-reading the PR afterwards.

This is a correctness bug, not an availability one: state you believe
you changed is unchanged, and nothing told you. It is also
**undetectable from either end by construction** — when the transport
drops mid-call our response is never delivered, so no error can be
produced server-side, and the client cannot distinguish "never
arrived" from "arrived and returned nothing".

So the contract is caller-side and unconditional:

> **A state-changing MCP call is a request, not a receipt. Assume a
> dropped write did NOT land until a read proves it did.**

Applies to every write wrapper — `update_pr`, `create_pr`,
`push_safe`, `pr_ready`, `pr_labels`, `issue_*`, `merge_pr`. Re-read
the field you set, not merely "the object exists":

- `update_pr(body=…)` → `pr_get` and check the body actually changed.
- `create_pr` / `pr_ready` → `pr_get` and check `isDraft`.
- `push_safe` → confirm the remote ref moved to the SHA you pushed.
- `issue_close` → re-read `state`.

This generalizes `tool-surface.md` § Post-condition re-verification,
which covers the same discipline for a narrower trigger (a force-push
silently re-drafting a PR). Same rule, one more reason for it.

## Status

- **In-repo and shipped:** worker `ToolSearch` retry
  (`crew-prompt-template.md` § 2); the GH-1088 fast path narrowing the
  longest blocking call; this file's containment for the watchdog case
  and for dropped writes.
- **Not implementable in-repo:** reconnect-on-demand
  (GH-1072 / GH-1099 ask 1) — the transport is harness-owned.
- **Open upstream work:** file the harness-client report with the
  60–90min reproduction, and decide whether a server-side keepalive is
  worth attempting from our end. Tracked in GH-1121 — split out of
  GH-1072/GH-1099 so those could close with the containment above
  without dropping this scope.
