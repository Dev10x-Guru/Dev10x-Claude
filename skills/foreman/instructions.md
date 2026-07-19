# Dev10x:foreman — Full Workflow

The cast: **supervisor** (the human, leaving), **watchdog** (the main
session — you), **foreman** (a cheap overseer subagent managing the
crew), **crew** (delivery workers running the Dev10x:work-on bundle
lifecycle). The supervisor reads the shift log in the morning.

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
3. The per-domain test tools for THIS repo (e.g. `run_node_tests`,
   `uv run --directory <api> pytest`) — proves the exact invocation
   shape and records it for the crew prompt (§ crew template).
4. Write access to the run directory and the repo tree.

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
   instructions, verify per-chunk closure (issues auto-closed,
   milestone closed), advance the queue, defer cut scope to the queue
   end, heartbeat to `status-foreman.md` every ~10 min. If the
   platform denies the foreman the Agent tool, it falls back to
   **spawn-by-request**: it sends the watchdog a ready-to-execute
   worker spec via SendMessage, and the watchdog's only job is to run
   that one Agent call verbatim (see `references/architecture.md`).

## Phase 2 — The night loop (watchdog discipline)

The watchdog (main session) does the MINIMUM — its context and its
turn are the most precious resources on site:

- React ONLY to watcher events and foreman messages. No
  implementation work, no exploratory reads, no polling loops.
- `STALL` for a crew worker → the foreman handles abort-respawn; a
  `STALL` while `status-foreman.md` itself is silent → TaskStop the
  foreman and respawn it from the manifest + newest heartbeats
  (its state is on disk, not in its head).
- `BASE MOVED` → relay to the foreman (it instructs the active worker
  to rebase, re-verify, and never merge on stale ancestry).
- `QUOTA RESET` after a mid-block pause → tell the foreman to resume
  or respawn interrupted crew.
- A decision only the supervisor can make (product call, invariant
  semantics, destructive migration) → do NOT guess and do NOT block
  the queue: have the scope cut per the crew contract, a follow-up
  issue filed, and the chunk (or its remainder) moved to the queue
  end. Log it in `DECISIONS.md` in the run directory for morning
  review.
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
| Anti-stall rule: no `sleep`/`--watch`/poll loops; CI via single-shot `ci_check_status` | A blocking wait dies on a permission wall and the worker hangs silently |
| Named per-domain test tools with exact invocation (from Phase 0.4) | Generic "run the tests" prose sends workers to `npm … \| tail` shapes that prompt |
| Heartbeat protocol: append one line to `status-<chunk>.md` via Write every ~15 min AND at phase transitions | File mtime is the stall detector's ground truth; self-reported timestamps lie, mtimes don't |
| Scope authority + cut protocol: `issue_comment` the remainder, leave open, EXCLUDE from `Fixes:` and reword the commit footer | A cut issue that still auto-closes on merge is a silent lie to the tracker |
| Merge discipline: rebase-merge on fresh ancestry only; pending CI is not green; zero `fixup!` at merge; address ALL top-level review comments (even INFO); auto-resolve addressed BOT threads only — never human threads | Every one of these is a merge-gate failure mode observed in the field |
| Decision log file per chunk | The supervisor audits choices in the morning, not at 03:00 |

## Red flags — STOP, you are about to lose the night

- An inline `while`/`sleep`/pipeline in a Monitor or Bash call —
  "it passed before" is meaningless; shapes re-match per call. Use
  `dev10x foreman watch`.
- A worker prompt without the background preamble or named test tools.
- "We'll add the allow rule when it prompts" — the supervisor is
  asleep; there is no *when*.
- Offering auto-mode / bypassPermissions to silence prompt risk.
- Merging on pending CI, stale ancestry, or with `fixup!` commits.
- The watchdog "quickly" doing implementation work in the main session.
- Two open PRs from overlapping file areas.

## Rationalization table

| Excuse | Reality |
|---|---|
| "This Monitor one-liner is simple, no script needed" | The 7-hour overnight freeze was exactly such a one-liner. Script or nothing. |
| "The worker knows the repo conventions" | It has a fresh system prompt. It knows nothing you didn't put in it. |
| "Pending CI, but everything else is green — merge" | Pending is not green. The field case: a check stuck `in_progress` with `conclusion=success` needed a job re-run, not a merge. |
| "The idle notification means the worker is stuck" | Idle pings fire between turns and arrive late/out of order. Only heartbeat-file mtime and live PR/CI state are evidence. |
| "Skip the pre-flight, the allowlist looked fine last week" | Allow rules are shape-sensitive and repos drift. Pre-flight is minutes; a missed shape is the night. |
| "Cheaper models everywhere will stretch the quota" | A failed chunk costs more than the model discount saves. Downgrade the overseer, never the crew. |
