# Tool surface and the lifecycle split (GH-922)

Who can call what, and why the delivery lifecycle is cut there.

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

So a worker prompt must never name a `Skill(...)` call, and must open
with the select-query bootstrap in `crew-prompt-template.md` § 2.

## MCP connectivity is not permanent (GH-1063)

A third fact, and the one that bites latest: **the bootstrap does not
hold for the worker's whole life.** Three independent crew workers in
the 2026-08-23 run lost their Dev10x MCP surface after 60–90+ minutes —
`create_pr` and `push_safe` became unreachable on tools they had
already loaded and already used. The suspected mechanism is an idle
timeout on a connection held across a long blocking call, which
`ci_check_status(wait=true)` produces by design. The cost lands at the
worst moment: two of the three had pushed and lost only the final
PR/verify step; the third wedged pre-PR with a branch on origin and no
PR, needing a fresh-spawn takeover to finish a chunk that was
substantively done.

Until the wrapper layer reconnects on demand, the mitigation is
worker-side and cheap: re-run the exact `ToolSearch` select-query once
when a previously-loaded tool reports unreachable, then report and stop
if it is still gone. A worker that reads "tool not found" as "this
operation is impossible" improvises raw CLI for a gated operation —
the failure the surface split exists to prevent.

## Subagent Bash CWD is per-call (GH-1028)

A fourth fact, and the one that costs the most when it is wrong:
**in an `Agent`-spawned subagent, Bash CWD resets on every call.**
A `cd` in one call does not carry to the next. Worktree pinning is
therefore **argument-based, not state-based** — `git -C <worktree>
<verb>`, `uv run --directory <worktree>`, absolute paths for every
file tool.

The failure mode is worse than a wrong directory. A worker that
believes `cd` persisted, finds git operating on the dispatcher's tree,
and reaches for `git --git-dir=<repo>/.git/worktrees/<wt>
--work-tree=<wt> …` produces a shape that matches no allow rule — and
the resulting prompt is unanswerable overnight AND records nothing in
the hook logs (a pending prompt is neither a block nor a denial), so
the worker wedges with no diagnostic trace. Two opus workers hit this
independently in the 2026-08-04/05 run; detection took ~2h of
heartbeat-stall plus file-mtime forensics and two stand-down
takeovers. Both replacements succeeded on `git -C`.

Prove the shape before the night: `preflight-checklist.md` item 3 runs
one representative `git -C <worktree>` command inside the probe
subagent, while the supervisor can still answer a prompt (GH-1030).

## Why the lifecycle is cut at PR-open

The `merge` gate can legitimately be pinned to `auto-advance` (a
solo-maintainer posture). That autonomy is only safe because
`Dev10x:gh-pr-merge` enforces its checks — CI verdict, top-level
findings, unresolved inline threads, `Fixes:`-scope delivery, fixup
detection, ancestry freshness. A worker that merges without them has
the full autonomy and none of the guardrails: policy says "full auto
merge on CI green", execution is "merge, having checked nothing" —
unattended, overnight, no human to catch it.

Field case (GH-922): worker C0, told to merge PR #901 via
`Skill(Dev10x:gh-pr-merge)`, could not reach it, fell back to a raw
rebase merge the platform rejected, then to a squash merge — the
documented rebase discipline violated, visible as one commit
(`70f322fc`).

### What actually holds the line (GH-1061)

