# Dev10x:foreman — Full Workflow

The cast: **supervisor** (the human, leaving), **watchdog** (the main
session — you), **foreman** (a cheap overseer subagent managing the
crew), **crew** (delivery workers running the Dev10x:work-on bundle
lifecycle). The supervisor reads the shift log in the morning.

**The cast is split by tool surface, not just by job.** Only the
watchdog can call `Skill(...)`; the foreman and crew are
`Agent`-spawned subagents reaching MCP wrappers only after an explicit
`ToolSearch` select-query, and never skills. Delivery therefore stops
at PR-open and the merge gate runs in the watchdog:
[`references/tool-surface.md`](references/tool-surface.md) (GH-922).

**Founding principle — the pre-approval window is a one-time
resource.** Every loop, watcher, and per-domain tool the night will
need must be enumerated and approved in Phase 0, while the supervisor
is still present — a permission prompt at 02:00 freezes a turn until
morning.

## Orchestration

**REQUIRED: Create a task at invocation.**
`TaskCreate(subject="Run foreman night shift", activeForm="Running
night shift")`, marked completed at Phase 3 wrap-up.

## Phase 0 — Intake & Pre-flight (supervisor present; REQUIRED gates)

### 0.1 Build the queue

Resolve the input via `issue_list` / `issue_get`, reading milestone
descriptions for declared dependencies. Chunk the work — one milestone
or coherent bundle per chunk, **sequential by default** (reach for
`Dev10x:fanout` only for provably disjoint file sets). Order by
dependency, pushing risky/decision-hungry chunks to the queue END.
Classify each chunk: `mechanical` / `standard` / `domain-heavy`.

### 0.2 Queue & model gate (REQUIRED AskUserQuestion)

Present the chunk plan with a per-chunk model recommendation derived
from the classification — the supervisor confirms or overrides:
`domain-heavy` → strongest model; `standard` → strong model;
`mechanical` → mid-tier; foreman overseer → cheap tier (relays,
monitors, spawns — never writes code). Never map the cheapest tier to
delivery work. Also ask which chunks the supervisor wants deferred or
excluded tonight.

### 0.3 Gate policy — adaptive + afk by default (GH-944)

**Default composition: `gate_preset: adaptive` + `gate_overlays:
[afk]`** — auto-advancing walk-away; the supervisor opts *out*, not
in. If the durable policy source already covers this checkout
(`~/.config/Dev10x/friction.yaml`), honor it verbatim and **skip the
gate**. Otherwise, offer the override once — **REQUIRED: Call
`AskUserQuestion`** (do NOT use plain text):

- `adaptive + afk` **(Recommended)** — full walk-away, merges
  included; the default this harness assumes
- `guided + afk` — walk-away pipeline, but merge stays a human action
  (`merge: skip`); pick this on a shared/team repo
- `strict` — every gate fires; only sane if the supervisor is in fact
  staying

**No contrary answer means the default.** Invoke `Skill(Dev10x:afk)`
to compose it. Never offer `bypassPermissions` / auto-mode as an
answer to prompt risk — this harness is never YOLO. Full
durable-policy-check procedure and the GH-978 worktree caveat (a
fresh `isolation="worktree"` checkout can see a phantom merge-gate
`ask`):
[`references/gate-policy-detail.md`](references/gate-policy-detail.md).

### 0.4 Permission pre-flight (the one-time window)

Enumerate and dry-run EVERY command shape the night will use: the
`dev10x foreman probe` CLI shape, one call per MCP wrapper, the
subagent `ToolSearch` bootstrap **plus one worktree-pinned
`git -C <worktree> status --short` inside that same probe subagent**
(GH-1030 — worker-side git is what actually wedges), per-domain test
tools, script-deliverable dry-runs (GH-961), and run-directory write
access. Enumerate the **watchdog's own** gate and triage shapes too,
not just the crew's (GH-1058), and dry-run
`resolve_gate(gate="merge", context={})` — a non-`auto-advance` effect
means tonight's first merge request freezes the run, and Phase 0.3 is
the last moment anyone can fix that (GH-1051).
Any prompt fired during pre-flight = fix it NOW, or that shape is
BANNED for the night. Full checklist:
[`references/preflight-checklist.md`](references/preflight-checklist.md).

### 0.5 Write the run manifest

