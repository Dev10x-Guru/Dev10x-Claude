# Phase 0.4 — Permission pre-flight detail

The full command-shape enumeration behind Phase 0.4 of
`instructions.md`. Read this before running pre-flight on a new
night-shift; the numbered list in `instructions.md` names the six
checks, this file carries the exact invocations and field evidence.

## 1. Resolve the CLI shape once, and reuse it

`dev10x foreman probe --scratchpad <run-dir>` proves the watcher CLI
runs unprompted and the quota/base/heartbeat reads work. **Resolve the
CLI shape here and record it in the manifest** — the bare `dev10x`
entry point exists only when the CLI is installed as a uv tool. Probe
once with the bare shape; on a 127 exit fall back in this order, and
use whichever answers for `watch` in Phase 1 too:

| Install shape | Working invocation |
|---|---|
| `dev10x` installed as a uv tool | `dev10x foreman probe …` |
| CWD is a plugin-repo checkout | `uv run dev10x foreman probe …` (GH-947) |
| Normal plugin-cache install, CWD is the target repo | `uv run --project $CLAUDE_PLUGIN_ROOT dev10x foreman probe …` (GH-961) |

The third row is the common case for a night run: the plugin lives
under `~/.claude/plugins/cache/<owner>/<plugin>/<version>` while the
CWD is the repo being worked, so `uv run` alone resolves the wrong
project and the bare command exits 127. Two consecutive night runs
burned pre-flight window rediscovering this. Discovering it while
arming the watcher costs the night; discovering it now costs one
command.

## 2. One representative MCP call per wrapper

One call per MCP wrapper the crew will need (`ci_check_status`,
`issue_get`, `pr_get`, …) proves the MCP server is up and the tools
resolve before any worker depends on them.

**A green verdict is not a failure diagnosis (GH-1062).** Proving
`ci_check_status` proves only that a worker can learn a check *failed*
— not that it can read *why*. Prove the failing-log shape too, on any
recent red run in this repo:

```
gh run view <run-id> --log-failed
```

(or `gh api repos/<owner>/<repo>/actions/jobs/<job-id>/logs`). Record
whichever answers in the manifest and in the crew prompt's verified
tool shapes. In the 2026-08-23 run a check went red mid-night, the
corrective brief improvised this shape unproven, and the worker
silent-wedged on the resulting prompt for ~3h — found only by
heartbeat stall plus mtime forensics. The verdict tool was proven; the
follow-up was not, and the follow-up is what the night needed.

## 3. The subagent tool surface — and its git shapes

Spawn a throwaway probe subagent that runs the crew template's
`ToolSearch` select-query and then one read-only MCP call. The
watchdog's own surface proves nothing about a worker's: subagents get
MCP wrappers only as deferred tools and get no `Skill(...)` at all. If
the probe comes back empty, narrow the worker contract in the
manifest rather than letting workers improvise raw CLI
(`tool-surface.md`).

**In the same probe, run one representative git command in the exact
worktree-pinned shape the crew template mandates** (GH-1030):

```
git -C <one of tonight's worktree paths> status --short
```

MCP wrappers and test tools were already proven here; worker-side
*git* was not — and git is what workers run most. In the 2026-08-04/05
run the probe came back fully green and two workers still wedged
later, on `git --git-dir=…` permission prompts that were unanswerable
overnight, invisible in hook logs (a pending prompt records neither a
block nor a denial), and detectable only via heartbeat stall.

A prompt fired **here** surfaces while the supervisor is still present
— the entire point of the one-time window — and the remedy is a narrow
allow rule for the worktree root (e.g. `Bash(git -C <worktrees-root>/*)`)
rather than a night lost to forensics. Cost: one extra command in an
already-mandatory probe.

Probe the shape the crew prompt actually mandates, not a convenient
substitute: a bare `git status` proves nothing about `git -C`, because
the two match different allow rules. If tonight's chunks will also
fetch, rebase, or stash, the same reasoning extends to those verbs —
one read-only `git -C … status --short` is the floor, not the ceiling.

