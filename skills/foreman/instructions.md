# Dev10x:foreman — Full Workflow

The cast: **supervisor** (the human, leaving), **watchdog** (the main
session — you), **foreman** (a cheap overseer subagent managing the
crew), **crew** (delivery workers running the Dev10x:work-on bundle
lifecycle). The supervisor reads the shift log in the morning.

**The cast is split by tool surface, not just by job.** Only the
watchdog is a top-level session, so only the watchdog can call
`Skill(...)`. The foreman and the crew are `Agent`-spawned subagents:
they reach MCP wrappers only after an explicit `ToolSearch`
select-query, and they cannot call skills at all. Delivery therefore
stops at PR-open and the merge gate runs in the watchdog — see
[`references/tool-surface.md`](references/tool-surface.md) (GH-922).

**Founding principle — the pre-approval window is a one-time
resource.** Every loop, watcher, long-running command, and per-domain
tool the night will need must be enumerated and approved in Phase 0,
while the supervisor is still present. A permission prompt at 02:00
freezes a turn until morning; this skill exists so that never happens.

## Orchestration

**REQUIRED: Create a task at invocation.** Execute at startup:

1. `TaskCreate(subject="Run foreman night shift", activeForm="Running night shift")`

Mark completed at Phase 3 wrap-up: `TaskUpdate(taskId, status="completed")`.

## Phase 0 — Intake & Pre-flight (supervisor present; REQUIRED gates)

### 0.1 Build the queue

- Resolve the input (milestone URLs/numbers, issue lists, bundles)
  via `issue_list` / `issue_get`. Read milestone descriptions for
  declared dependencies ("Blocked by …").
- Chunk the work: one milestone or coherent bundle per chunk.
  **Sequential chunks by default** — parallel fanout across chunks
  invites cross-chunk conflicts (shared token files, lockfiles).
  Reach for `Dev10x:fanout` only for chunks with provably disjoint
  file sets, and never two open PRs from overlapping areas.
- Order by dependency; push known-risky or decision-hungry chunks to
  the queue END so the deliverable chunks are banked first.
- Classify each chunk: `mechanical` (pattern application, adoption
  sweeps, doc moves) / `standard` (scoped features/fixes) /
  `domain-heavy` (invariants, migrations, cross-BC event flows).

### 0.2 Queue & model gate (REQUIRED AskUserQuestion)

Present the chunk plan with a per-chunk model recommendation derived
from the classification — the supervisor confirms or overrides:

- `domain-heavy` → strongest available worker model (e.g. opus)
- `standard` → strong worker model (opus when budget allows, else sonnet)
- `mechanical` → mid-tier (sonnet)
- foreman overseer → cheap tier (haiku/sonnet) — it only relays,
  monitors, and spawns; it never writes code
- Never map the cheapest tier to delivery work.

Also ask which chunks (if any) the supervisor wants explicitly
deferred or excluded tonight.

### 0.3 Friction level gate (REQUIRED AskUserQuestion)

Offer `guided` or `strict` (see `../../references/friction-levels.md`).
This harness is **never YOLO**: do not offer, suggest, or accept
`bypassPermissions` / auto-mode as the answer to prompt risk — the
whole design assumes the permission model stays authoritative. Then
invoke `Skill(Dev10x:afk)` to compose the walk-away gate policy for
the session (adaptive preset + afk overlay).

### 0.4 Permission pre-flight (the one-time window)

Enumerate and dry-run EVERY command shape the night will use — now,
while a prompt costs seconds instead of hours:

1. `dev10x foreman probe --scratchpad <run-dir>` — proves the watcher
   CLI runs unprompted and the quota/base/heartbeat reads work.
2. One representative call per MCP wrapper the crew will need
   (`ci_check_status`, `issue_get`, `pr_get`, …) — proves the MCP
   server is up and the tools resolve.
3. **The subagent tool surface** — spawn a throwaway probe subagent
   that runs the crew template's `ToolSearch` select-query and then
   one read-only MCP call. The watchdog's own surface proves nothing
   about a worker's: subagents get MCP wrappers only as deferred
   tools and get no `Skill(...)` at all. If the probe comes back
   empty, narrow the worker contract in the manifest rather than
   letting workers improvise raw CLI (`references/tool-surface.md`).
4. The per-domain test tools for THIS repo (e.g. `run_node_tests`,
   `uv run --directory <api> pytest`) — proves the exact invocation
   shape and records it for the crew prompt (§ crew template).
