# Fanout JSONL Pub/Sub Bus (v1)

Sibling-to-sibling coordination protocol for `Dev10x:fanout`
swarm children. Lets concurrently-running agents publish and
consume file-lock requests, conflict signals, progress
heartbeats, and bailout notices without serialising the wave
at the first sign of drift.

**Status:** v1 — append-only JSONL file per wave. No MCP server,
no daemon. If field experience shows tail-based polling is
insufficient, promote to `mcp__plugin_Dev10x_fanout_bus__*`
(see § Future Work).

**Scope:** This document is referenced by the
`Dev10x:fanout` Phase 3 dispatch prompt and consumed directly
by swarm-child agents. ADR 0004 leaves real-time coordination
out of the native-Agent swarm baseline and points at this
follow-up.

## Why file-based, not MCP

ADR 0004 ships native-Agent swarm dispatch with no
sibling-to-sibling channel: drift is reported through the
agent's result message and the orchestrator resolves between
waves. That's adequate when conflicts are rare but loses
parallelism whenever conflicts actually occur. The four
mechanisms compared in GH-133's issue body:

| Mechanism | Pros | Cons |
|---|---|---|
| Append-only JSONL bus per wave (this doc) | Zero new infra; deterministic; inspectable | Tail-based polling |
| MCP server `fanout_bus` with topics + subscriptions | Cleanest API; persist + filter | Requires building the server |
| `SendMessage` between named agents | Already exists | Peer-to-peer rather than pub/sub; orchestrator loses visibility |
| Orchestrator as broker | Centralised; parent stays in the loop | Adds latency; parent context fills up |

JSONL wins for v1 because every Dev10x swarm child already has
Bash + Read + Write + `mcp__plugin_Dev10x_cli__mktmp` in scope.
No new tool, no server lifecycle, no protocol versioning past
the event schema below. The file itself is the audit trail.

## File layout

The orchestrator creates a per-wave directory **before**
dispatching any Agent calls in that wave:

```
/tmp/Dev10x/fanout/<wave_id>/
    bus.jsonl       — append-only event stream
```

Creation goes through `mcp__plugin_Dev10x_cli__mktmp` in two
steps (GH-385 F3). A single `mktmp` call with a slash in the
prefix fails when the parent directory does not yet exist:

```
# Step 1 — create the wave directory (always created)
wave_dir = mcp__plugin_Dev10x_cli__mktmp(
    namespace="fanout",
    prefix="<wave_id>",
    directory=True,
)
# wave_dir["path"] → /tmp/Dev10x/fanout/<wave_id>.XXXX/

# Step 2 — create the bus file inside the wave directory
Write(file_path=wave_dir["path"] + "/bus.jsonl", content="")
bus_path = wave_dir["path"] + "/bus.jsonl"
```

Children that receive `bus_path` MUST NOT assume it needs
creating — it already exists. Children that encounter a write
error on `bus_path` MUST log it in their result but MUST NOT
abort: bus coordination is best-effort.

The returned `path` is inlined into every sibling's swarm
context prompt as `bus_path`. The wave_id is the same UUID the
swarm context already carries — the bus path is just a
deterministic suffix.

`<wave_id>` is the only path-variable component. Children MUST
NOT create new files under this directory; they only append to
`bus.jsonl`.

## Event schema

Every event is a single JSON object on one line, newline-terminated.
No multi-line JSON, no comments. Append-only — never rewrite
prior events.

Common envelope on every event:

| Field | Type | Description |
|---|---|---|
| `ts` | string | RFC 3339 UTC timestamp |
| `from` | string | Publisher's `item_id` (matches swarm context) |
| `event` | string | One of the event types below |
| `seq` | integer | Monotonic per-publisher counter starting at 1 |

The `seq` field lets consumers detect dropped events when
tailing the file. Implementations MAY skip enforcement in v1.

### `file_lock_request`

A child intends to write to one or more paths and asks
siblings to defer touching them.

| Field | Type | Description |
|---|---|---|
| `paths` | array of strings | Repo-relative paths the publisher claims |
| `intent` | string | Short human label, e.g. `"refactor"`, `"fix-test"` |
| `expires_at` | string | RFC 3339; advisory expiry. Consumers may ignore stale locks. |

### `file_lock_grant`

A sibling acknowledges another sibling's `file_lock_request`
and confirms it will NOT touch the listed paths. Optional —
absence of a grant within `lock_wait_timeout` (default 30s)
is treated as implicit non-conflict.

| Field | Type | Description |
|---|---|---|
| `request_ts` | string | The `ts` of the `file_lock_request` being granted |
| `granted_to` | string | The requester's `item_id` |

### `conflict_signal`

