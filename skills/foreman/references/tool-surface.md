# Tool surface and the lifecycle split (GH-922)

Who can call what, and why the delivery lifecycle is cut at that
boundary rather than at a convenient point in the workflow.

## The surface, per role

| Role | Spawned as | `Skill(...)` | `mcp__plugin_Dev10x_cli__*` |
|---|---|---|---|
| watchdog / orchestrator | top-level session | yes | yes (pre-loaded) |
| foreman overseer | `Agent` subagent | **no** | only via `ToolSearch` select-query |
| crew worker | `Agent` subagent | **no** | only via `ToolSearch` select-query |

Two distinct facts, often conflated:

1. **`Skill(...)` is unreachable from an `Agent`-spawned subagent.**
   Observed 2026-07-30 (plugin 0.91.0): `Skill(Dev10x:gh-pr-merge)`
   inside a worker returned "Unknown skill". Naming a skill in a
   worker prompt does not make its discipline run.
2. **MCP wrappers ARE reachable — but they are deferred tools.**
   They resolve only after an explicit
   `ToolSearch(query="select:<name>,<name>,…")`. A keyword search, or
   a call issued before that load, returns "No matching deferred
   tools found" — the symptom originally read as "subagents have no
   MCP at all".

So a worker prompt must (a) never name a `Skill(...)` call, and
(b) open with the select-query bootstrap in
`crew-prompt-template.md` § 2.

## Subagent Bash CWD is per-call (GH-1028)

A third fact, and the one that costs the most when it is wrong:
**in an `Agent`-spawned subagent, Bash CWD resets on every call.**
A `cd` in one call does not carry to the next. Worktree pinning is
therefore **argument-based, not state-based** — `git -C <worktree>
<verb>`, `uv run --directory <worktree>`, absolute paths for every
file tool.

The failure mode is worse than a wrong directory. A worker that
believes `cd` persisted, finds git operating on the dispatcher's tree,
and reaches for `git --git-dir=<repo>/.git/worktrees/<wt>
--work-tree=<wt> …` produces a shape that matches no allow rule. The
resulting permission prompt is unanswerable overnight AND records
nothing in the hook logs — a pending prompt is neither a block nor a
denial — so the worker wedges with no diagnostic trace. Two opus
workers hit this independently in the 2026-08-04/05 run; detection
took heartbeat-stall plus file-mtime forensics, ~2h, and two
stand-down takeovers. Both replacements succeeded on `git -C`.

Prove the shape before the night rather than assuming it:
`preflight-checklist.md` item 3 runs one representative `git -C
<worktree>` command inside the probe subagent, while the supervisor
is still present to answer a prompt (GH-1030).

## Why the lifecycle is cut at PR-open

The `merge` gate can legitimately be pinned to `auto-advance` (a
solo-maintainer posture). That autonomy is only safe because
`Dev10x:gh-pr-merge` enforces its checks — CI verdict, top-level
findings, unresolved inline threads, `Fixes:`-scope delivery, fixup
detection, ancestry freshness.

A worker that cannot reach that skill and merges anyway has the full
autonomy and none of the guardrails: the policy says "full auto merge
on CI green"; what executes is "merge, having checked nothing". The
gate is imaginary at exactly the moment it matters most — unattended,
overnight, no human to catch it.

Field case (GH-922): worker C0 was told to merge PR #901 via
`Skill(Dev10x:gh-pr-merge)`, could not reach it, fell back to a raw
rebase merge that the platform rejected, then to a squash merge. The
PR landed squashed — the documented rebase-merge discipline silently
violated, verifiable in the history as a single commit (`70f322fc`).

The split therefore runs along the surface boundary:

```
crew worker (subagent)          orchestrator (top-level session)
────────────────────────        ────────────────────────────────
implement                       merge gate:
test / lint                       CI verdict green
commit                            unresolved_threads == 0
push_safe                         top-level comments clean
create_pr(draft=false)            isDraft == false
verify isDraft == false           MERGEABLE
ci_check_status(wait=true)        zero fixup! commits
address review                  merge_pr (rebase)
STOP ─────────────────────►     issue_close / milestone_close
```

Workers never merge and never close issues. The orchestrator never
writes code.

## The foreman overseer is also a subagent

`architecture.md` places the foreman one tier below the watchdog, as
an `Agent`-spawned overseer. It therefore has the same constrained
surface as the crew: it can load MCP wrappers via `ToolSearch`, and
it cannot call `Skill(Dev10x:gh-pr-merge)` at all.

Consequences the instructions must honor:

- **Closure verification** (`issue_get` / `pr_get`) is available to
  the foreman only after the `ToolSearch` bootstrap. Until it loads
  those tools, any "verified closed" claim it relays is a
  transcription of a worker's unverified assertion, not an
  observation. In this run's field case the foreman's verification
  log was exactly that — a verification step that had silently
  degraded into repetition.
- **The merge gate belongs to the watchdog**, the only role that can
  invoke `Dev10x:gh-pr-merge`. The foreman prepares the request (PR
  number, chunk, delivered/cut table) and relays it; the watchdog
  runs the skill. This is the same dumb-relay shape as the
  spawn-by-request fallback in `architecture.md`.

## Post-condition re-verification

State-changing calls do not stay true. Re-read the state you depend
on immediately before you depend on it.

Field case (GH-922, this run): PR #926 was created, marked ready via
`pr_ready`, then force-pushed after a rebase — and silently reverted
to DRAFT. Bots skip drafts, so CI and review both went quiet on a PR
everyone believed was open for business.

Rules:

- After ANY force-push (`--force-with-lease` included), re-check
  `isDraft` via `pr_get` and re-run `pr_ready` if needed.
- After `create_pr(draft=false)`, verify `isDraft` is false — the
  flag is a request, not a guarantee.
- Before the merge gate, re-read CI verdict, mergeability, and
  ancestry freshness. A verdict from ten minutes ago is a memory,
  not a fact.

## Pre-flight obligation (Phase 0.4)

Add to the permission pre-flight, while the supervisor is present:

1. Spawn a throwaway probe subagent and have it run the exact
   `ToolSearch` select-query from the crew template, then make one
   read-only MCP call (e.g. `issue_get`). This proves the worker
   surface for tonight rather than assuming it.
2. If the probe comes back empty, the night runs with a narrower
   worker contract — workers implement and commit, the orchestrator
   pushes and opens PRs — and that reduction goes in the manifest.
   Do not silently substitute raw CLI for a gated operation.
3. **Enumerate the watchdog's own shapes as well** (GH-1058). The
   table above cuts the surface by role in both directions: a probe
   subagent proves the crew's surface and says nothing about the
   top-level session's. The merge gate's CI and draft reads and the
   stall-triage forensics are watchdog commands, and they prompted
   mid-night in the 2026-08-21/22 run while their MCP replacements sat
   loaded and unused. Prefer `ci_check_status(wait=false)` for the CI
   verdict, `pr_get` for draft/mergeability, and `dev10x foreman probe`
   for run-dir state, over `gh pr checks` / `gh pr view --json` /
   `ls -lt` + `stat`.