5. Write access to the run directory and the repo tree.

Any prompt fired during pre-flight = fix it NOW: prefer switching to
a wrapper/skill; propose a narrow allow rule only when no wrapper
exists. If neither fits, that command shape is BANNED for the night
and the plan must route around it.

### 0.5 Write the run manifest

Create the run directory (via `mcp__plugin_Dev10x_cli__mktmp`,
namespace `foreman`) and write `manifest.md`: queue order, per-chunk
model + scope notes, friction level, base branch, verified command
shapes, deferred chunks. Workers and the foreman heartbeat into this
directory — one `status-<chunk>.md` each.

## Phase 1 — Arm the harness

1. Start the single watcher (one Monitor call, script-only — NEVER an
   inline loop/pipeline):

   `dev10x foreman watch --scratchpad <run-dir> --base-branch <base>`

   It emits: `STALL:` (heartbeat silence ≥ 25 min), `BASE MOVED:`,
   `QUOTA MILESTONE:`, `QUOTA RESET:` (5h block rollover — resume
   interrupted crew).
2. Spawn the **foreman** overseer (cheap model, named agent). Its
   brief: manage the queue per the manifest — spawn one crew worker
   per chunk (prompt built from
   `references/crew-prompt-template.md`), relay `BASE MOVED` rebase
   instructions, relay each finished chunk's PR to the watchdog for
   the merge gate, verify per-chunk closure, advance the queue, defer
   cut scope to the queue end, heartbeat to `status-foreman.md` every
   ~10 min. Its prompt opens with the same `ToolSearch` select-query
   bootstrap as a crew prompt — without it the foreman cannot call
   `issue_get`/`pr_get`, and any closure it reports is a
   transcription of a worker's claim rather than an observation
   (GH-922). It can never call `Skill(Dev10x:gh-pr-merge)`. If the
   platform denies the foreman the Agent tool, it falls back to
   **spawn-by-request**: it sends the watchdog a ready-to-execute
   worker spec via SendMessage, and the watchdog's only job is to run
   that one Agent call verbatim (see `references/architecture.md`).

## Phase 2 — The night loop (watchdog discipline)

The watchdog (main session) does the MINIMUM — its context and its
turn are the most precious resources on site:

- React ONLY to watcher events and foreman messages. No
  implementation work, no exploratory reads, no polling loops.
- `STALL` → run the **stand-down handshake** BEFORE any takeover,
  respawn, or `TaskStop`. Heartbeat silence proves the worker is not
  progressing; it does NOT prove the process is gone, and a revived
  worker is a live conflict risk a dead one is not. In order:
  1. Send the stalled agent a direct message naming every action
     already completed on its chunk (branch, commits, PR, merges,
     comments posted) and instructing it to **reply `STOP-ACK` and
     cease all writes** — report state, do not re-execute anything.
  2. Wait one more heartbeat interval (~15 min / the next watcher
     tick). A reply — `STOP-ACK`, a status report, any message at
     all — is strong evidence of liveness: it is alive, so resume it
     with a corrective brief instead of replacing it.
  3. Only if it stays silent through that SECOND window does takeover
     proceed — `TaskStop` + respawn from `manifest.md` and the newest
     heartbeats (all state is on disk, not in its head): the foreman
     does this for a crew worker, the watchdog for a silent foreman.

  Never skip step 1 because spend went flat: a cheap idle agent and a
  dead agent look identical on a spend graph. Full evidence and the
  idle-notification asymmetry: `references/stall-protocol.md`.
- `BASE MOVED` → relay to the foreman (it instructs the active worker
  to rebase, re-verify, and never merge on stale ancestry).
- **`MERGE REQUEST <chunk>` from the foreman → run the merge gate.**
  This is the one piece of real work the watchdog owns, because it is
  the one piece nobody below it can do: `Skill(Dev10x:gh-pr-merge)`
  is unreachable from a subagent. Re-read live state first (CI
  verdict, `isDraft`, mergeability, ancestry) — a worker's report is
  a memory, not a fact — then merge and close the chunk's issues via
  `issue_close` / `milestone_close`. Refuse the request if anything
  is pending, draft, conflicting, or carries `fixup!` commits, and
  send it back to the foreman with the failing check named.
- `QUOTA RESET` after a mid-block pause → tell the foreman to resume
  or respawn interrupted crew. An agent idle **by instruction** — a
  foreman holding for a relay like this one — has expected-stale
  heartbeats; a literal "silent foreman → `TaskStop`" reading would
  destroy a healthy overseer mid-wait. The handshake tells the cases
  apart.