A child has discovered a file-scope drift it cannot resolve
locally. Sent before the child decides whether to wait or
bail out.

| Field | Type | Description |
|---|---|---|
| `path` | string | Repo-relative path in conflict |
| `with_item` | string | Sibling `item_id` that owns the path per Phase 2 conflict graph (may be `"unknown"`) |
| `severity` | string | `"hard"` (cannot proceed) or `"soft"` (could proceed with risk) |

### `progress`

Optional heartbeat. Lets the orchestrator and siblings see
that a child is still alive between commits.

| Field | Type | Description |
|---|---|---|
| `stage` | string | Free-form short label, e.g. `"design"`, `"implementing"`, `"reviewing"` |
| `note` | string | Optional one-line context (≤80 chars) |

### `bailout`

Final event published when a child decides to abort its work
rather than wait. The orchestrator reads this on wave-drain
to decide whether to re-dispatch in a follow-up wave.

| Field | Type | Description |
|---|---|---|
| `reason` | string | `"conflict"`, `"timeout"`, `"permission"`, or free-form |
| `recoverable` | boolean | `true` if a re-dispatch with adjusted ownership could succeed |

## Decision gate: wait vs bail

When a swarm child publishes a `conflict_signal`, it MUST
choose one of two responses — never busy-loop:

| Response | When | How |
|---|---|---|
| **Wait** | Sibling reachable; `severity: "soft"`; the sibling can plausibly finish first | Poll `bus.jsonl` for a matching `file_lock_grant` or for the sibling's terminal event (`bailout` or its result return). Cap the wait at `lock_wait_timeout` (default 30s). On timeout, transition to **bail**. |
| **Bail** | `severity: "hard"`, sibling unreachable, or wait timed out | Publish `bailout` with `recoverable: true|false`, return `BLOCKED: file-scope drift on <path> (sibling=<id>)` from the Agent result. Do NOT push a partial branch. |

The orchestrator MUST treat any `bailout` published in a wave
as a signal to consider rebasing successors and re-dispatching
the bailed item in a follow-up wave.

## Producer rules (swarm child)

1. Open the bus path read-only first to load prior events from
   the same wave (Phase 2 conflict-graph guidance may already
   have been emitted by the orchestrator). Use `Read` or
   `Bash(tail -F)` for live consumption.
2. Before writing to a path that overlaps with
   `shared_files_with_siblings`, publish a
   `file_lock_request`. Wait up to `lock_wait_timeout` for a
   `file_lock_grant` from each implicated sibling.
3. On detected drift, publish `conflict_signal` and follow the
   decision gate above.
4. Publish `progress` at most once per minute. The bus is not
   a debug log.
5. Never delete or truncate `bus.jsonl`. Append only.

## Consumer rules (swarm child)

1. Tail `bus.jsonl` periodically; ignore events whose `from`
   field is your own `item_id`.
2. Respond to `file_lock_request` with a `file_lock_grant`
   when you are confident you will not touch the listed paths
   within the current wave. Silence is acceptable; explicit
   denial is published as `conflict_signal` with
   `with_item: <requester>`.
3. Treat `bailout` from a sibling as a hint that any paths
   that sibling claimed are now available — but do not assume
   the sibling reverted partial changes. Inspect the worktree.

## Orchestrator rules

The orchestrator (the main `Dev10x:fanout` session) is a
passive consumer in v1:

1. Create the bus directory and file before each wave
   dispatch.
2. Inline `bus_path` into every child's swarm-context prompt.
3. On wave drain, read `bus.jsonl` once to harvest
   `bailout`/`conflict_signal` events and feed them into the
   Phase 4 re-dispatch decision.
4. Do NOT publish into the bus. The bus is a sibling-to-sibling
   channel; orchestrator coordination stays in agent result
   messages.
5. Keep the bus file after the wave completes — it doubles as
   an audit trail. The `/tmp/Dev10x/fanout/<wave_id>/`
   directory is cleaned up by normal `/tmp` rotation.

## Defaults

| Parameter | Default | Override |
|---|---|---|
| `lock_wait_timeout` | 30s | Per-child via swarm-context payload |
| `progress_interval` | 60s | Same |
| `max_events_per_wave` | 500 | Soft cap — log a warning on the bus and continue |

## Future work

Promote to `mcp__plugin_Dev10x_fanout_bus__*` when ANY hold:

- File-tailing latency causes measurable wasted parallelism
  in a real swarm run (not a synthetic benchmark)
- Cross-wave coordination is required (e.g., long-lived
  cross-pipeline lockfiles)
- Schema needs publish-side validation that the current
  free-form JSONL cannot enforce

Until then, the bus is plain JSONL. The simplicity is the
feature.