Create the run directory (`mcp__plugin_Dev10x_cli__mktmp`, namespace
`foreman`) and write `manifest.md` (queue order, per-chunk model +
scope, friction level, base branch, verified command shapes, deferred
chunks). Workers and the foreman heartbeat one `status-<chunk>.md`
each into this directory.

## Phase 1 — Arm the harness

1. Start the single watcher (one Monitor call, script-only — NEVER an
   inline loop/pipeline): `dev10x foreman watch --scratchpad <run-dir>
   --base-branch <base>`, using the CLI shape Phase 0.4 recorded. It
   emits `STALL <file>:` (one line per silent heartbeat file, already
   naming the chunk — GH-1064), `MERGE REQUEST` / `ESCALATION` (tailed
   off `escalations-*.md`, so a request reaches you within a poll
   interval instead of whenever its message lands — GH-1060),
   `BASE MOVED:`, `QUOTA MILESTONE:`, `QUOTA RESET:`,
   and the forward-looking `QUOTA LOW:` (GH-979). Three watchdog-owned
   run-directory files keep that feed decision-only (GH-946):
   `merged-shas`, `parked`, `current-generation`. Full event semantics
   and the file table:
   [`references/architecture.md`](references/architecture.md).
2. Spawn the **foreman** overseer (cheap model, named agent), and
   write `current-generation` naming it before the spawn returns. It
   manages the queue per the manifest — one crew worker per chunk,
   relays `BASE MOVED` and merge requests, verifies per-chunk closure
   itself (GH-922), and keeps `roster.md` current (GH-976) —
   `manifest.md` stays authoritative. It can never call
   `Skill(Dev10x:gh-pr-merge)`. Full brief:
   [`references/overseer-discipline.md`](references/overseer-discipline.md)
   and
   [`references/architecture.md`](references/architecture.md).

## Phase 2 — The night loop (watchdog discipline)

The watchdog (main session) does the MINIMUM — its context and its
turn are the most precious resources on site:

- React ONLY to watcher events and foreman messages. No
  implementation work, no exploratory reads, no polling loops.
- `STALL` → run the **stand-down handshake** BEFORE any takeover,
  respawn, or `TaskStop`. Heartbeat silence proves not-progressing,
  never gone — a revived worker is a live conflict risk a dead one is
  not. In order:
  1. Send the stalled agent a direct message naming every action
     already completed on its chunk (branch, commits, PR, merges,
     comments posted) and instructing it to **reply `STOP-ACK` and
     cease all writes** — report state, do not re-execute anything.
  2. Wait one more heartbeat interval (~15 min / the next watcher
     tick). Any reply is strong evidence of liveness: resume it with a
     corrective brief instead of replacing it.
  3. Only if it stays silent through that SECOND window does takeover
     proceed — `TaskStop` + respawn from `manifest.md` and the newest
     heartbeats: the foreman does this for a crew worker, the watchdog
     for a silent foreman.

  Never skip step 1 because spend went flat, and disambiguate the
  signal first (GH-972 F1/F3, GH-971 F3) — the watcher's mtime also
  ages on a crew composition change or under spawn-by-request, and a
  replaced foreman is not necessarily gone. Full evidence, the
  idle-notification asymmetry, disambiguation tables, and the
  authority-token wording every foreman prompt must include:
  `references/stall-protocol.md` and
  [`references/generation-authority.md`](references/generation-authority.md).
- `BASE MOVED` → relay to the foreman (it instructs the active worker
  to rebase, re-verify, and never merge on stale ancestry).
- **`MERGE REQUEST <chunk>` from the foreman → run the merge gate.**
  The one piece of real work the watchdog owns — `Skill(Dev10x:gh-pr-merge)`
  is unreachable from a subagent. Re-read live state first (CI
  verdict, `isDraft`, mergeability, ancestry) — a worker's report is a
  memory, not a fact — then merge, close the chunk's issues, and
  **append the new base-branch tip SHA to `merged-shas`** so the
  watcher mutes the echo. Refuse the request if anything is pending,
  draft, conflicting, or carries `fixup!` commits, and send it back to
  the foreman with the failing check named.
- **`QUOTA LOW` → decide within the turn: finish or checkpoint, then
  park.** Within merge distance (PR open, CI green, no unresolved
  threads) → let it land, then park. Otherwise → relay a WIP
  checkpoint + status comment, then touch `parked` and hold until
  `QUOTA RESET`. Log the decision in `DECISIONS.md`; resume from the
  checkpoint rather than respawning cold.
