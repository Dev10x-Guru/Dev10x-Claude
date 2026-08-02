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

### 0.3 Gate policy — adaptive + afk by default (GH-944)

**The default composition is `gate_preset: adaptive` +
`gate_overlays: [afk]`** — auto-advancing walk-away. That is not a
convenience: an unattended run whose gates still fire freezes on the
first one until morning, so the harness's own posture must be the
walk-away posture, and the supervisor opts *out*, not in.

1. Check the durable policy source — the global
   `~/.config/Dev10x/friction.yaml` (ADR-0018; the per-repo
   `.claude/Dev10x/config.yaml` is retired and holds nothing durable).
   Read the matching `projects[]` entry, or call
   `mcp__plugin_Dev10x_cli__preset_pin_status` and verify with a
   `resolve_gate` probe. **If a policy already covers this checkout**
   (`gate_preset` / `gate_overlays` resolved), honor it verbatim and
   **skip the gate** — a persisted choice is the supervisor's answer,
   and re-asking is exactly the friction this harness exists to
   remove. Record which policy was adopted in `DECISIONS.md` and
   continue to 0.4.
2. Otherwise offer the override once, with the default pre-selected —
   **REQUIRED: Call `AskUserQuestion`** (do NOT use plain text):
   - `adaptive + afk` **(Recommended)** — full walk-away, merges
     included; the default this harness assumes
   - `guided + afk` — walk-away pipeline, but merge stays a human
     action (`merge: skip`); pick this on a shared/team repo
   - `strict` — every gate fires; only sane if the supervisor is in
     fact staying
   **No contrary answer means the default**: proceed with
   `adaptive + afk` rather than blocking the queue.
3. Invoke `Skill(Dev10x:afk)` to compose the chosen policy (it is
   read-before-write, so it is a no-op when the durable config already
   matches). For `guided + afk`, set `gate_preset: guided` and let the
   `afk` overlay ride on top — see `../../references/friction-levels.md`
   and the `Dev10x:afk` § Relationship to Presets and Overlays.

**The composed policy does not reach a spawned worktree** (GH-962 F1).
A worker dispatched with `isolation="worktree"` gets a fresh checkout
with no session policy, on an agent-generated path that matches no
`projects[].match` glob — so `resolve_gate(gate="merge")` falls back
to defaults and returns `ask` even under `adaptive + afk`. **GH-978
has landed the code-level fix** (worktree-first probe with repo-root
fallback) on branch `janusz/GH-978/worktree-gate-policy`; until it
merges to `develop`, warn every worker at spawn that a phantom merge
`ask` is an artifact of its checkout and not a supervisor decision,
and record the standing authorization once in `DECISIONS.md`. Wording
and rationale:
[`references/overseer-discipline.md`](references/overseer-discipline.md)
§ The merge gate reads `ask` in fresh worktrees; do not hand-write
config into a worker's worktree as a substitute.

This harness is **never YOLO**: do not offer, suggest, or accept
`bypassPermissions` / auto-mode as the answer to prompt risk. Walk-away
autonomy comes from the gate policy, which keeps the permission model
authoritative; auto-mode discards it.

### 0.4 Permission pre-flight (the one-time window)

Enumerate and dry-run EVERY command shape the night will use — now,
while a prompt costs seconds instead of hours:

1. `dev10x foreman probe --scratchpad <run-dir>` — proves the watcher
   CLI runs unprompted and the quota/base/heartbeat reads work.
   **Resolve the CLI shape here and record it in the manifest** — the
   bare `dev10x` entry point exists only when the CLI is installed as a
   uv tool. Probe once with the bare shape; on 127 fall back in this
   order and use whichever answers for `watch` in Phase 1 too:

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
5. **Script deliverables, not just test runners** (GH-961). For every
   queued chunk whose *deliverable* includes an executable artifact —
   a `bin/*.sh`, a generated compose file, a CLI entry point — dry-run
   THAT artifact's own invocation shape, or add a narrow allow rule
   for it, during this window. A worker that modifies a shell script
   legitimately needs to execute it to verify the change, and a
   manifest that bans "executing repo shell scripts" wholesale as
   unproven leaves that worker with no sanctioned path. Field case: a
   chunk whose deliverable was `bin/render-worktree-config.sh` hit a
   permission prompt mid-night, then hit a second one from the
   banned-shape workaround it improvised
   (`ENV=x docker compose config 2>&1 | grep -A2 …` — env prefix plus
   redirect plus pipe). Record each proven shape in the manifest so
   the worker never has to improvise.
