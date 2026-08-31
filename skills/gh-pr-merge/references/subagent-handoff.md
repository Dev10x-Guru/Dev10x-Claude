# Subagent Handoff Re-Verify Contract (GH-1093)

Depth behind the § Subagent handoff exception section of
`instructions.md`. That section is the binding rule; this file
carries the report schema, the per-check reasoning, and the
evidence.

## What went wrong

In a `Dev10x:fanout` swarm (bl-zebra, 2026-08-29), three
worktree-isolated workers each ran the full 9-check gate, hit
Check 2's infrastructure override (review bots red on an
account quota cap), and correctly returned `NEEDS_CONTEXT` —
the override is `ALWAYS_ASK` and `AskUserQuestion` is not
exposed to background subagents.

The orchestrator, holding the supervisor's standing widget
authorization, then re-ran all 9 checks per the re-invocation
contract before calling `merge_pr` (PRs #2660, #2667, #2669,
#2670 in Brave-Labs/zebra). Every merge was validated twice —
`unresolved_threads`, `check_top_level_comments`, `pr_comments`,
`ci_check_status`, `pr_get`, `git status` and `git log` each ran
in both contexts, minutes apart, for roughly 3–4× duplicated
tool traffic per PR.

The re-invocation contract is right in general: state drifts,
and a sibling skill's context is not evidence. But the
subagent-handoff case is *structured* — the worker's report
carries the observed values, the timestamps, and the infra
evidence. The orchestrator's genuine exposure in the minutes
between handoff and merge is only the time-sensitive subset.

## Report schema

The worker's report is the whole basis of the exception, so a
report missing any field fails the exception and the
orchestrator re-runs everything. Required fields:

| Field | Meaning |
|-------|---------|
| `pr` | `owner/repo#N` |
| `head_sha` | Full SHA the nine checks were measured against |
| `measured_at` | ISO-8601 UTC timestamp of the check run |
| `checks` | One entry per check, each naming its **observed value** — `isDraft: false`, `mergeable: MERGEABLE`, `verdict: green`, `unresolved threads: 0`, … |
| `blocked_gate` | Which `ALWAYS_ASK` gate could not be fired |
| `blocked_evidence` | Why it fired — e.g. the failing check names and the infrastructure cause |

A bare "✓ passed" per check does not satisfy `checks`, for the
same reason it does not satisfy the Step 1 self-check: an
unverifiable tick is the shortcut GH-112 caught.

## Why each check falls where it does

**Re-run fresh, always:**

| Check | Why it cannot be inherited |
|-------|----------------------------|
| 1, 1b, 1c (threads, top-level, inline) | A reviewer or bot can post between handoff and merge — the documented late-comment race (GH-462 F3) |
| 2 (CI) | A pending leg can settle either way; a re-run can turn a green leg red |
| 2b, 3, 4, 7 (merged/auto-merge, draft, mergeable, approval) | Already a **single** `pr_get` call, which the orchestrator must make anyway to confirm state and HEAD — inheriting them would save nothing |

**Acceptable from the report, iff `head_sha` is unchanged:**

| Check | Why the SHA pins it |
|-------|---------------------|
| 1d (Fixes-linked scope delivered) | A function of the commit graph — the same commits deliver the same scope |
| 5 (working copy clean) | Worker-local state in the worker's own worktree; the orchestrator cannot observe it at all, so the report is the only evidence that exists |
| 6 (no fixup/squash commits) | A function of the commit graph |

The unchanged head SHA is what makes these three safe: all
three are properties of the commits, and new commits move the
SHA. Any mismatch means the graph changed and the exception
does not apply.

## Failure posture

Bias to the full re-run. Fall back to it on **any** of:

- `head_sha` differs from the fresh `pr_get` HEAD
- Any required report field absent or unparseable
- The report is older than 30 minutes
- The report came from anything other than a subagent this
  orchestrator dispatched in this session

The exception exists to remove duplicated traffic, never to
merge on a stale reading. Re-running costs a handful of API
calls; merging on stale state costs a bad merge.

## The cheaper alternative, and why it is not enough

`fanout`'s dispatch template could instead say: when a standing
supervisor authorization for an infra override exists, merges
are orchestrator-only — workers stop at "PR ready + report" and
never invoke `gh-pr-merge` at all, avoiding the first of the two
full runs.

That is strictly cheaper and worth doing, but it is not a
replacement. A worker cannot know in advance whether it will hit
an `ALWAYS_ASK` gate, and a worker that *can* merge should — the
handoff only happens on the gate it could not fire. The two
changes compose: the template avoids the duplicate run when the
outcome is predictable, and this contract bounds the cost when
it is not.
