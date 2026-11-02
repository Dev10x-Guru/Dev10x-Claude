# Known SKILL.md Size Overrides

Orchestration hubs whose SKILL.md or `instructions.md` exceeds the
200-line budget in `.claude/rules/INDEX.md` § Size Budgets, each with
its cohesion justification. Moved out of INDEX.md, which loads in
every session, to keep that index inside its own rule budget
(GH-1750). New overrides are recorded here, not in INDEX.md. When
this file nears its own 200-line budget, move the `foreman` entry —
most of it — to `skills/foreman/references/` and leave a pointer.

## Overrides

- `work-on` (1191 lines) — 4-phase adaptive orchestrator with
  5 complete play definitions and subagent dispatch patterns
- `skill-audit` (1042 lines) — multi-wave audit with per-skill
  behavioral analysis patterns
- `fanout` (~737 lines instructions) — native-Agent swarm
  orchestrator with 6-phase execution model, swarm context
  payload, recursive-fanout guard, and conflict-wave management
- `foreman` (360 lines instructions, GH-987 — down from 585) —
  unattended night-shift harness: Phase 0 pre-flight, the full Phase 2
  night loop (including the stall stand-down handshake), the crew
  contract headline list, and the red-flag / rationalization tables
  are execution-gating and must stay inline. Depth extracted to
  `references/architecture.md`, `crew-prompt-template.md`,
  `stall-protocol.md`, `overseer-discipline.md`, `crew-contract.md`
  (the twelve-element table — already split out, so it is no longer a
  candidate), `roster.md`, `tool-surface.md`, `durability-envelope.md`,
  `worktree-recovery.md`, `mcp-connectivity.md`, and — new in GH-987 —
  `preflight-checklist.md` (Phase 0.4 command-shape enumeration),
  `gate-policy-detail.md` (Phase 0.3 durable-policy-check procedure;
  the GH-978 worktree caveat retired with the fix, GH-1716),
  `generation-authority.md` (STALL
  signal disambiguation and the `current-generation` authority-token
  contract), and `collapsed-merge-guidance.md` (the no-watcher-armed
  merge fallback), plus — new in GH-1059 — `worker-tool-shapes.md`
  (why the crew template pins Glob over Bash `find`, what
  `{{lint_shape}}` resolves against, and why the `ToolSearch`
  bootstrap is re-run). Both `stall-protocol.md` (371 lines) and
  `crew-prompt-template.md` (385 lines) are already over the 200-line
  reference budget and must not grow further — route any new depth to
  a new reference file instead. GH-1028 is the worked example: the
  worktree-pinning *rule* had to grow the template's bake-in block by
  8 lines because workers receive it verbatim, so all of the
  supporting evidence went to `tool-surface.md` § Subagent Bash CWD
  instead. GH-1059/GH-1066/GH-1063 repeated the pattern: the three new
  tool-shape mandates are worker-verbatim and stayed inline, while
  every line of evidence behind them went to `worker-tool-shapes.md`.
  GH-1052 is the same trade a third time: the
  `run_node_tests(script=…)` steer is worker-verbatim (4 lines in § 5)
  while the night-run evidence and the wrapper's two shape rules went
  to `worker-tool-shapes.md`. GH-1050 is the largest such exception so
  far — the § 6 CWD **mode self-test** replaced an unconditional
  `git -C` mandate the validate-bash hook actually denies, and a worker
  cannot run a test it was not handed, so the whole recipe is inline
  (+24 lines); the three-artifact contradiction table and the
  depth-1-vs-depth-2 evidence went to `worker-tool-shapes.md` § CWD
  mode, and `tool-surface.md` § Subagent Bash CWD was rewritten in
  place at net-zero lines rather than appended to.
  GH-1099/GH-1072 is the pattern applied to `tool-surface.md` itself:
  its § "MCP connectivity is not permanent" grew a second and third
  failure surface (watchdog-wide loss, silently-dropped writes), so the
  section was rewritten in place as a three-row containment table
  *pointing at* the new `references/mcp-connectivity.md`, leaving the
  file at 200 rather than over it. The evidence, the per-surface
  containment, and the finding that reconnect-on-demand is not
  implementable in-repo (the dying hop is harness-owned) all live in
  the new file. The caller-side half of the rule — a write is a
  request, not a receipt — went to `.claude/rules/mcp-tools.md`
  instead, since it binds every MCP caller and not only foreman crews.
  `tool-surface.md` and `overseer-discipline.md` were both AT the
  200-line cap — the next addition to either needs an extraction, not
  an append. GH-1599 did exactly that for `overseer-discipline.md`:
  the overseer-tier fallback ladder moved to the new
  `overseer-fallback-ladder.md` (33 lines), leaving a 3-line pointer,
  and the freed room took the watchdog's never-`mv`/`cp`/`rm`-a-run-dir
  rule (GH-1577) — 194 lines then, 158 after GH-1716 dropped the
  merged GH-978 safety-net section (`instructions.md` 388). GH-1109
  applied the same trade once more: arming and
  tearing down the external wake timer is execution-gating (Phase 1
  step 2 and Phase 3 step 1, ~14 lines inline), while the evidence for why a
  paused session cannot observe its own quota reset went to
  `durability-envelope.md` § Rule 3b. GH-1214 **executed** that split
  plan: the Phase 0.1 convergence-file rule is 9 lines inline and its
  evidence is the new `references/queue-and-model.md`, and the Phase 0.4
  crew-depth probe is 10 lines inline pointing at `mcp-connectivity.md`
  § Absent from spawn — `instructions.md` lands at 382. The same PR is
  the second-largest template exception after GH-1050: the **fatal-shapes
  block** is read by the worker verbatim, before its first Bash call, and
  a block held in a reference file is a block the worker never sees, so
  the 34-line block is inline (`crew-prompt-template.md` → 452) with two
  now-redundant ban sites collapsed into pointers to it, and all of the
  evidence — the ten frozen workers' verbatim last calls, why a ban on
  line 160 does not fire, and the two correct-but-unhelpful validate-bash
  denials — in the new `references/fatal-shapes.md`.
  `preflight-checklist.md` went to 213 for the same reason
  `tool-surface.md` did: a section rewritten in place could not absorb a
  fourth failure surface. Split plan if the template grows again: § 5
  (verified tool shapes) and § 6 (workspace + branch) are the next
  extractable pair — both are `{{placeholder}}`-driven and could be
  assembled from `worker-tool-shapes.md` rather than restated, leaving
  the template as the *order* of the brief plus the verbatim blocks that
  must be read in it