6. Write access to the run directory and the repo tree.

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

   Use the shape Phase 0.4 recorded — `uv run dev10x foreman watch …`
   inside a plugin-repo checkout (GH-947), or
   `uv run --project $CLAUDE_PLUGIN_ROOT dev10x foreman watch …` for a
   normal plugin-cache install (GH-961). Do not re-derive it here: a
   127 at arming time is exactly the failure the manifest entry exists
   to prevent.

   It emits: `STALL:` (heartbeat silence ≥ 25 min), `BASE MOVED:`,
   `QUOTA MILESTONE:`, `QUOTA RESET:` (5h block rollover — resume
   interrupted crew).

   Two run-directory files keep that feed decision-only (GH-946) —
   both are watchdog-owned, like `manifest.md`:

   | File | Written when | Watcher effect |
   |---|---|---|
   | `merged-shas` | After every merge the gate performs — append the resulting base-branch tip SHA, one per line, `#` comments allowed. Read the SHA from a source already in the pre-flight surface: the `BASE MOVED old→new` event the watcher emits for the run's own merge, or the `base origin/<branch>: <sha>` line of `dev10x foreman probe`
(it is read from the remote via `ls-remote`, so it never needs a
fetch and never goes stale — GH-964) — never a separate raw git call the allow-list doesn't cover | A `BASE MOVED` whose new tip matches is the run's own echo: rebaselined silently, no relay, no classification turn |
   | `parked` | Touched when the queue is deliberately held (burn gate, supervisor hold); removed on release | While present, `STALL` and `QUOTA MILESTONE` are suppressed; muted milestones roll up into one `QUOTA MILESTONE (parked rollup)` line on release, and the stall clock gets one window of grace so resuming crew is not alarmed on immediately |
   | `current-generation` | Rewritten by the watchdog every time a foreman is spawned or replaced: one line, `G<n> <agent-name> <UTC timestamp>` | Nothing in the watcher — it is the foremen's own authority token. A foreman re-reads it before every broadcast, spawn, or relay; if the name is not its own, it stands itself down (GH-971 F3) |

   Keep `merged-shas` current: a skipped append costs a full relay
   plus a `git log old..origin/<base>` verification turn to conclude
   the run merged it itself.
2. Spawn the **foreman** overseer (cheap model, named agent), and
   write `current-generation` naming it before the spawn returns. Its
   brief: re-read `current-generation` before every broadcast, spawn
   request, relay or queue advance and stand down if the name is not
   its own (GH-971 F3 — see Phase 2); follow the wait cycle and the
   disk-first escalation order in
   [`references/overseer-discipline.md`](references/overseer-discipline.md),
   which also carries the standing merge-gate authorization every
   worker prompt must repeat (GH-962); manage the queue per the
   manifest — spawn one crew worker
   per chunk (prompt built from
   `references/crew-prompt-template.md`), relay `BASE MOVED` rebase
   instructions, relay each finished chunk's PR to the watchdog for
   the merge gate, verify per-chunk closure, advance the queue, defer
   cut scope to the queue end, heartbeat to `status-foreman.md` every
   ~10 min, and keep `roster.md` current — the one at-a-glance table of
   every delegated chunk (`Chunk | Issue(s) | State | PR | Worker |
   Last update`), rewritten in the same turn as each transition's
   existing heartbeat or decision line, so the queue reads at a glance
   instead of being reconstructed from every status file in turn. It is
   a foreman-owned derived view — `manifest.md` and the decision logs
   stay authoritative:
   [`references/roster.md`](references/roster.md) (GH-976). Its prompt
   opens with the same `ToolSearch` select-query
   bootstrap as a crew prompt — without it the foreman cannot call
   `issue_get`/`pr_get`, and any closure it reports is a
   transcription of a worker's claim rather than an observation
   (GH-922). It can never call `Skill(Dev10x:gh-pr-merge)`. If the
   platform denies the foreman the Agent tool, it falls back to
   **spawn-by-request**: it sends the watchdog a ready-to-execute
   worker spec via SendMessage, and the watchdog runs that one Agent
   call — verbatim in authorship, but never unread. Two consequences
   bind for the rest of the night (`references/architecture.md`):
   - **Sanity-check the spec before executing it** (GH-972 F2). The
     cheap-tier overseer is now authoring prompts, not just relaying
     them. Confirm every cited file path resolves (`Glob`/`Read`), the
     issue numbers match the manifest, and the branch/worktree follow
     the run convention. On a miss, correct that section from
     `issue_get` and tell the foreman, so its next spec is better.
   - **The event flow inverts**: the watchdog becomes the workers'
     parent and receives their lifecycle events, so the foreman is
     idle by design and its heartbeat WILL go stale on a cadence. Log
     the mode in `DECISIONS.md` and read every `STALL` on
     `status-foreman.md` under the carve-out in Phase 2.

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

  **Disambiguate the signal before the handshake** (GH-972 F3). The
  watcher reports the newest heartbeat mtime across the whole run
  directory, so it also ages when the crew's *composition* changes —
  an idle-by-design overseer, or the handoff window between one
  worker finishing and the next's first heartbeat. `stat` the
  individual `status-<chunk>.md` files to find WHICH one is stale,
  then check that chunk's branch tip and PR/CI state. A stale file
  belonging to an agent that is idle by instruction is expected, not
  a fault. The shapes and their ground-truth checks are tabulated in
  `references/stall-protocol.md` § Structural false positives.

  **A replaced foreman is not necessarily gone — a session-limit
  death is a PAUSE for a top-level session and a KILL for its
  subagents** (GH-971 F3). "The silent foreman is gone" is therefore
  a false premise: an interrupted foreman can revive well before its
  stated reset, resume issuing instructions, and leave two live
  supervisors on one queue — each unaware of the other, the older one
  acting on stale state and relaying orders to a crew that
  `SendMessage` reports as having no transcript. Observed twice in
  one run, across two generations.

  The asymmetry is what makes it invisible: the workers really are
  dead, so a revived foreman's crew never contradicts it.

  **Carry a durable authority token.** The run dir gets a
  `current-generation` file — one line, `G<n> <agent-name>
  <UTC timestamp>` — rewritten by the watchdog on every foreman spawn
  or replacement. Every foreman prompt must include:

  > Before ANY broadcast, spawn request, relay, or queue advance,
  > `Read` `<run-dir>/current-generation`. If the agent name on that
  > line is not yours, you have been replaced: write one final line to
  > `status-foreman.md` saying so, send no further messages, and stop.
  > Do not verify this by asking another agent — the file is the
  > authority.

  This makes replacement idempotent from the predecessor's side, so a
  revival stands itself down instead of needing the watchdog to
  notice. `TaskStop` remains the watchdog's tool, not its only
  defence. Distinct from GH-965, which covers the flat-roster spawn
  limit and the non-survival of subagent transcripts: that is about
  what a revived foreman *can reach*; this is about the orchestrator
  treating a pause as a death and creating the duplicate at all.

  **Under spawn-by-request, a `STALL` on `status-foreman.md` is
  expected noise, not a fault** (GH-972 F1). The foreman has no event
  source of its own in that mode — worker events arrive at YOU — so
  it cannot heartbeat on its own schedule. The default response is a
  nudge ("report state and heartbeat"), never a respawn; escalate to
  `TaskStop` only if it also ignores a direct message through a
  second window.

  Two further rules live in that same file and bind here: a respawn
  gets a FRESH worktree, so uncommitted work in a dead worker's tree
  is reachable only by the watchdog entering it directly (GH-957);
  and after two stalls of identical shape on one chunk, the third
  respawn switches model tier rather than rewriting the brief again
  (GH-956).