- Never write into a crew worker's `status-<chunk>.md`: those files
  are worker-owned exclusively, and a `Write` from anyone else
  refreshes the mtime the stall detector reads as liveness.
- A decision only the supervisor can make (product call, invariant
  semantics, destructive migration) → do NOT guess and do NOT block
  the queue: have the scope cut per the crew contract — which ALWAYS
  leaves a tracker issue (the still-open original or a new split
  issue) as the permanent record — and the chunk (or its remainder)
  moved to the queue end by issue number. Log it in `DECISIONS.md`
  in the run directory for morning review.
- Every supervisor-grade decision the watchdog does make gets a
  numbered entry (D1, D2, …) in `DECISIONS.md` with rationale.

## Phase 3 — Morning wrap-up (REQUIRED, in order)

1. Verify: every queued chunk's issues closed or carrying a
   cut-rationale comment; milestones closed via `milestone_close`;
   no orphaned open PRs; stop the watcher and retire the foreman.
2. Consolidate `DECISIONS.md` + per-chunk decision files into the
   morning report (delivered/cut table per chunk, PRs + merge SHAs,
   open threads needing the supervisor).
3. **Self-audit (the skill improves itself):** collect every
   prompted, denied, or hook-blocked command from the night; run
   `Skill(Dev10x:diag-friction)` on each offender; file upstream
   issues proposing command-skill-map entries or hook guidance for
   the structural ones — **blocking with guidance beats being
   stopped mid-track**. Queue `Skill(Dev10x:skill-audit-queue)` for
   the session.
4. `Skill(Dev10x:session-wrap-up)` to route anything unfinished.

## Crew contract (what every worker prompt must contain)

Build each worker prompt from `references/crew-prompt-template.md`.
The non-negotiable elements, each of which exists because its absence
cost hours in the field (GH-890):