- `git-groom` (~1100 lines instructions, GH-1705) — history rewriting
  with the commit-losing guards interleaved with the strategies they
  protect; split plan in the file's override note
- `plugin-maintenance` (~1100 lines, GH-1705) — settings-writing steps
  whose mode tags must match the orchestration task lists (GH-1127);
  split plan in the file's override note
- `diag-friction` (~370 lines, GH-1727) — procedures moved to
  `references/step-details.md`; the map-read mandate, backfill gate,
  Step 3h routing table and retry gate stay inline
- `project-scope` (~440 lines, GH-1705) — four-phase pipeline with
  scope, project-entity and tracker gates
- `ticket-create` (~350 lines, GH-1704/GH-1705) — mode detection,
  never-file-bare triage, Step 4e gate, Step 5 dispatch contract;
  recipes in `references/tracker-creation.md`
- `ddd` (~299 lines) — workshop orchestration hub: 4 session
  modes, 7-layer event storming flow, solo AI-cast facilitation
  (incl. the GH-789 discussion-agent model-tier gate), and
  quality gates are semantically cohesive; depth extracted to 13
  reference files. GH-783 executed the split plan (was: move
  scaffolding + mode task lists to `references/session-modes.md`)
  — New Workshop scaffolding, per-mode `TaskCreate` lists, and the
  mode-determination table now live in
  `references/session-modes.md`; back under the 300-line soft
  target