- `BASE MOVED` → relay to the foreman (it instructs the active worker
  to rebase, re-verify, and never merge on stale ancestry).
- **`MERGE REQUEST <chunk>` from the foreman → run the merge gate.**
  This is the one piece of real work the watchdog owns, because it is
  the one piece nobody below it can do: `Skill(Dev10x:gh-pr-merge)`
  is unreachable from a subagent. Re-read live state first (CI
  verdict, `isDraft`, mergeability, ancestry) — a worker's report is
  a memory, not a fact — then merge and close the chunk's issues via
  `issue_close` / `milestone_close`, then **append the new base-branch
  tip SHA to `merged-shas`** so the watcher mutes the echo of this very
  merge instead of relaying it back as external movement. That append
  plus the `DECISIONS.md` entry is also how the merge reaches
  `roster.md`: the foreman flips the row at its next wake. The watchdog
  does not edit the roster itself. Refuse the
  request if anything is pending, draft, conflicting, or carries
  `fixup!` commits, and send it back to the foreman with the failing
  check named.
- **Holding the queue** (burn gate, waiting on a quota block, a
  supervisor-only decision that stalls the whole queue) → touch
  `parked` in the run directory before going idle and remove it on
  release. That mutes quota-milestone spam and the stall alarms an
  instructed-idle crew would otherwise trip, so the hold does not
  invent an ad-hoc batching policy per run (GH-946).
- `QUOTA RESET` after a mid-block pause → tell the foreman to resume
  or respawn interrupted crew. An agent idle **by instruction** — a
  foreman holding for a relay like this one — has expected-stale
  heartbeats; a literal "silent foreman → `TaskStop`" reading would
  destroy a healthy overseer mid-wait. The handshake tells the cases
  apart.

  A pause is not a death. If the **session itself** died and this is
  a fresh one, none of the previous crew is reachable — transcripts
  do not cross a session boundary, so every worker must be freshly
  spawned and every inherited claim re-derived from origin before it
  is acted on. Read
  [`references/durability-envelope.md`](references/durability-envelope.md)
  before building any resumption plan (GH-965).
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
- **Escalations go to disk FIRST, then to a message** (GH-962 F2).
  Agent-to-agent messaging is best-effort notification, not a
  channel — one time-critical escalation arrived hours late, batched
  behind unrelated pings, and the run recovered only because the same
  content was in `DECISIONS.md`. Write the numbered entry, then send
  the nudge, and never block on the reply. Reading side: when
  something has gone quiet, read the run directory before concluding
  nothing was said.