Two things, and neither is a lock: the **prompt contract** ("THEN SET
DOWN YOUR PEN. Do not merge.", `crew-prompt-template.md` § 7), and the
**omission of `merge_pr` from the crew select-query** in § 2, so a
compliant worker never loads it.

`Skill(Dev10x:gh-pr-merge)` genuinely is unreachable from a subagent —
but `mcp__plugin_Dev10x_cli__merge_pr` is NOT. It is a deferred tool
like any other wrapper, and a subagent can load it with its own
`ToolSearch(query="select:merge_pr")`; in the audited run one did
exactly that and merged. Earlier revisions credited tool separation
for the enforcement, dressing a prompt-deep rule as a structural one.

**A worker that loads `merge_pr` anyway is unenforced** — nothing
denies the call, nothing records it as a violation. Known gap, not a
guarantee: closing it needs a permission-layer deny on `merge_pr` for
subagent callers, which does not exist today. Until then the two
mitigations above plus after-the-fact detection are all there is — a
chunk whose PR is already merged when its MERGE REQUEST arrives is
the signature.

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

Workers never merge and never close issues; the orchestrator never
writes code.

### The gate is the last catch for a stale `Fixes:` (GH-1061)

`Fixes:`-scope delivery is already one of the gate's checks — run it
as a diff comparison, not a formality: read every `Fixes:` line and
confirm the diff in front of you delivers that issue. A crew worker in
the audited run reverted an issue's implementation to get CI green and
left the trailer behind; the PR would have auto-closed an issue whose
work had just been removed — undelivered work marked done in the
tracker, overnight. The worker should have declared that revert a
scope cut (`crew-contract.md`, scope-authority row); when it does not,
the gate is the last place anyone sees it.

## The foreman overseer is also a subagent

`architecture.md` places the foreman one tier below the watchdog, as
an `Agent`-spawned overseer. It therefore has the same constrained
surface as the crew: it can load MCP wrappers via `ToolSearch`, and
it cannot call `Skill(Dev10x:gh-pr-merge)` at all. Two consequences
the instructions must honor:

- **Closure verification** (`issue_get` / `pr_get`) is available to
  the foreman only after the `ToolSearch` bootstrap. Until it loads
  those tools, any "verified closed" claim it relays is a
  transcription of a worker's unverified assertion — a verification
  step silently degraded into repetition, which is what one field
  run's verification log turned out to be. The general form of this
  rule is `overseer-discipline.md` § No claim without an artifact.
- **The merge gate belongs to the watchdog**, the only role that can
  invoke `Dev10x:gh-pr-merge`. The foreman prepares the request (PR
  number, chunk, delivered/cut table) and relays it; the watchdog runs
  the skill — the same dumb-relay shape as the spawn-by-request
  fallback in `architecture.md`.

## Post-condition re-verification

State-changing calls do not stay true. Re-read the state you depend
on immediately before you depend on it. Field case (GH-922): PR #926
was created, marked ready via `pr_ready`, then force-pushed after a
rebase — and silently reverted to DRAFT. Bots skip drafts, so CI and
review both went quiet on a PR everyone believed open for business.

- After ANY force-push (`--force-with-lease` included), re-check
  `isDraft` via `pr_get` and re-run `pr_ready` if needed.
- After `create_pr(draft=false)`, verify `isDraft` is false — the
  flag is a request, not a guarantee.
- Before the merge gate, re-read CI verdict, mergeability, and
  ancestry freshness. A verdict from ten minutes ago is a memory.

## Pre-flight obligation (Phase 0.4)

Add to the permission pre-flight, while the supervisor is present:

1. Spawn a throwaway probe subagent, have it run the exact
   `ToolSearch` select-query from the crew template, then make one
   read-only MCP call (e.g. `issue_get`) — proving the worker surface
   for tonight rather than assuming it.
2. If the probe comes back empty, the night runs with a narrower
   worker contract — workers implement and commit, the orchestrator
   pushes and opens PRs — and that reduction goes in the manifest.
   Do not silently substitute raw CLI for a gated operation.
3. **Enumerate the watchdog's own shapes as well** (GH-1058). A probe
   subagent proves the crew's surface and says nothing about the
   top-level session's. The merge gate's CI and draft reads and the
   stall-triage forensics are watchdog commands, and they prompted
   mid-night in the 2026-08-21/22 run while their MCP replacements sat
   unused. Prefer `ci_check_status(wait=false)` for the CI verdict,
   `pr_get` for draft/mergeability, and `dev10x foreman probe` for
   run-dir state, over `gh pr checks` / `gh pr view --json` /
   `ls -lt` + `stat`.