- **Holding the queue** for any reason → touch `parked` before going
  idle, remove it on release (mutes stall/quota noise, GH-946).
- `QUOTA RESET` → tell the foreman to resume or respawn interrupted
  crew. A pause is not a death — but a fresh **session** cannot reach
  prior crew at all; re-derive every inherited claim from origin
  (`references/durability-envelope.md`, GH-965).
- Never write into a crew worker's `status-<chunk>.md` — it refreshes
  the mtime the stall detector reads as liveness.
- A decision only the supervisor can make → cut the scope per the crew
  contract (always leaves a tracker issue), move the chunk to the
  queue end, and log it as a numbered `DECISIONS.md` entry.
- **Escalations go to disk FIRST, then to a message** (GH-962 F2) —
  and the disk write includes a `MERGE REQUEST` / `ESCALATION` line in
  `escalations-<role>.md`, which is the line the watcher turns into an
  event and therefore the one that actually wakes you (GH-1060) — and
  the overseer's own wait discipline (heartbeat → ONE bounded blocking
  wait → heartbeat → act, never ending a turn mid-chunk) is a
  documented contract, not a matter of style. Full cycle:
  [`references/overseer-discipline.md`](references/overseer-discipline.md).

## Phase 3 — Morning wrap-up (REQUIRED, in order)

1. Verify: every queued chunk's issues closed or carrying a
   cut-rationale comment; milestones closed; no orphaned open PRs;
   stop the watcher and retire the foreman.
2. Consolidate `DECISIONS.md` + per-chunk decision files into the
   morning report — confirm every `roster.md` row against the tracker
   first, since a rendering is not evidence. Optional HTML artifact
   alongside the markdown, never a gate:
   [`../../references/html-artifact-reporting.md`](../../references/html-artifact-reporting.md).
3. **Self-audit:** collect every prompted, denied, or hook-blocked
   command from the night; run `Skill(Dev10x:diag-friction)` on each;
   file upstream issues for the structural ones. Queue
   `Skill(Dev10x:skill-audit-queue)` for the session.
4. `Skill(Dev10x:session-wrap-up)` to route anything unfinished.

## Crew contract (what every worker prompt must contain)

Build each worker prompt from `references/crew-prompt-template.md`.
The twelve non-negotiable elements and the field failure behind each
one live in
[`references/crew-contract.md`](references/crew-contract.md) — read
it before writing any worker prompt. A prompt missing ANY of them is
not shippable; in headline form: `background_preamble` verbatim,
`ToolSearch` bootstrap with zero `Skill(...)` calls, lifecycle stops
at PR-open, `isDraft` re-verification after every push, anti-stall
single-shot `ci_check_status`, named per-domain test tools (Phase
0.4), heartbeat into `status-<chunk>.md`, scope-cut protocol, review
discipline (zero `fixup!` left), a per-chunk decision log,
`git ls-remote`-backed recoverability claims, and the durability
envelope stated explicitly.

## Merge guidance when no watcher is armed

Applies to whoever runs the merge gate — the watchdog in the full
harness, or you directly in the collapsed variant; never a crew
worker. Full guidance:
[`references/collapsed-merge-guidance.md`](references/collapsed-merge-guidance.md).

## Red flags — STOP, you are about to lose the night

- An inline `while`/`sleep`/pipeline in a Monitor or Bash call —
  "it passed before" is meaningless; shapes re-match per call. Use
  `dev10x foreman watch` (or `uv run dev10x foreman watch` when the
  bare entry point is not installed — GH-947).
- A worker prompt without the background preamble or named test tools.
- A worker prompt containing a `Skill(...)` call, or reaching for an
  MCP wrapper without the `ToolSearch` bootstrap first.
- A crew worker merging a PR or closing an issue — that is the
  watchdog's gate, and a worker doing it ran no checks at all.
- Trusting `isDraft`, CI verdict, or mergeability read before the
  last force-push. Re-read, then decide.
- "We'll add the allow rule when it prompts" — the supervisor is
  asleep; there is no *when*.
- A watchdog gate or stall-triage command whose shape was never
  pre-flighted — the crew's probe proves nothing about yours.