- **The overseer's own wait discipline** is a documented contract, not
  a matter of style: heartbeat, ONE bounded blocking wait
  (`TaskOutput(block=true, timeout≈600s)` or equivalent), heartbeat
  again, then act — and never end a turn while workers are mid-chunk.
  "I will go passive and still heartbeat every ~10 min" is not
  achievable; an idle agent runs no code and writes nothing, so it
  trips a false STALL every window. Full cycle and rationale:
  [`references/overseer-discipline.md`](references/overseer-discipline.md).

## Phase 3 — Morning wrap-up (REQUIRED, in order)

1. Verify: every queued chunk's issues closed or carrying a
   cut-rationale comment; milestones closed via `milestone_close`;
   no orphaned open PRs; stop the watcher and retire the foreman.
2. Consolidate `DECISIONS.md` + per-chunk decision files into the
   morning report (delivered/cut table per chunk, PRs + merge SHAs,
   open threads needing the supervisor). `roster.md` is the skeleton
   of that table — confirm every row against the tracker before it
   ships, since the roster is a rendering and a rendering is not
   evidence.
3. **Self-audit (the skill improves itself):** collect every
   prompted, denied, or hook-blocked command from the night; run
   `Skill(Dev10x:diag-friction)` on each offender; file upstream
   issues proposing command-skill-map entries or hook guidance for
   the structural ones — **blocking with guidance beats being
   stopped mid-track**. Queue `Skill(Dev10x:skill-audit-queue)` for
   the session.
4. `Skill(Dev10x:session-wrap-up)` to route anything unfinished.

## Crew contract (what every worker prompt must contain)

Build each worker prompt from `references/crew-prompt-template.md`. The
twelve non-negotiable elements and the field failure behind each one live
in [`references/crew-contract.md`](references/crew-contract.md) — read
it before writing any worker prompt. A prompt missing ANY of them is
not shippable; in headline form:

1. `background_preamble` prepended verbatim
2. `ToolSearch` bootstrap, and ZERO `Skill(...)` calls
3. Lifecycle stops at PR-open — workers never merge, never close issues
4. Post-condition re-verification of `isDraft` after every push
5. Anti-stall rule — single-shot `ci_check_status`, no blocking waits
6. Named per-domain test tools with exact invocation (from Phase 0.4)
7. Heartbeat protocol into `status-<chunk>.md`
8. Scope authority + cut protocol — every cut ends as a tracker issue
9. Review discipline — all comments addressed, zero `fixup!` left
10. Decision log file per chunk
11. Recoverability claims backed by `git ls-remote` evidence — never
    assert "work is on branch X" from the edit alone
12. The durability envelope stated: pushed commits and tracker
    comments survive; a worker-local scratchpad or uncommitted tree
    does not

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
- Reading a `STALL` as a verdict instead of a prompt to `stat` the
  individual status files.
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
| "The watcher fired `STALL`, so something is stalled" | The watcher reports the newest mtime in the run dir; it also ages on a crew handoff and on an idle-by-design overseer. `stat` the individual files and read the chunk's git/PR state before concluding. |
| "Skip the pre-flight, the allowlist looked fine last week" | Allow rules are shape-sensitive and repos drift. Pre-flight is minutes; a missed shape is the night. |
| "The worker said it committed the migration on branch X — resume from there" | An edit is not a commit and a commit is not a push. Field case: the branch never existed on origin and the worktree died with four uncommitted files; the chunk was a restart. `git ls-remote --heads origin '<glob>'` before you believe it. |
| "I'll wait passively and heartbeat every 10 minutes" | An idle agent runs no code. There is no timer and nothing wakes it. Heartbeat, make ONE bounded blocking wait, heartbeat again — or accept a false STALL every window. |
| "I messaged the watchdog about it, so it's escalated" | Messages are best-effort and have arrived hours late, batched behind unrelated pings. `DECISIONS.md` is the authoritative channel; the message is only a nudge that it exists. |
| "The merge gate returned `ask`, so the supervisor wants to decide" | In a fresh isolation worktree that `ask` is a resolver fallback — no session policy, no matching config glob — not a supervisor decision (GH-978, fix landed on `janusz/GH-978/worktree-gate-policy`, pending merge). Workers stop at PR-open regardless. |
| "Cheaper models everywhere will stretch the quota" | A failed chunk costs more than the model discount saves. Downgrade the overseer, never the crew. |