| Element | Why it is mandatory |
|---|---|
| `background_preamble` (fetch via MCP) prepended verbatim | Background agents never see the session friction briefing; without it they reinvent `cd &&`, pipes, heredocs |
| `ToolSearch` select-query bootstrap for every MCP wrapper the chunk needs, and ZERO `Skill(...)` calls anywhere in the prompt | Subagents get MCP wrappers only as deferred tools and get no skills at all. A prompt naming `Skill(Dev10x:gh-pr-merge)` does not make its 9 checks run — it makes the worker improvise (`references/tool-surface.md`) |
| Lifecycle split: implement → test → commit → push → PR open and verified not-draft → CI green → review addressed → **STOP**. Workers never merge, never close issues | The merge gate lives in a skill only the top-level watchdog can call. A worker merging without it has full autonomy and no guardrails — "auto-merge on CI green" executing as "merge, having checked nothing" (field case: PR #901 landed squashed against documented rebase discipline) |
| Post-condition re-verification: re-check `isDraft` via `pr_get` after `create_pr` AND after every force-push | A state-changing call's effect does not survive later git operations. Field case: PR #926 was `pr_ready`-ed, then silently reset to DRAFT by a force-with-lease push — bots skip drafts, so CI and review went quiet on a PR believed open |
| Anti-stall rule: no `sleep`/`--watch`/poll loops; CI via single-shot `ci_check_status` | A blocking wait dies on a permission wall and the worker hangs silently |
| Named per-domain test tools with exact invocation (from Phase 0.4) | Generic "run the tests" prose sends workers to `npm … \| tail` shapes that prompt |
| Heartbeat protocol: append one line to `status-<chunk>.md` via Write every ~15 min AND at phase transitions | File mtime is the stall detector's ground truth; self-reported timestamps lie, mtimes don't |
| Scope authority + cut protocol — every cut ends as a tracker issue: defer (original stays OPEN with a structured deferral comment, EXCLUDED from `Fixes:`, commit footer reworded, requeued by issue number) or split (partial PR closes the original; remainder becomes a NEW scoped issue, `Refs:`-linked) | The queue and manifest live in a temp dir — after a catastrophic harness failure, open tracker issues are the ONLY surviving record of cut scope; a cut issue that still auto-closes on merge is a silent lie to the tracker |
| Review discipline: address ALL top-level review comments (even INFO); auto-resolve addressed BOT threads only — never human threads; zero `fixup!` commits left at hand-off | These are the merge-gate conditions the watchdog will check; a worker that ignores them just hands back a PR the gate refuses |
| Decision log file per chunk | The supervisor audits choices in the morning, not at 03:00 |

## Merge guidance when no watcher is armed

Applies to whoever runs the merge gate — the watchdog in the full
harness, or you directly in the collapsed variant. It is never a
crew worker.

The merge discipline above assumes the full night-shift harness
(watcher relaying `BASE MOVED`). In the collapsed / in-session variant
— no `dev10x foreman watch` armed — a rebase→CI-pending→park cycle
re-triggers CI on every rebase and can ping-pong indefinitely. When
`pr_get` reports the PR green and `MERGEABLE`, and the diff cannot
conflict with what merged since (e.g. docs-only, disjoint files),
merge directly and let the rebase-merge strategy replay the commit.
Only fall back to a local rebase when `pr_get` reports `CONFLICTING`.

## Red flags — STOP, you are about to lose the night

- An inline `while`/`sleep`/pipeline in a Monitor or Bash call —
  "it passed before" is meaningless; shapes re-match per call. Use
  `dev10x foreman watch`.
- A worker prompt without the background preamble or named test tools.
- A worker prompt containing a `Skill(...)` call, or reaching for an
  MCP wrapper without the `ToolSearch` bootstrap first.
- A crew worker merging a PR or closing an issue — that is the
  watchdog's gate, and a worker doing it ran no checks at all.
- Trusting `isDraft`, CI verdict, or mergeability read before the
  last force-push. Re-read, then decide.
- "We'll add the allow rule when it prompts" — the supervisor is
  asleep; there is no *when*.
- Offering auto-mode / bypassPermissions to silence prompt risk.
- Merging on pending CI, stale ancestry, or with `fixup!` commits.
- The watchdog "quickly" doing implementation work in the main session.
- Two open PRs from overlapping file areas.
- Taking over a stalled chunk without the stand-down handshake, or
  citing flat spend as corroborating evidence that a worker is dead.
- `TaskStop`-ing a foreman whose heartbeat is stale because it is
  waiting on a relay you sent it.
- Anyone but the owning worker writing to `status-<chunk>.md`.
- Firing an `AskUserQuestion` the handoff already answered. Under afk
  this freezes the run until the supervisor returns. A mid-run
  clarifying question is NOT authorization to open a gate — answer
  inline and continue.

## Rationalization table

| Excuse | Reality |
|---|---|
| "This Monitor one-liner is simple, no script needed" | The 7-hour overnight freeze was exactly such a one-liner. Script or nothing. |
| "The worker knows the repo conventions" | It has a fresh system prompt. It knows nothing you didn't put in it. |
| "The prompt says `Skill(Dev10x:gh-pr-merge)`, so the 9 checks run" | The worker cannot call it. Naming a skill a subagent cannot reach buys the appearance of a gate and none of the gate. |
| "The worker reported the PR is ready and green — merge it" | That is a memory of a past state. Force-pushes re-draft PRs and bases move. Re-read `isDraft`, CI, and ancestry at the gate. |
| "The foreman relayed that the issues are closed" | Only if the foreman actually called `issue_get`. Without its ToolSearch bootstrap it is repeating the worker's claim, and verification has degraded into transcription. |
| "Pending CI, but everything else is green — merge" | Pending is not green. The field case: a check stuck `in_progress` with `conclusion=success` needed a job re-run, not a merge. |
| "The idle notification means the worker is stuck" | Idle pings fire between turns and arrive late/out of order — they prove neither liveness nor death. Heartbeat mtime, live PR/CI state, and a REPLY to a direct message are the evidence. |
| "Heartbeat is 28 min stale — it's dead, take the chunk over" | Silence means *not progressing*, not *dead*. Field case: a worker declared dead woke 22 min later, re-ran its whole mission, and posted duplicate rationale comments on the PR the takeover had already finished. Handshake first. |
| "Spend has been flat for 30 min, that corroborates it's dead" | A cheap idle agent and a dead agent are indistinguishable on a spend graph. Flat cost is not evidence of death — it is not evidence of anything. |
| "The foreman hasn't heartbeat since I sent the relay — respawn it" | It is idle by instruction, waiting on you. Killing it destroys a healthy overseer and resets the queue. Ask it to report first. |
| "Skip the pre-flight, the allowlist looked fine last week" | Allow rules are shape-sensitive and repos drift. Pre-flight is minutes; a missed shape is the night. |
| "Cheaper models everywhere will stretch the quota" | A failed chunk costs more than the model discount saves. Downgrade the overseer, never the crew. |