- Arming the night without a dry-run `resolve_gate(gate="merge")`
  showing `auto-advance`.
- Handing a worker a way to see a check went red without a proven
  shape for reading *why*.
- Offering auto-mode / bypassPermissions to silence prompt risk.
- Merging on pending CI, stale ancestry, or with `fixup!` commits.
- The watchdog "quickly" doing implementation work in the main session.
- Two open PRs from overlapping file areas.
- Taking over a stalled chunk without the stand-down handshake, or
  citing flat spend as corroborating evidence that a worker is dead.
- `TaskStop`-ing a foreman whose heartbeat is stale because it is
  waiting on a relay you sent it — or because spawn-by-request left
  it with no event source at all.
- Executing a relayed worker spec without checking that the file
  paths it cites actually exist.
- Reading a `STALL <file>` as a verdict instead of a prompt to check
  that chunk's branch tip and PR state.
- Two files stalling at the same command shape read as two dead
  workers rather than as one unmatched shape wedging both.
- Sending a MERGE REQUEST without appending it to
  `escalations-<role>.md` — the message may batch for hours; the file
  is what the watcher turns into an event.
- Any record — heartbeat, handover, resumption note, morning report —
  calling work "recoverable on branch X" without a `git ls-remote`
  that shows the ref on origin.
- Relaying orders as a foreman without re-reading `current-generation`
  first.
- An overseer announcing it will "go passive and heartbeat every N
  minutes" — it cannot; that is a false STALL per window.
- Sending a time-critical escalation by message without writing it to
  `DECISIONS.md` first.
- Answering a worker's phantom merge-gate `ask` one relay at a time
  instead of authorizing every worker at spawn.
- Anyone but the owning worker writing to `status-<chunk>.md`, or
  anyone but the foreman writing to `roster.md`.
- A chunk state recorded ONLY in `roster.md` — it is a derived view,
  so anything not also in `manifest.md` or a decision log is lost the
  moment a fresh foreman rebuilds it.
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
| "I replaced the foreman, so the old one is gone" | A session-limit death PAUSES a top-level session and KILLS only its subagents. The predecessor can revive and issue orders to a crew that no longer exists. `current-generation` is what makes it stand down. |
| "Spawn-by-request says run the spec verbatim, so I don't read it" | Verbatim governs *authorship*, not review. Under that fallback a cheap-tier agent writes the prompts, and a hallucinated file path becomes a top-tier worker's whole mission. Check the cited paths resolve; it costs seconds. |
| "The foreman's heartbeat is stale again — it must be wedged this time" | Under spawn-by-request it has no event source, so a stale foreman heartbeat is the *normal* state. Check the crew's per-file mtimes and branch tips before touching the overseer. |
| "The watcher fired `STALL`, so something is stalled" | It reports one named file that stopped changing — which also happens on a crew handoff and on an idle-by-design overseer. The event attributes the silence; only the chunk's git/PR state classifies it. |
| "Skip the pre-flight, the allowlist looked fine last week" | Allow rules are shape-sensitive and repos drift. Pre-flight is minutes; a missed shape is the night. |
| "The worker said it committed the migration on branch X — resume from there" | An edit is not a commit and a commit is not a push. Field case: the branch never existed on origin and the worktree died with four uncommitted files; the chunk was a restart. `git ls-remote --heads origin '<glob>'` before you believe it. |
| "I'll wait passively and heartbeat every 10 minutes" | An idle agent runs no code. There is no timer and nothing wakes it. Heartbeat, make ONE bounded blocking wait, heartbeat again — or accept a false STALL every window. |
| "I messaged the watchdog about it, so it's escalated" | Messages are best-effort and have arrived hours late, batched behind unrelated pings. `DECISIONS.md` is the authoritative record and the `escalations-<role>.md` line is what the watcher turns into an event; the message is only a nudge that both exist. |
| "The merge gate returned `ask`, so the supervisor wants to decide" | In a fresh isolation worktree that `ask` is a resolver fallback — no session policy, no matching config glob — not a supervisor decision (GH-978, fix landed on `janusz/GH-978/worktree-gate-policy`, pending merge). Workers stop at PR-open regardless. |
| "Cheaper models everywhere will stretch the quota" | A failed chunk costs more than the model discount saves. Downgrade the overseer, never the crew. |