**Include the worktree-cleanup verbs (GH-1068 F2).** `git -C <wt>
restore` and `git -C <wt> clean` are not chunk work, so they are easy
to leave out of an enumeration built from the queue — and they are
exactly what the watchdog reaches for when it recovers a wedged or
dirty worktree at 03:00. A run froze 7.5 hours on that prompt. Any
verb the *recovery* paths need
([`worktree-recovery.md`](worktree-recovery.md),
[`corrupted-worktree-repair.md`](corrupted-worktree-repair.md)) belongs
in this probe alongside the verbs the chunks need.

## 4. Per-domain test tools — and the install that precedes them

The per-domain test tools for THIS repo (e.g. `run_node_tests`,
`uv run --directory <api> pytest`) — proves the exact invocation
shape and records it for the crew prompt (§ crew template).

**Prove the dependency-install shape for tonight's fresh worktrees
(GH-1062).** A fresh worktree has no `node_modules` / no synced venv,
so the first thing a worker runs is an install — and the install shape
is not the test shape. `pnpm --dir <dir> install` fails under corepack
when the project pins an older pnpm (`packageManager: pnpm@9.15.9`);
only the in-directory invocation self-switches to the pinned version.
Probe the exact form tonight's workers will use, and record the
watchdog pre-installing every worktree during Phase 0 as a sanctioned
fallback when no worker-side shape survives the probe.

## 5. Script deliverables, not just test runners (GH-961)

For every queued chunk whose *deliverable* includes an executable
artifact — a `bin/*.sh`, a generated compose file, a CLI entry point
— dry-run THAT artifact's own invocation shape, or add a narrow allow
rule for it, during this window. A worker that modifies a shell
script legitimately needs to execute it to verify the change, and a
manifest that bans "executing repo shell scripts" wholesale as
unproven leaves that worker with no sanctioned path.

Field case: a chunk whose deliverable was
`bin/render-worktree-config.sh` hit a permission prompt mid-night,
then hit a second one from the banned-shape workaround it improvised
(`ENV=x docker compose config 2>&1 | grep -A2 …` — env prefix plus
redirect plus pipe). Record each proven shape in the manifest so the
worker never has to improvise.

## 6. Write access

Write access to the run directory and the repo tree.

## 7. The watchdog's own gate and triage shapes (GH-1058)

Items 1–6 enumerate what the *crew* runs. The watchdog runs commands
too — the merge gate's CI and draft reads, and the stall-triage
forensics — and those were never on this list. In the 2026-08-21/22
run they raised permission prompts mid-night, invisible in the hook
logs for the usual reason (a pending prompt records neither a block nor
a denial), while MCP replacements were already loaded and unused.

Route them to wrappers rather than proving raw shapes, and record the
routing in the manifest:

| Watchdog need | Prefer | Instead of |
|---|---|---|
| CI verdict at the merge gate | `ci_check_status(wait=false)` | `gh pr checks` |
| draft / mergeability / ancestry | `pr_get` | `gh pr view --json …` |
| run-dir state during stall triage | `dev10x foreman probe` | `ls -lt`, `stat`, `git log` |

Where no wrapper exists, dry-run the raw shape here like any other.
The rule is the same one item 3 makes for workers — the watchdog's
surface proves nothing about the crew's, and the crew's proves nothing
about the watchdog's.

## 8. Dry-run the merge gate itself (GH-1051)

Prove the *policy*, not just the commands. Call:

```
resolve_gate(gate="merge", context={})
```

`effect: "auto-advance"` means merges land unattended tonight. Anything
else means the first `MERGE REQUEST` freezes the run on an
`AskUserQuestion` no one is awake to answer — and the `human_review`
floor produces exactly that on a repo whose policy reads
`adaptive + [solo-maintainer, afk]` but carries no explicit
`merge: auto-advance` override (GH-1056).

On a non-`auto-advance` effect, surface it in the Phase 0.3 gate while
the supervisor is still present, with three honest options:

- pin `merge: auto-advance` for this repo via `pin_gate_preset`
- take a one-night standing authorization for tonight's queue
- run `guided + afk` knowingly — merges hold until morning

Phase 0.3's "adaptive + afk — full walk-away, merges included" is a
promise about the *preset*; this check is what makes it a promise about
the *run*.

## Any prompt fired during pre-flight

Fix it NOW: prefer switching to a wrapper/skill; propose a narrow
allow rule only when no wrapper exists. If neither fits, that command
shape is BANNED for the night and the plan must route around it.
