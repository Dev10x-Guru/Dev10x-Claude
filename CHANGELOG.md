# Changelog

All notable changes to the Dev10x Claude Code Plugin are documented here.
This project adheres to [Semantic Versioning](https://semver.org/).

## Unreleased

## 0.80.0 — Continuous Learning Loop, Installable PR-Review Action & Source-Derived Permissions

Released 2026-06-25

### Features

- **Close the review-to-rule learning loop** — recurring PR review
  comments are mined into candidate patterns, scored for confidence and
  false-positive risk, authored into reference rules, and surfaced for
  review, so the system learns from past reviews instead of repeating
  them ([GH-346](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/346),
  [GH-347](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/347),
  [GH-348](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/348),
  [GH-349](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/349),
  [GH-350](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/350),
  [GH-353](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/353))
- **Install Dev10x PR review as a GitHub Action on any repo** — a guided
  setup wires up the reviewer Action, including learned-rule review, on
  repositories beyond this one
  ([GH-351](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/351),
  [GH-352](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/352),
  [GH-707](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/707))
- **Derive permissions from a source two-axis manifest** — a
  source-derived manifest plus proactive seeding grants default-safe
  reads for surfaces like Sentry, JIRA, and Vercel, unifies sensitivity
  classification across surfaces, and seeds rule provenance fleet-wide
  for worktrees, so safe reads stop re-prompting per project
  ([GH-600](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/600),
  [GH-601](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/601),
  [GH-602](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/602),
  [GH-603](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/603),
  [GH-606](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/606),
  [GH-607](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/607))
- **Approve sensitive read probes in-session** — credentialed reads and
  sensitive probes can be approved without dropping to a manual shell,
  and read-only MCP tools can be promoted to global settings
  ([GH-604](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/604),
  [GH-480](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/480))
- **Run node/yarn dev loops off the Bash layer** — `run_node_tests`
  brings jest/vitest/yarn/npm/pnpm test runs through the MCP boundary,
  sidestepping the brace-expansion block no allow-rule could suppress
  ([GH-703](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/703))
- **Run PR-state merge checks without the raw CLI** and **distinguish
  required from advisory CI verdicts**, so merge gating reflects which
  checks actually block
  ([GH-668](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/668),
  [GH-658](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/658))
- **Enable server-initiated LLM sampling** via a `request_sampling` MCP
  tool ([GH-343](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/343))
- **Trust the plan while attending later gates** — background subagents
  stay off hook-tripping command shapes and the supervisor can defer
  attention to later decision gates
  ([GH-678](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/678),
  [GH-610](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/610))
- **Register platforms during onboarding** and resolve skill-script
  paths canonically, with diag-friction routing for four more raw
  command shapes
  ([GH-528](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/528),
  [GH-611](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/611),
  [GH-609](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/609))
- **Establish pre-commit as the canonical lint entry point** — ruff,
  shellcheck, and mypy run through `.pre-commit-config.yaml` as the
  single lint gate
  ([GH-619](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/619))

### Security

- **Close the DX003 interpreter-stdin execution bypass** — piping a
  script into an interpreter's stdin no longer evades the execution
  safety validator
  ([GH-687](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/687))

### Performance

- **Collect release PRs in one batch query** instead of per-PR fetches,
  and reduce git subprocess forks at session stop
  ([GH-550](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/550),
  [GH-552](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/552))

### Fixes

- **Resolve git-fixup misfire on a stale local develop** — the
  fixup-target resolver cross-checks `origin/develop` instead of a stale
  local ref ([GH-676](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/676))
- **Enable closing issues as not planned**
  ([GH-674](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/674))
- **Match plugin skill-script grants across roots and `//`**
  ([GH-704](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/704))
- **Surface hook-denial findings to MCP audit callers** and in default
  installs, so friction-riddled sessions no longer report zero unmatched
  calls ([GH-507](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/507),
  [GH-574](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/574))
- **Fail closed when safety validators raise**, rather than letting an
  exception open the gate
  ([GH-494](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/494))
- **Prevent the daemon from killing the wrong process** and keep the
  roots cache fresh by retaining the refresh task
  ([GH-573](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/573),
  [GH-498](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/498))

### Hardening

- **Close write races across session, settings, and lock state** —
  bounded waits on contended file locks, torn-write protection for the
  applied-version stamp, lost-update protection for `SessionStore.update`
  and settings mutators, and non-interleaving concurrent skill-metric
  lines ([GH-555](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/555),
  [GH-558](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/558),
  [GH-562](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/562),
  [GH-571](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/571))
- **Ensure Slack send failures reach callers** and keep the MCP server
  from crashing on missing config
  ([GH-537](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/537),
  [GH-532](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/532))

### Refactors

- **Enforce the Result contract at the MCP boundary** (ADR-0009) and
  adopt Catalog, Query Object, AbstractHook, and Value Object archetypes
  across the permission, session, github, and validator packages, sealing
  package boundaries and typing the domain models throughout
  ([GH-509](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/509),
  [GH-654](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/654),
  [GH-584](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/584))
- **Consolidate permission config on `projects.yaml`** and centralize
  protected-branch handling, validator dispatch, and session-state
  capture ([GH-577](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/577),
  [GH-583](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/583),
  [GH-635](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/635))

### Tests

- **Enforce default-stage mypy and shellcheck warnings** and strengthen
  the permission-classifier fixture corpus via evidence triage, closing
  CI-hang and reproducibility gaps
  ([GH-619](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/619),
  [GH-271](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/271),
  [GH-614](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/614))

### Docs

- **Document any-repo install and the learning loop**, the accepted App
  JWT argv exposure, and permission-rule generalization patterns
  ([GH-354](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/354),
  [GH-499](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/499),
  [GH-592](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/592))

## 0.79.0 — Permission Friction Reduction, Structured Policy Model & Cross-Fork PRs

Released 2026-06-08

### Features

- **Model permission rules as structured policies** — the flat
  allow-rule string list becomes typed `Policy` value objects carrying
  tier, source, and effect, laying the foundation for the deny catalog,
  user/project source precedence, and worktree forward-sync that the
  GH-271 friction evidence converged on
  ([GH-271](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/271))
- **Close six permission-friction and tooling gaps in one bundle** —
  DX014 matches production hosts by context rather than a bare `prod-`
  prefix (GH-482), `uvx`-launched `skill notify slack-send` declares
  slack-sdk so it actually runs (GH-483, thanks
  [@szx19970521](https://github.com/szx19970521) for surfacing it in
  [#487](https://github.com/Dev10x-Guru/Dev10x-Claude/pull/487)),
  `issue_comment` gains a
  `body_file` arg (GH-484), DX007 normalizes `uv run` env-flags before
  prefix-matching (GH-485), git-groom resolves its base against
  `origin/<base>` instead of a stale local ref (GH-486), and
  project-audit persists its Phase 4 findings memo (GH-481)
  ([GH-481](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/481))
- **See which read-only MCP tools and research domains can go global** —
  `dev10x permission promote-plan` produces a deduped, read-only dry-run
  plan of the claude.ai-hosted tools and WebFetch domains that re-prompt
  per project, so they can move to global settings instead of being
  re-approved in every repo (write tools and plugin-distributed tools
  are never promoted)
  ([GH-470](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/470))
- **Open cross-fork PRs through `create_pr`** — `create_pr` /
  `Dev10x:gh-pr-create` accept an optional head repo, push the branch to
  the fork owner's remote, and emit `--head <owner>:<branch>`, so
  contributing to an external repo from a fork keeps the wrapper's Job
  Story, commit list, summary comment, and notify flow
  ([GH-473](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/473))

### Security

- **Refuse to auto-approve `uv run --with` installs** — `--with <pkg>`
  now disqualifies `uv run` auto-approval, closing a supply-chain hole
  where an allowed inner command silently installed an arbitrary package
  and bypassed the fence-tool ask
  ([GH-485](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/485))

### Fixes

- **Surface hook denials in skill-audit friction reports** — Phase 4 now
  scans the tool-result blocks it previously dropped for
  `permissionDecision: deny` and `BLOCKED:` validator signals, so
  sessions riddled with hook friction no longer report "0 unmatched
  calls"
  ([GH-474](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/474))
- **Allow containerized and 1Password-wrapped psql through the DB gate**
  — the DX004 read-only SQL gate exempts `docker exec … psql` (runs in a
  test container) and `op run -- psql` (the sanctioned secrets wrapper)
  while still blocking bare host psql
  ([GH-474](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/474))
- **Reclaim merged agent worktrees holding replicated dirt** — fanout
  teardown force-removes merged-but-dirty worktrees when their only
  changes are stale or a repo-wide `.claude/` rewrite replicated
  identically across siblings, so leftovers stop piling up
  ([GH-476](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/476))
- **Stop bash/sh/zsh exec from bypassing DX003** — the execution-safety
  guard now covers shell interpreters alongside python3, steering
  `bash /tmp/x.sh` and `sh -c …` to the Write-tool/uv-script path
  instead of relying on an unreliable deny-rule
  ([GH-469](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/469))
- **Run plugin scripts without re-prompting** — plugin-maintenance emits
  concrete version-pinned script rules instead of `**` globs that Claude
  Code's Bash matcher never matches, and purges the dead globs that were
  masking script coverage
  ([GH-471](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/471))

### Docs

- **Document worktree CWD and push discipline** — the git-worktree skill
  now warns that `cd` does not persist between Bash calls and that raw
  `git push` is hook-blocked, steering callers to absolute paths and
  `Skill(Dev10x:git)`
  ([GH-474](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/474))
- **Document the lessons-learned implementation plan** — capture the
  GH-460 plan for harvesting merged PRs and review threads into the
  learning loop
  ([GH-460](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/460))

## 0.78.0 — MCP Client Integration, Swarm Teardown & CI Quality Gates

Released 2026-06-03

### Features

- **Read Dev10x knowledge as addressable MCP resources** — playbooks,
  rules, references docs, and the skill index are exposed under
  `dev10x://` URIs, so MCP clients read them directly instead of
  falling back to Bash tool-calls or filesystem searches
  ([GH-339](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/339))
- **Invoke review, commit, and jtbd templates as MCP prompts** — the
  workflow templates are registered as first-class MCP prompts with
  argument autocomplete, so clients run Dev10x's conventions without
  re-deriving them by hand each time
  ([GH-340](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/340))
- **Keep client resource caches fresh** — a knowledge-resource watcher
  polls the files backing the registered MCP resources and emits
  `list_changed`/`updated` notifications when they change on disk, so
  connected clients refresh instead of serving stale content
  ([GH-341](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/341))
- **See progress on long-running MCP tools** — `run_tests`,
  `mass_rewrite`, `rebase_groom`, and `create_pr` stream progress and
  log notifications when the client supplies a progress token, so long
  operations no longer look like a silent stall
  ([GH-342](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/342))
- **Scope MCP operations to client-declared directory roots** — the
  server fetches and caches the client's `roots/list`, refreshes on
  `roots/list_changed`, and exposes a `list_client_roots` tool so
  skills can validate CWD against what the client considers in-scope,
  with a `DEV10X_ROOTS_ENABLED=0` escape hatch
  ([GH-344](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/344))
- **Tear down swarm worktrees after merge** — fanout now runs a
  teardown decision tree per merged child PR (remove clean worktrees,
  force-remove stale duplicates of develop HEAD, keep and surface
  genuinely unique content), prunes leftovers, and delegates abandoned
  branch cleanup to the new branch-prune skill
  ([GH-463](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/463))
- **Prune stale local branches in rebase-merge repos** — the new
  `Dev10x:git-branch-prune` skill classifies branches into four
  categories (gone-upstream, merged-ancestor, content-landed-via-
  rebase, ahead/undecidable) behind a REQUIRED deletion gate, so
  branch hygiene works in repos where `git branch --merged` misses
  most merged branches
  ([GH-464](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/464))
- **Block performance regressions in CI** — the benchmark suite runs
  on every PR against a cached per-branch baseline and fails on a mean
  regression greater than 20%, so hook-latency and startup regressions
  can no longer ship undetected
  ([GH-432](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/432))
- **Enforce hook-test coverage in CI** — the hooks workflow measures
  coverage against a 70% threshold and the project-wide floor rose
  from a stale 38% to 75%, so coverage discipline is machine-enforced
  rather than agent-dependent
  ([GH-433](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/433))
- **Warn before editing code whose spec is stale** — the experimental
  `DX015` spec-drift validator fires on Edit/Write when the branch's
  ticket maps to an active spec not yet touched in the working set,
  moving the Golden Rule from "skill-if-invoked" to "hook-always"
  (opt-in via `DEV10X_HOOK_EXPERIMENTAL=1`)
  ([GH-434](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/434))
- **Audit skill usage inline by default** — skill-audit's new
  lightweight strategy works from visible conversation context with a
  single disposition gate; the forensic transcript-extraction fan-out
  moves behind `--full` or auto-escalation, so most sessions capture
  findings without a separate terminal
  ([GH-436](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/436))
- **Harvest merged PRs and review threads for the learning loop** —
  fail-soft fetchers turn closed PRs and their inline review threads
  into structured data, feeding downstream clustering and
  candidate-rule scoring without re-scraping GitHub
  ([GH-345](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/345))
- **Find all Dev10x config under XDG paths** — `databases.yaml` is
  discovered at `~/.config/Dev10x/`
  ([GH-448](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/448)),
  global playbook overrides resolve from
  `~/.config/Dev10x/playbooks/`
  ([GH-445](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/445)),
  and upgrade-cleanup migrates both automatically — including configs
  stranded in hidden backup directories
  ([GH-446](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/446),
  [GH-447](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/447))
- **Detect stale running hooks at SessionStart** — the session
  compares the running-hook version against the latest installed
  plugin and nudges for a restart when a mid-session
  `claude plugin update` left shipped friction fixes dormant
  ([GH-407](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/407))

### Fixes

- **Resume dead swarm agents instead of re-dispatching** — fanout now
  prefers SendMessage resume when an agent's turn dies, swarm children
  verify their worktree before any branch checkout, gh-pr-merge runs
  comment checks strictly after CI is green (closing the bot-post
  race), the drift gate no longer offers switching to a deleted
  branch, and canonical MCP parameter shapes are documented to prevent
  first-call validation errors
  ([GH-462](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/462))
- **Survive hostile worktree topologies in fanout** — child worktrees
  stay writable and base-safe (branch-upstream guard prevents bare
  pushes from advancing the base PR), and orchestrators dispatching
  from a sibling worktree detect the cross-repo-root condition and
  fall back to serial mode
  ([GH-424](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/424),
  [GH-427](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/427))
- **Stop full-mode cleanup from reintroducing friction** —
  plugin-maintenance's global-dedup and doctor canonicalize are now
  opt-in (`--aggressive`), preserving the project-local rules and
  literal `~/` paths the permission engine actually needs
  ([GH-420](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/420))
- **Send Slack notifications from any install context** —
  `uvx dev10x skill notify slack-send` calls an importable module
  instead of resolving filesystem paths into `skills/`, so it works
  when installed as a wheel
  ([GH-442](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/442))
- **Recover the MCP server from a deleted process CWD** — when the
  worktree the server was spawned in is removed after a merge, the
  server chdirs to the plugin root instead of failing every
  subsequent subprocess call with ENOENT
  ([GH-418](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/418))

### Refactors

- **Encode friction-level behaviour on the enum itself** —
  `pending_decisions_guidance()` and `fallback_guidance()` replace
  if/elif dispatch chains in the decision-guidance rule and
  skill-redirect message formatting
  ([GH-249](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/249))

### Docs

- **Unified backpressure architecture reference** — a single doc maps
  the two-direction model (action gating + output gates) across every
  hook, validator, and completion-gate surface
  ([GH-435](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/435))
- Rule-index updates for `DX014`/`DX015` and the perf CI gate;
  corrected the investigate skill's Common Mistakes routing table
  ([GH-444](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/444))

## 0.77.0 — Persistent MCP Daemon, Sensitivity-Axis Gating & Live GitHub Contract Tests

Released 2026-06-01

### Features

- **Run the MCP servers as a persistent daemon over HTTP** — a managed
  background daemon adds health checks, graceful shutdown, and
  restart-safe lock handling, per-client session state is maintained
  across StreamableHTTP requests, and a new session-aware client wires
  Claude Code to the running daemon when it is healthy while falling
  back to a fresh per-session STDIO server when it is not, so sessions
  pay lower startup overhead with no manual configuration
  ([GH-336](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/336),
  [GH-337](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/337),
  [GH-338](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/338))
- **Keep MCP tools working after a bound worktree is deleted** — cli
  tool calls now fall back gracefully instead of failing with ENOENT
  when a worktree is removed after a branch merge, so `mktmp` and the
  other MCP tools keep working in post-merge sessions instead of
  hitting "Current directory does not exist"
  ([GH-410](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/410))
- **Gate commands that touch sensitive targets** — a new orthogonal
  sensitivity axis classifies actions against secrets, credentials,
  PII, and production infrastructure, and the `DX014` validator blocks
  and asks for review before executing even trivially-reversible reads
  that the tier and reversibility axes alone would let through
  ([GH-406](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/406),
  [GH-395](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/395))
- **Catch GitHub GraphQL/REST field drift before it reaches sessions** —
  a live contract-test tier exercises the GitHub-backed MCP read tools
  (`pr_get`, `pr_comments`) against the real REST/GraphQL surface and a
  known fixture PR, and queries are validated against the published
  GraphQL schema, so invalid fields and response-shape drift are caught
  in CI instead of forcing a downstream session to fall back to raw `gh`
  ([GH-398](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/398),
  [GH-386](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/386))
- **Smoke-test a release candidate before tagging** — the release flow
  now builds and installs the wheel locally, prints the real remote
  side effects before the irreversible tag, and requires a live
  `--plugin-dir` run for changes that touch the MCP server or
  permission hooks, so a broken server/hook surface can no longer reach
  PyPI or move the marketplace ref by accident
  ([GH-387](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/387))
- **Sharpen the permission doctor across worktrees** — the doctor now
  surfaces horizontal duplicates when multiple MCP servers expose the
  same capability under different prefixes, and anchors each project's
  `.worktrees` parent across every CWD-keyed permission scope, so
  cross-worktree work no longer drifts out of coverage
  ([GH-371](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/371),
  [GH-376](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/376))
- **Self-review a green PR before pinging a teammate** —
  `Dev10x:gh-pr-request-review` lets a supervisor eyeball the PR
  themselves and defer the review request cleanly, with the DoD runner
  picking up the gh-pr checks and a standby Write permission so the
  flow runs without friction
  ([GH-396](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/396))
- **Run fanout swarms straight through to merged PRs** — each
  `Dev10x:work-on` child in a worktree-isolated swarm no longer stalls
  after branch or PR creation, so the orchestrator carries every item
  to completion without manual nudging
  ([GH-368](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/368))
- **Read plugin-maintenance preferences from the XDG config path** —
  `Dev10x:plugin-maintenance` now reads and writes
  `plugin-maintenance-prefs.yaml` under `~/.config/Dev10x/`, completing
  the XDG config-layout migration
  ([GH-390](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/390))
- **Name milestones without collisions across initiatives** —
  milestone naming gains initiative-prefixed conventions so parallel
  initiatives can create milestones without clashing
  ([GH-388](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/388))

### Fixes

- **Stop `permission clean` from silently removing covered rules** —
  cleanup no longer drops project-local rules that may not be covered
  by global rules, ending phantom permission prompts after a clean
  ([GH-391](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/391))
- **Restore `mass-rewrite.py` to its un-mangled form** — a bulk-rewrite
  workaround had corrupted the file's glyphs, docstring, and print
  strings; it is restored to its last-good commit so git-groom
  mass-rewrite works correctly
  ([GH-415](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/415))

## 0.76.0 — Friction-Free CLI, Typed MCP Boundaries & Smarter PR Review

Released 2026-05-31

### Features

- **Pre-approve the safe inspection surface so unattended runs stop
  stalling** — narrow allow-rules for read-only tools, `--version`
  flags, and read-only git/gh/uv subcommands let adaptive and AFK
  sessions run without tripping the permission gate or the "don't ask
  again" catch-all footgun
  ([GH-310](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/310))
- **Run structured-data tools without a prompt** — 15 read-only
  processors and validators (`jq`, `yamllint`, `actionlint`, `shellcheck`,
  binary-existence lookups, and more) join the base permission catalog,
  so the canonical structural alternatives `Dev10x:diag-friction` steers
  toward no longer prompt themselves
  ([GH-308](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/308))
- **Pre-approve docs, extracted probes, Railway, and safe git flags** —
  four permission-catalog follow-ups land together: ~30 canonical HTTPS
  doc domains for WebFetch, execution of extracted `/tmp/Dev10x` and
  `~/.claude/tools` probes, a Railway read-only tier-3 group, and a
  `flag_overrides` schema that ships `git clean -n`, `git branch -d`,
  and `git reset --dry-run`
  ([GH-369](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/369),
  [GH-370](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/370),
  [GH-372](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/372),
  [GH-373](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/373))
- **Stop quoted shell metacharacters from triggering false blocks** — a
  quote-aware tokenizer strips single-quoted spans, ANSI-C strings, and
  escaped pairs before threat detection, and the new `DX012`
  safe-expansion validator approves commands whose metacharacters resolve
  to known-safe env vars, so `gh api graphql -f query='{...}'` and
  `echo "$CLAUDE_PLUGIN_ROOT"` pass cleanly
  ([GH-309](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/309))
- **Block MCP tool names pasted as shell commands** — the new `DX013`
  validator hard-blocks a command whose first token matches
  `mcp__<server>__<tool>` and steers back to the tool-call protocol,
  closing a recurring failure mode that memory and docs alone could not
  prevent
  ([GH-375](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/375))
- **Steer in-place stream editors to the Write/Edit tool** — flag-aware
  detection routes `sed -i`, `perl -i`, `gawk -i inplace`, and
  `dd of=<file>` to the editing tools while leaving read-only `sed -n`
  and `awk` forms untouched
  ([GH-374](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/374))
- **Request JIRA and Slack reviews without env-prefix friction** — the
  `dev10x:jira` base skill becomes the plugin-bundled `Dev10x:jira` with
  a documented tenant-wrapper pattern, and `Dev10x:slack-review-request`
  gains a real `dev10x skill notify` CLI surface, so neither tenant
  wrappers nor Slack steps fall back to version-pinned script paths
  ([GH-233](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/233),
  [GH-313](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/313))
- **Edit PR inline review-thread comments via MCP** — the new
  `pr_review_comment_edit` wrapper covers the `pulls/comments` endpoint
  that `issue_comment_edit` could not reach, so clearing a stale bot
  finding to unblock the merge gate no longer needs raw `gh api PATCH`
  ([GH-304](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/304))
- **Push small fixes directly during PR review** — `Dev10x:gh-pr-review`
  adds a courtesy-fixup path that classifies mechanical findings
  (unused imports, trivial renames, dead code) and offers a batch scope
  gate before pushing, ending the comment-then-author round-trip
  ([GH-323](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/323))
- **Leave a PR review as a GitHub draft** — a draft-vs-submit gate in
  `Dev10x:gh-pr-review` lets reviewers finalize on the Files-changed tab
  before the review becomes visible, with intent-detection defaults and
  author-aware biasing
  ([GH-319](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/319))
- **Use comment reactions as a triage signal** — `Dev10x:gh-pr-triage`
  reads a comment's reactions as a verdict lean when no directing prose
  exists, and `Dev10x:gh-pr-respond` surfaces a `Signal` column so
  reaction-only verdicts stay auditable before the batch approval gate
  ([GH-314](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/314))
- **Catch a stale CLI before running maintenance** — `Dev10x:plugin-maintenance`
  now reads the marketplace manifest and installed versions in a
  preflight step, prompts to update when either surface is behind, and
  can persist the choice so future sessions skip the prompt
  ([GH-307](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/307))
- **Surface parked work from the canonical session store** —
  `Dev10x:park-discover` now reads `session.yaml` as its primary
  substrate, every park writer indexes into that store, and its
  documented commands route through Read/Grep/MCP wrappers instead of
  friction-triggering `cat`/`grep -rn`/subshell forms
  ([GH-85](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/85))
- **Run the MCP servers over HTTP without code changes** — a
  `DEV10X_MCP_TRANSPORT` env var selects the transport, making the
  daemon/HTTP path opt-in while STDIO stays the default
  ([GH-335](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/335))
- **Normalize PyCharm/uv worktrees after checkout** — the new
  `Dev10x:ide-normalize` skill fixes `.idea/` module names, disables the
  `ADD_CONTENT_ROOTS` setting that breaks editable installs, backfills the
  Django settings module, and patches the uv-SDK FLAVOR_DATA gap that
  crashed PyCharm on fresh worktrees
  ([GH-320](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/320))

### Hardening

- **Block privilege-escalation commands by default** — `sudo`, `doas`,
  `pkexec`, and `sudoedit` deny rules ship in the base catalog for any
  command shape, with a narrow `sudo-apt` opt-in group for routine
  package management, closing the root-level bypass an agent reached for
  in the wild
  ([GH-326](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/326))

### Fixes

- **Restore the `pr_get` and `resolve_review_thread` MCP tools** — both
  wrappers failed and forced raw `gh` fallbacks; `pr_get` no longer
  requests the invalid `merged` field (deriving merged-ness from state),
  `resolve_review_thread` queries the correct `reviewThreads` shape, and
  `request-review` routes detection through the stable `pr_detect` wrapper
  ([GH-329](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/329))
- **Convert a PR review to draft only when inline comments exist** — the
  CI review step queries the real `reviewComments` count instead of
  trusting the model's recollection, ending spurious draft conversions
  that blocked merge with zero findings
  ([GH-333](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/333))
- **Stop the permission generalizer from emitting invalid rules** — two
  classes of bug produced mid-string `:*` forms that Claude Code rejects
  after running maintenance on 0.75.0; the generalizer pattern and two
  redundant `grep` rules are fixed, with a regression test for the
  quoted-JSON-blob arg case
  ([GH-315](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/315))
- **Unblock the pre-PR gate on every branch** — the doctor passes
  `str(cwd)` to `subprocess_utils.run`, resolving a mypy type mismatch
  that the GH-245 cwd-discipline merge introduced on develop
  ([GH-245](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/245))

### Refactors

- **Enforce a uniform `Result[T]` contract at the MCP boundary** — the
  polymorphic `to_dict` branch is dropped, `record_upgrade` and `_gh_api`
  return `Result[dict]`, and the 1834-line `server_cli.py` splits into
  github/git/plan/audit/misc tool modules; ADR-0009 records the decision
  ([GH-243](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/243))
- **Seal context boundaries with domain protocols** — Milestone 5 of the
  architecture audit adds ADR-0007/0008, moves session policy rules and
  the audit writer behind protocols, extracts `SettingsDocument` for
  settings I/O, and re-homes the audit-skills permission analysis so the
  context boundary points the right way
  ([GH-244](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/244))
- **Make subprocess calls honor the caller's worktree** — a sync
  `subprocess_utils.run` chokepoint defaults `cwd` to the bound effective
  CWD, direct `subprocess.run`/`os.getcwd()`/module-scope `GitContext()`
  usages are routed through it, and a lint test forbids regressions
  ([GH-245](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/245))
- **Resolve contradictory allow-rule diagnostics** — a single canonical
  `AllowRule` value object with space-boundary-aware matching replaces
  four drifted matchers and several duplicated settings loaders, so a
  rule can no longer be reported matched by one diagnostic and unmatched
  by another
  ([GH-242](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/242))
- **Extract skill logic into importable, unit-tested modules** — the
  release classifier, JTBD extraction, Slack formatting, permission
  config loading, skill-index builder, and subagent-status/batch-detection
  protocols move into `dev10x.skills.*` modules with full coverage, the
  dead PR-status batch query API is retired, and the audit-skills boundary
  is sealed
  ([GH-246](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/246),
  [GH-248](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/248),
  [GH-244](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/244))
- **Replace dispatch chains with declarative patterns** — Milestone 10
  of the architecture audit applies map-based dispatch and the
  template-method pattern across hooks, validators, and the task state
  machine, retiring if/elif chains and per-call should_run/validate
  sequencing (11 of 36 findings; the rest deferred)
  ([GH-249](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/249))
- **Drop env-prefix friction from plugin-maintenance, JIRA, and
  aws-vault** — maintenance steps route uniformly through
  `uvx dev10x permission`, and the JIRA and aws-vault scripts accept a
  leading `--tenant`/`--registry` flag so callers never need the
  allow-rule-defeating `VAR=value script.sh` prefix
  ([GH-306](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/306),
  [GH-311](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/311))

### Tests

- **Cover the recently shipped MCP and CLI shipping paths** — handler
  tests land for PR/issue comment, review-request, and thread-resolution
  tools, plus playbook CLI and config-schema validation, closing the M8
  audit's zero-coverage gaps
  ([GH-247](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/247))
- **Stop plan_sync tests from polluting the repo root** — the two
  offending tests return a real `tmp_path`, and a session-scoped autouse
  guard removes and fails on stray `<MagicMock …>` files
  ([GH-332](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/332))

### Docs

- **Ratify the importable-module policy and script-vs-domain rules** —
  ADR-0010 records that skill logic lives in importable modules with
  thin uv-script shims, a new boundaries rule sets the print-vs-logging
  and `sys.exit`-vs-`Result` conventions, and `ci_check_status` emits its
  error JSON on stdout so stdout-parsing consumers never see empty output
  ([GH-246](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/246))
- **Record the `dev10x` CLI invocation benchmark and decision** —
  ADR-0012 captures the startup comparison of `dev10x`, `uvx dev10x`, and
  the in-process call, leading with `dev10x …` as the preferred form and
  keeping `uvx dev10x …` as the zero-install fallback
- **Document validator, permission, and orchestration test patterns** —
  new reference docs capture safe-flag overrides, multi-flag validator
  detection, validator test structure, permission tier-assignment logic,
  and regression/schema testing for orchestration paths, distilled from
  lessons-learned analysis
  ([GH-271](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/271))

## 0.75.0 — Friction Reduction, Typed Boundaries & Business-ROI JTBD

Released 2026-05-27

### Features

- **Anchor JTBD Job Stories in business ROI** — the `Dev10x:jtbd`
  skill now traces refactor, infrastructure, and dependency-bump
  work up to the end-customer outcome instead of accepting "the
  developer wants to" as the actor, so every PR body, ticket scope,
  and release note inherits business-meaningful framing. A new
  doctrine memo grounds the rule with worked examples and citations
  ([GH-276](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/276))
- **Eliminate per-version permission churn via the `uvx dev10x`
  CLI** — plugin-maintenance work routes through the version-stable
  CLI so a single set of allow-rules survives every plugin upgrade,
  retiring four cache-path shim scripts that went stale on each
  version bump
  ([GH-269](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/269))
- **Allow trimmer pipelines without broadening allow-rules** — the
  new `PipelineAllowValidator` (DX011) auto-approves `| tail`,
  `| head`, and `| wc` pipelines when every segment already matches
  an existing Bash allow-rule, removing a recurring source of one-off
  approval prompts
  ([GH-262](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/262))
- **Edit and delete PR/issue comments via MCP** — `issue_comment_edit`
  and `issue_comment_delete` wrappers replace raw `gh api PATCH/DELETE`
  calls, so the "edit a stale bot finding to clear the merge gate"
  workflow no longer triggers an approval prompt
  ([GH-283](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/283))
- **Recommend structured tools in `diag-friction`** — blocked
  inline-code commands now map to canonical tools (yq, jq, yamllint,
  actionlint, curl) from a bundled knowledge base instead of always
  suggesting a `~/.claude/tools/` extraction
  ([GH-282](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/282))
- **Land fixups on the commits that own their lines** — `Dev10x:git-fixup`
  blames each staged hunk against the branch range to target the owning
  commit, ending the autosquash conflict loops that rerere memoized
  ([GH-299](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/299))
- **Enable scope-aware triage and priority-split responses** — a YAGNI
  verdict in `gh-pr-triage` plus a now/fast-follow priority axis in
  `gh-pr-respond` let reviewers route out-of-scope findings and defer
  non-urgent VALIDs without manual steering
  ([GH-297](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/297))
- **Prevent silent feature activation via reused relations** — PR
  review gains a cross-consumer behavioural-reuse check that flags when
  populating an existing relation could activate a feature gated on row
  presence in a sibling repo
  ([GH-290](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/290))
- **Prevent context-anxiety pauses in adaptive solo sessions** — a
  SessionStart reassurance block fires under adaptive friction with a
  solo maintainer so the agent trusts long task lists instead of
  re-asking settled scope decisions
  ([GH-261](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/261))
- **Expose the Dev10x config root via bare CLI invocation and finish
  the XDG migration** — bare `dev10x` echoes the resolved config root
  for portable shell idioms, and the last three user configs migrate
  off `~/.claude/` so fresh projects no longer hit the sensitive-path
  consent gate
  ([GH-270](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/270))
- **Ship AWS Secrets Manager access as a plugin-bundled skill** —
  `Dev10x:aws-vault` relocates the secrets/kubectl wrappers out of
  user space with a configurable service registry so the skill is
  shareable across projects

### Fixes

- **Stabilize the permission doctor on wheel installs** — the baseline
  permissions catalog now ships inside the package and resolves via a
  module-relative path, fixing the `FileNotFoundError` crash on
  PyPI-installed dev10x
  ([GH-264](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/264))

### Hardening

- **Enforce atomic writes and locks on boundary hot paths** — session
  state, plan context, the platform registry, and the audit log now use
  atomic writes and file locks so concurrent worktrees, parallel hooks,
  and the long-lived MCP server cannot lose state in a race; ADR-0011
  documents the layered atomicity model
  ([GH-240](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/240))

### Refactors

- **Enforce typed identifiers across plan and PR surfaces** — five new
  value objects (Task, TicketId, SkillName, RepositoryRef, BranchName)
  replace dict-of-Any threading and scattered regex literals, validating
  inputs once at each boundary
  ([GH-241](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/241))
- **Ship flaky-test fixes through the `work-on` pipeline** —
  `Dev10x:py-test-flaky` is now a thin investigator and ticket scoper
  that hands delivery to `Dev10x:work-on`, so flaky fixes inherit the
  same gates, self-review, and PR monitoring as any other ticket
  ([GH-281](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/281))
- **Strip forbidden-token priming from skill docs** — skill bodies no
  longer name `DEV10X_SKIP_CMD_VALIDATION` as a negative example, and a
  doctor strategy scans for the priming token outside the hook layer
  ([GH-272](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/272))

### Docs

- **Anchor config paths in cross-platform notation** — skill docs use
  abstract `<Dev10x config>/<file>` paths backed by a platform
  resolution table instead of literal `~/.config/Dev10x/` forms that
  misled Windows users
  ([GH-270](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/270))
- **Ensure the no-checkpoints rule travels with auto-advance** — a
  canonical "no checkpoints" definition plus per-skill reinforcement
  stops adaptive-friction sessions from inserting "Ready to proceed?"
  pauses mid-pipeline
  ([GH-223](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/223))
- **Route fixup comment fetch through MCP wrappers** — `Dev10x:git-fixup`
  Step 2 documents `pr_detect` and `pr_comments` instead of the raw `gh`
  shapes the friction scanner forbids
  ([GH-299](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/299))
- **Document review and testing patterns from superseded bot PRs** —
  add the backlog-deferral format, pytest fixture/async handler
  patterns, the hook refactor + lazy-import checklist, and the
  instructions.md allowed-tools scope clarification
  ([GH-202](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/202),
  [GH-124](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/124),
  [GH-130](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/130),
  [GH-104](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/104))

## 0.74.0 — MCP Routing Coverage & Session Mode Awareness

Released 2026-05-21

### Features

- **Route pytest through the `run_tests` MCP wrapper** — `Dev10x:py-test`
  now drives test execution through the MCP tool so coverage gates,
  output capture, and skill enforcement stay consistent across
  invocations
  ([GH-238](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/238))
- **Route `gh pr view` and issue state changes through MCP wrappers** —
  `pr_get`, `issue_close`, and `issue_reopen` replace raw `gh` calls,
  closing the last common CLI fallbacks the routing hook saw in the
  wild
  ([GH-267](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/267))
- **Route `ticket-scope` comments through the `issue_comment` MCP tool**
  — scoping comments land via the structured wrapper instead of `gh
  issue comment`
  ([GH-228](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/228))
- **Surface session mode and classify interrupts** — sessions now
  expose their active mode (attended, walk-away, etc.) and classify
  interrupts so skills can adapt their gating behavior
  ([GH-189](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/189),
  [GH-229](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/229))
- **Pre-format Python files before staging in `git-commit`** —
  ruff/black run automatically on staged Python changes so commits
  never carry unformatted code
  ([GH-224](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/224))

### Fixes

- **Restore `Dev10x:py-test` after a hook hard-block regression** —
  the validation hook no longer hard-blocks the documented `uv run
  pytest` invocation that `Dev10x:py-test` retries
  ([GH-274](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/274))

### Refactors

- **Codify skill-name suffix convention and apply the rename map** —
  skill directory and invocation names now follow a consistent suffix
  convention; the rename map keeps backward references working
  ([GH-217](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/217))
- **Trim `diag-friction` and `gh-pr-review` SKILL.md bodies** — both
  skill bodies were extracted to references so per-invocation token
  cost drops without losing detail
  ([GH-197](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/197),
  [GH-199](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/199))

## 0.73.0 — XDG Config, MCP Wrapper Coverage & Walk-Away Mode

Released 2026-05-19

### Features

- **Move Dev10x userspace config out of `~/.claude/`** — config now
  lives under the OS-standard XDG path (`~/.config/Dev10x/` on
  Linux/macOS, `%APPDATA%/Dev10x/` on Windows; override via
  `DEV10X_CONFIG_HOME`). Legacy files at `~/.claude/memory/Dev10x/`
  and `~/.claude/Dev10x/` are migrated lazily on first read and
  explicitly by `dev10x config migrate` (wired into both
  `Dev10x:upgrade-cleanup` Step 1 and `Dev10x:doctor` Step 0)
  ([GH-215](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/215))
- **Enable spec-as-source-of-truth pipeline (SPDD)** — M1 milestone
  lands the spec-driven development flow so tickets, code, and
  acceptance criteria stay aligned from a single source
- **Close GitHub CLI wrapper gap with 4 new MCP tools** —
  `milestone_create`, `issue_edit`, `issue_comment`, and
  `issue_list` replace raw `gh api`/`gh issue` invocations so
  the routing hook can steer agents away from CLI fallbacks
  ([GH-220](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/220))
- **Route `project-scope` through bulk MCP wrappers** — milestone
  and issue creation use the bulk tools, eliminating per-item
  approval friction for multi-ticket projects
  ([GH-222](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/222))
- **Route `gh pr edit` to the `update_pr` MCP wrapper** — drops
  another raw-CLI path and keeps PR edits behind the structured
  wrapper
  ([GH-209](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/209))
- **Enable `gh-pr-merge` Step 5 via the `merge_pr` MCP tool** —
  final merge step runs through the wrapper so guardrails stay
  consistent end-to-end
  ([GH-232](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/232))
- **Enable walk-away mode for unattended sessions** — supervisor
  can hand off long-running flows so the user does not need to
  baby-sit each prompt
  ([GH-231](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/231))
- **Defer skill-audit invocations via `Dev10x:skill-audit-queue`** —
  audits run asynchronously instead of blocking the active session
  ([GH-219](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/219))
- **Detect Slack-forwarded threads in `ticket-scope` Phase 1.2** —
  forwarded threads carry their original context so scoping reads
  the right conversation
  ([GH-218](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/218))
- **Enable sibling pub/sub coordination via a JSONL bus** —
  parallel sub-agents exchange progress and findings on a shared
  JSONL channel
  ([GH-133](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/133))
- **Surface `push_safe` results so callers can confirm pushes** —
  the wrapper now returns `{pushed, ref, remote, sha, tracking,
  ci_run_url}` instead of `{}` on success, removing the
  silent-success ambiguity
  ([GH-188](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/188))
- **Surface permission-friction diagnosis as `diag-friction`** —
  refactored diagnosis is now a first-class command/skill
  ([GH-214](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/214))
- **Advise on redundant content fetches in PreToolUse** — agents
  get steered away from re-reading content the session already
  loaded
  ([GH-206](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/206))
- **Steer agents to serialized commands over shell loops** —
  guidance hook nudges toward separate tool calls instead of
  `for`/`while` bash loops that defeat permission matching
  ([GH-234](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/234))
- **Audit every validation bypass via a rationale string** — the
  skip path now requires a justification recorded in the audit
  log
  ([GH-226](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/226))

### Fixes

- **Stabilize skill self-checks and permission rules**
  ([GH-252](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/252))
- **Stop Gate 6 from silently skipping after resolve** —
  `gh-pr-respond` now re-validates instead of treating a
  resolved thread as fully addressed
  ([GH-208](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/208))
- **Stop false-positive blocks on `find -name 'git-push-safe.sh'`** —
  the validator no longer mistakes the literal pattern for a
  push command
  ([GH-210](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/210))

### Docs & Internals

- Record 2026-05-18 architecture audit findings under `docs/memos/`
- Document Example 5 in the diag-friction examples list
- Restore ruff format on doctor and permission modules

## 0.72.0 — Doctor, Fanout Swarm & Permission Hygiene

Released 2026-05-17

### Features

- **Diagnose systemic drift with `Dev10x:doctor`** — new skill
  surfaces plugin-version mismatches, missing per-project skill
  pre-approvals, and clusters session paths to propose coherent
  directory coverage so permission friction is fixed at the root
  ([GH-87](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/87),
  [GH-116](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/116),
  [GH-115](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/115))
- **Prompt for upgrade-cleanup when plugin version drifts** —
  SessionStart detects an installed version newer than the
  recorded baseline and nudges the user toward
  `Dev10x:upgrade-cleanup`
  ([GH-109](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/109))
- **Enable native-Agent fanout swarm dispatch** — `Dev10x:fanout`
  now dispatches independent work items as parallel sub-agents
  with a 6-phase execution model, conflict-wave management, and
  recursive-fanout guard
  ([GH-36](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/36))
- **Invert monitor architecture to supervisor + micro-agents** —
  `gh-pr-monitor` runs a long-lived supervisor that dispatches
  read-only micro-agents per check, constrained by contract so
  background monitors cannot mutate the repo
  ([GH-68](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/68))
- **Enable solo-maintainer milestone-bundle PR shipping** —
  `work-on` and `gh-pr-create` understand parent tracker tickets
  and bundle overlapping sub-tickets into a single PR with a
  scoped review auto-skip
  ([GH-185](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/185),
  [GH-196](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/196),
  [GH-161](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/161))
- **Adopt subagent status protocol across orchestration** —
  orchestrators read explicit `DONE / DONE_WITH_CONCERNS /
  NEEDS_CONTEXT / BLOCKED` status from dispatched agents
  ([GH-69](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/69))
- **Pre-approve Linear MCP tools in plugin baseline** — drops
  per-session approval prompts for Linear issue, comment, and
  document operations
  ([GH-204](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/204))
- **Enable top-level PR issue-comment replies via MCP** — new
  `pr_issue_comment` tool replaces raw `gh api POST` fallbacks
  ([GH-205](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/205))
- **Enable multi-workspace Slack posting** — Slack skills route
  per-workspace credentials so multiple orgs can be addressed
  from one session
  ([GH-98](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/98))
- **Enforce push-then-create order in `gh-pr-create`** — branch
  is pushed before `gh pr create` runs, eliminating empty-PR
  failures
  ([GH-159](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/159))
- **Default `gh-pr-merge` to rebase for curated history** —
  matches the project's atomic-commit convention
  ([GH-134](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/134))
- **Enforce one-fixup-per-comment via mechanical guardrail** —
  prevents bundled fixup commits that obscure review traceability
  ([GH-123](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/123))
- **Detect branch drift before commits land off-target** —
  pre-commit gate catches mistargeted feature work
  ([GH-147](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/147))
- **Enrich audit issues with bundling labels** — skill-audit
  output groups related findings for batched remediation
  ([GH-190](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/190))
- **Enable early-insight short-circuit in `skill-audit`** —
  surfaces high-confidence findings before all phases complete
  ([GH-113](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/113))
- **Enable bundled-fixup replies and post-groom SHA refresh** —
  PR comment replies follow rebase-rewritten history
  ([GH-86](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/86))
- **Compare user playbooks against plugin defaults** — surfaces
  stale overrides after plugin upgrades
  ([GH-192](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/192))
- **Cover monorepo `uv run --project` invocations with one rule**
  — single allow rule eliminates per-subdir approval prompts
  ([GH-137](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/137))
- **Nudge agents away from prefix-bypassing shell shapes** — new
  hook validator flags `cd && cmd` and env-prefix patterns that
  defeat allow-rule prefix matching
  ([GH-119](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/119))
- **Enable hook-block routing for bare `pytest` invocations** —
  redirects to the `py-test` skill so coverage gating runs
  ([GH-155](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/155))
- **Enable self-healing permission hints** — `skill-reinforcement`
  proposes the missing allow rule alongside the skill redirect
  ([GH-178](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/178))
- **Enforce pre-staging gate in `git-commit` Step 10** — refuses
  to commit when nothing is staged, avoiding empty commits
  ([GH-157](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/157))
- **Enforce Phase 3 plan-approval `AskUserQuestion` always** —
  `work-on` cannot skip the plan-approval gate
  ([GH-158](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/158))
- **Track `skill-audit` invocation as cycle-audit task** —
  audit runs surface as first-class work items
  ([GH-148](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/148))

### Refactors

- **Group domain by archetype into 4 sub-packages** — domain
  layer reorganized along Software Archetypes for clarity
  ([GH-145](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/145))
- **Unify MCP boundary error envelope via `Result[T]`** —
  internal functions return typed `SuccessResult`/`ErrorResult`;
  MCP handlers unwrap at the boundary
  ([GH-108](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/108))
- **Decompose `hooks/session.py` into archetype-aligned modules**
  ([GH-144](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/144))
- **Consolidate Plan domain via service layer + `TaskStatus`** —
  Plan operations route through a service layer with a typed
  status enum
  ([GH-81](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/81))
- **Promote validator registry and capability dispatch** —
  validators register declaratively
  ([GH-82](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/82))
- **Split platform `Registry` and add Tell-Don't-Ask helpers** —
  permission diagnostics and investigator facades promoted to
  public surface
  ([GH-83](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/83))
- **Type hook phase/outcome via `HookPhase` + `HookOutcome`** —
  replace `friction_level` strings with `FrictionLevel` enum,
  `PROFILE_HIERARCHY` tuple with `ProfileTier` enum, and
  centralize Claude Code filesystem paths via `ClaudeDir`
  ([GH-80](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/80))
- **Promote permission helpers to public, drop stdout-capture
  hack** — permission helpers no longer rely on captured stdout
  ([GH-92](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/92))
- **Unify validator error returns with `Result[str]`** — single
  return shape across all validators
  ([GH-78](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/78))
- **Run permission-audit analysis in-process** — eliminates
  subprocess fan-out for audit phases
  ([GH-142](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/142))
- **Consolidate audit log reading into `audit/log_reader`** —
  one reader serves CLI, MCP, and the audit skill
  ([GH-143](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/143))
- **Centralize PR status fetches behind `PRStatusQuery`** —
  removes scattered `gh pr view` calls
  ([GH-146](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/146))

### Fixes

- **Authenticate GitHub App via Bearer scheme** — JWT requests
  now use the correct header
  ([GH-76](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/76))
- **Stabilize subprocess error contract for missing scripts** —
  consistent error shape when scripts are absent
  ([GH-89](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/89))
- **Exclude bot approvals from review-state precheck** — bot
  approvals no longer satisfy human-review gating
  ([GH-128](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/128))
- **Stop blocking `mktmp.sh` args as git commit** — hook
  validator no longer misreads helper invocations
  ([GH-84](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/84))
- **Surface git-repo errors from `plan.json_summary`** —
  callers see the underlying repo error instead of an empty
  payload
  ([GH-78](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/78))

### Security

- **Prevent state file corruption under concurrent writers** —
  state writes use atomic file replacement
  ([GH-77](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/77))
- **Enforce cwd binding on MCP handlers via `@requires_cwd`** —
  handlers cannot operate outside the bound working directory
  ([GH-78](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/78))
- **Constrain background monitor agents to read-only by
  contract** — dispatched monitor sub-agents cannot mutate state
  ([GH-68](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/68))
- **Enforce `gh-pr-merge` skill via raw CLI deny** — raw
  `gh pr merge` is blocked to keep pre-merge gates in play
  ([GH-112](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/112))
- **Allow `uv run dev10x` from plugin-maintenance** — scoped
  allow rule so maintenance can self-invoke
  ([GH-99](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/99))
- **Allow read-only `find` over plugin cache** — narrow rule
  for cache hygiene checks
  ([GH-122](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/122))
- **Enable grep across plugin cache + memory without prompts** —
  removes friction for retrospective queries
  ([GH-135](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/135))

### Docs

- **Keep internal GitHub MCP over official server** — ADR-0006
  documents why Dev10x ships composite GitHub tools rather than
  depending on `github/github-mcp-server`
- **Lift `Verify AC` invariant to a universal Dev10x rule** —
  every skill ends with a Verify-AC terminal task
  ([GH-149](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/149))
- **Close skill-bypass gaps in `work-on` shipping pipeline** —
  documents mandatory skill chain through commit and PR
  ([GH-152](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/152))
- **Mandate `gh-pr-monitor` invocation after PR creation** —
  removes the "and then what?" gap
  ([GH-162](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/162))
- **Close 7 permission/hook gaps across scaffolding and skills**
  ([GH-127](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/127))
- **Plan SPDD REASONS Canvas adoption across scope skills**
  ([GH-70](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/70))
- **Document `Result[T]` envelope in `mcp-tools.md`**
  ([GH-93](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/93))

### Internal

- **Raise test coverage on critical MCP and CLI paths**
  ([GH-79](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/79))
- **Rebaseline `mcp_server_import` startup gate** — startup-time
  budget updated after import refactors
  ([GH-121](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/121))

## 0.71.0 — GitHub App Verification & Acknowledgments

Released 2026-05-08

### Features

- **Prove github-app setup credentials end-to-end** — setup flow
  prompts for install scope (Personal/Org/Manual), accepts a
  `.pem` file path (defaulting to the newest key in `~/Downloads`)
  and stores it under `~/.claude/Dev10x/github-bot/` with chmod
  600, then verifies the App JWT against `GET /app`,
  `GET /app/installations`, and a per-installation token+repo
  read before writing config — failed verification exits without
  saving ([GH-72](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/72))

### Refactors

- **Discourage agents from misusing skip-validation flag** —
  rewrite the skill-redirect block-message hint as a ⚠️ warning
  that names the lazy-bypass pattern and reserves
  `DEV10X_SKIP_CMD_VALIDATION=true` for skill authors, so agents
  stop copy-pasting it as a shortcut around recommended skills

### Docs

- **Acknowledge external contributors and inspirations** — add
  `ACKNOWLEDGMENTS.md` crediting @tiretutor-paul as project
  godfather alongside external bug reporters, and list the
  projects, talks, and writing that shaped Dev10x's design
  (QRSPI / HumanLayer, obra/superpowers, Fowler PoEAA,
  Refactoring Guru, Software Archetypes, gitmoji,
  semantic-release, JTBD community)

### Internal

- **Apply ruff format to permission-related files** — bring six
  pre-existing files under `src/dev10x/skills/permission*` and
  matching tests in line with project style after pre-PR checks
  flagged them on develop

## 0.70.0 — Subagent Protocols & Privacy Hardening

Released 2026-05-05

### Features

- **Enable subagent status protocol parsing** — orchestrators
  read explicit `DONE / DONE_WITH_CONCERNS / NEEDS_CONTEXT /
  BLOCKED` final-status lines from dispatched agents instead of
  guessing from free-form prose, and `gh-pr-monitor`'s GH-901
  fallback parses `BLOCKED:` as the primary signal
  ([GH-69](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/69))
- **Enable bot identity for agent-generated PR replies** — opt-in
  GitHub App identity routes review-thread replies and PR summary
  comments through `dev10x-bot[bot]` while keeping PR creation,
  reviewer assignment, and thread resolution under the engineer's
  account ([GH-65](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/65))
- **Enable in-place PR body updates via MCP tool** — new
  `mcp__plugin_Dev10x_cli__update_pr` lets `gh-pr-create` update
  mode and `git-groom` Phase 4 refresh PR body, title, or base
  branch without raw `gh api PATCH` permission prompts
  ([GH-60](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/60))
- **Stabilize fixup! reply links across grooming** — fixup reply
  comments use absolute `/commit/HASH` permalinks so links keep
  resolving after rebase rewrites SHAs
  ([GH-52](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/52))
- **Detect privacy and external service drift in CI** — a new
  privacy-audit workflow scans source for external services and
  outbound network usage, cross-checks against `PRIVACY_POLICY.md`,
  and comments on PRs that introduce undocumented integrations
  ([GH-6](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/6))

### Fixes

- **Allow MCP tools to target session worktree** — MCP tools that
  shell out to `git`/`gh` honor a per-call `cwd` so EnterWorktree
  sessions stop hitting the spawning repo's branch and dirty-tree
  state ([GH-979](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/979))
- **Cover user-global `settings.json` in upgrade-cleanup
  rewrites** — `update-paths.py` now discovers both
  `~/.claude/settings.json` and `settings.local.json` when
  `include_user_settings: true`, so versioned plugin paths no
  longer go stale after every upgrade
  ([GH-982](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/982))

### Security

- **Scrub private context from skill-audit upstream reports** —
  audit-report and skill-audit Phase 7 redact private repo
  names, branches, tracker IDs, paths, and free-text excerpts
  before filing upstream issues, with `AskUserQuestion` gating
  unscrubbable findings ([GH-56](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/56))

### Refactors

- **Reduce agent dispatch tokens via body extraction** — apply
  the skill-body-extraction strategy to plugin-distributed
  agents; `permission-auditor.md` shrinks from 226 → 159 lines
  with bulk content moved under
  `references/agents/permission-auditor/`
  ([GH-983](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/983))
- **Defer pre-PR checks to project pre-commit settings** —
  `pre-pr-checks.sh` delegates to `pre-commit run` when
  `.pre-commit-config.yaml` is present so projects own their
  ruff/mypy versions and excludes end-to-end
  ([GH-38](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/38))
- **Allow direct-to-base commits in solo-maintainer mode** —
  `git-commit` reads `solo_maintainer` from session config and
  skips the develop/main/master block so single-author repos
  can commit directly to the base branch
  ([GH-57](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/57))

### Docs

- **Inject friction context into skill-audit Wave 2** — Phase 3
  compliance subagent receives `friction_level` and
  `active_modes` so documented auto-select gates score as
  COMPLIANT instead of SKIPPED_STEP
  ([GH-55](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/55))
- **Tighten `ticket-scope` research tool routing** — Phase 2
  mandates Grep/Read tools over bash `grep`/`cat` and Phase 7.1
  routes through the `mktmp` MCP tool
  ([GH-55](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/55))
- **Strengthen `work-on` Phase 1 + Phase 2 enforcement** — route
  workspace detection through `gh-context`, inline the TaskList
  self-check, mark subtask creation REQUIRED before any Agent
  dispatch, and prohibit Explore-subagent dispatch for source
  fetch ([GH-55](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/55))
- **Repoint changelog GH refs to the right repo** — convert
  footnote-style refs to inline links and pin pre-0.67 entries
  plus 0.68 high-number refs to the archived
  `Dev10x-Claude2` repo so historical links keep resolving
  ([GH-53](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/53))

## 0.69.0 — Permission Friction & Audit Empiricism

Released 2026-05-01

### Features

- **Enable empirical investigation of permission rule shapes** —
  audit tooling captures real-world permission rule patterns so
  prefix-friction diagnostics rest on observed behavior instead
  of assumptions ([GH-47](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/47))
- **Emit per-skill Read rules with `~/` + `/home` twins** —
  `plugin-maintenance` writes both expansions so Read rules match
  regardless of which form Claude resolves at allow-check time
  ([GH-48](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/48))
- **Detect Write-overwrite, workspace, and exit-code friction in
  audit** — three new diagnostics surface common permission
  prompt causes that previously slipped past audit reports
  ([GH-46](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/46))
- **Prefer working-dir scripts when CWD is plugin source** —
  hooks and skills resolve script paths to the active checkout
  rather than the installed plugin, so local edits take effect
  immediately ([GH-42](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/42))
- **Register `/tmp/Dev10x` workspace via `plugin-maintenance`
  bootstrap** — first-run setup adds the workspace allow rule so
  `mktmp` and friends stop prompting on fresh installs ([GH-40](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/40))
- **Stop pre-creating files in `mktmp` to avoid Write-overwrite
  prompt** — the MCP tool returns a fresh path without touching
  it, so the first Write call no longer trips the overwrite gate
  ([GH-39](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/39))
- **Expose audit-wrap log discovery via MCP tools** —
  `audit_hook_log_path` and `audit_hook_recent` let skills query
  hook timing data without shelling out ([GH-29](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/29))
- **Add PoC option to `ticket-scope` approval gate** — scoping a
  proof-of-concept ticket no longer forces the full template
  treatment ([GH-33](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/33))
- **Auto-detect Slack state to skip redundant prompts** —
  `slack-review-request` checks for an existing token before
  prompting, smoothing the request-review flow ([GH-19](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/19))

### Fixes

- **Fix Server Tests workflow path** — the CI path filter now
  matches the relocated MCP server module ([GH-9](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/9))
- **Use REST API for PR body updates to avoid Projects-classic
  exit 1** — `gh-pr-create` update mode bypasses a `gh` GraphQL
  failure on repos still attached to classic projects ([GH-41](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/41))
- **Resolve pre-existing mypy errors in MCP github and hook
  audit** — strict typing passes again after the GitHub-domain
  lift
- **Scope pre-PR mypy invocation to `src/`** — match
  `pyproject.toml` so the pre-PR check stops scanning unrelated
  trees

### Refactors

- **Lift the GitHub domain into a top-level package** — MCP
  GitHub helpers move out of the server-internal namespace so
  CLI tools and tests can share them ([GH-9](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/9))
- **Lift simple MCP domains into top-level packages** —
  cohesive single-purpose MCP modules become standalone packages
  for easier reuse ([GH-9](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/9))
- **Reuse subprocess utilities outside the MCP layer** — the
  shared subprocess helper graduates out of `mcp/` so audit and
  CLI consumers stop duplicating it ([GH-9](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/9))
- **Enforce template selection in `ticket-scope` Phase 5.1** —
  skill body blocks free-text drift through the template gate
  ([GH-28](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/28))
- **Enforce `jtbd` delegation in `ticket-scope` Phase 4b** —
  Job Story drafting routes through the dedicated skill
  ([GH-27](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/27))
- **Enforce `instructions.md` read at `ticket-scope` startup** —
  body content loads explicitly so phase logic is visible to the
  agent ([GH-26](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/26))
- **Preserve hook guardrails outside split-rebase docs** —
  `git-commit-split` references hook rules instead of redefining
  them ([GH-15](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/15))
- **Enable consistent coverage gates in skill scripts** — every
  skill script enforces the same coverage threshold ([GH-13](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/13))
- **Route raw `git` CLI in skill bodies through wrappers** —
  skills call the safe-rebase / safe-push wrappers instead of
  raw `git` so guardrails stay in force ([GH-14](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/14))

### Documentation

- **Document fanout-parallel hook propagation surprises** —
  parent hooks may not run inside fanout children; the rule lives
  next to the skill ([GH-32](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/32))
- **Document fanout-parallel cold-load budget floor** — children
  pay a fixed cold-load cost, so fanout below the floor is
  slower than serial ([GH-31](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/31))
- **Document `--bare` strips OAuth in fanout-parallel children**
  — bare clones lose token auth, breaking `gh` calls inside
  fanout children ([GH-30](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/30))
- **Clarify mode prompt overrides preserve skills delegation** —
  override examples no longer suggest dropping skill calls
  ([GH-45](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/45))
- **Forbid skill partial-read downgrade in `work-on`** — the
  skill always reads the full body to keep orchestration
  contracts intact ([GH-44](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/44))
- **Enforce `gh-pr-respond` for all PR review comments** —
  responding directly via `gh` bypasses validation gates
  ([GH-43](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/43))

### Polish

- **Modernize `Result` generics with PEP 695 syntax**
- **Wrap long literal strings in `src/dev10x` and tests**
- **Resolve `RuleEngine F821` in `edit_validator` hook**
- **Sort imports in `skill-audit` script entry points**
- **Remove dead test variables and rename ambiguous loop var**

## 0.68.0 — First-Run Setup & PR-Skill Hardening

Released 2026-04-29

### Features

- **Streamline first-run permission setup** — bootstrap walks new
  users through the minimum permission set so the plugin works
  without per-tool prompting on day one ([GH-1](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1))
- **Detect raw CLI in skill docs to prevent MCP/Skill bypass** —
  reviewer surfaces `gh`/`git` shell-outs in skill bodies that
  should route through MCP tools or sibling skills ([GH-5](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/5))
- **Eliminate per-invocation permission prompts in 18 skills** —
  audit-driven sweep adds the missing `allowed-tools` entries so
  these skills run without approval friction ([GH-11](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/11))
- **Allow scoped `pr_comments` listings on heavily reviewed PRs**
  — pagination + filtering avoid response-size limits on PRs with
  hundreds of threads ([GH-997](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/997))
- **Enable batched comment hiding via single GraphQL mutation** —
  one round-trip hides many comments instead of N requests
  ([GH-987](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/987))
- **Enable bootstrap coverage for uv/yq/git/gh patterns** —
  bootstrap allow rules cover the toolchain seen across skills
  out of the box ([GH-20](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/20))

### Fixes

- **Halt PR creation when pre-PR checks fail** — `gh-pr-create`
  no longer pushes a draft PR when type-check or test gates
  failed ([GH-998](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/998))
- **Enforce ticket-create haiku dispatch and tracker fast-fail**
  — tracker mismatches surface immediately and ticket creation
  uses the right model tier ([GH-998](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/998))
- **Enforce slack-review-request prepare script use** — Slack
  notifications go through the prepared script so token handling
  stays consistent ([GH-998](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/998))
- **Allow numeric-string comment IDs on `pr_comment` reply** —
  reply tool accepts both forms returned by upstream APIs
  ([GH-995](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/995))

### Refactors

- **Eliminate raw `gh` CLI in PR-skill bodies** — PR skills route
  through MCP wrappers, fixing audit findings and removing the
  raw-CLI bypass ([GH-12](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/12))
- **Guard `request-review` against approved PR pings** — already-
  approved PRs no longer ping reviewers redundantly ([GH-993](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/993))

## 0.67.0 — Maintenance & Repository History Pruning

Released 2026-04-26

Maintenance release. No new features or behavior changes — the
plugin keeps its 0.66.0 surface area while the repository itself
gets a fresh start.

### Maintenance

- **Prune repository history** — the public repository was rewound
  to a minimal commit history. Past development history is no
  longer reachable from `main`/`develop`; existing checkouts will
  need a fresh clone.

## 0.66.0 — Skill Slimdown & Post-Upgrade Polish

Released 2026-04-20

### Features

- **Enable pytest flaky-test fix orchestration** —
  `Dev10x:py-test-flaky` orchestrates the full flaky-test
  workflow (reproduce, root-cause, fix, ticket, branch,
  commit, PR) and delegates to Dev10x sibling skills so
  fixes follow project conventions without per-step coaching
- **Streamline upgrade-cleanup post-upgrade flow** —
  `ensure_base` auto-expands stale MCP wildcards, a new
  `enumerate-mcp.py` wrapper runs by absolute path,
  worktree-absolute paths drop out of the merge filter, the
  `session-start-reload.py` allow rule is annotated, and
  `update-paths`/`clean` gain a `--summary` flag so the post-
  v0.65.0 upgrade pass no longer needs hand-holding ([GH-965](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/965))

### Refactors

- **Rename oversized SKILL.md files to instructions.md** —
  pure rename of 14 skill bodies (work-on, skill-audit,
  git-commit, gh-pr-monitor, gh-pr-respond, fanout, git-groom,
  qa-self, scope, git-commit-split, playbook, ticket-scope,
  gh-pr-merge, gh-pr-create) so `git log --follow` preserves
  history ahead of the frontmatter split ([GH-970](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/970))
- **Split skill frontmatter from body via instructions.md** —
  each oversized skill now ships a ~30–50 line SKILL.md (YAML
  frontmatter plus a pointer) with the body in `instructions.md`,
  so MOTD index and skill discovery costs drop and the body only
  loads once a skill is invoked ([GH-970](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/970))
- **Split task-orchestration.md into per-pattern files** —
  the 649-line shared reference shrinks to a 50-line index
  that links to per-pattern files under `references/orchestration/`,
  so downstream consumers keep working without edits and
  pattern detail loads only when a skill links the specific
  file ([GH-970](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/970))

### Documentation

- **Clarify data-handling practices for adopters** — the
  plugin documentation now describes local-only storage paths,
  states that no telemetry or user data leaves the machine,
  enumerates third-party integrations with credential scopes,
  and provides data deletion commands plus the audit-log
  disable switch, closing the disclosure gap flagged by an
  external security audit ([GH-966](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/966))
- **Enable reliable plugin install via shell CLI** — install
  instructions now prefer `claude plugin marketplace add` and
  `claude plugin install` shell commands (run outside a Claude
  Code session) over the unreliable `/plugin` slash commands,
  and drop the non-existent `claude plugin add --local`
  subcommand from the local-development path

## 0.65.0 — Hook Performance & Control

Released 2026-04-19

### Features

- **Shorten session startup by consolidating hooks** —
  SessionStart now runs 5 features in one orchestrator (Stop
  runs 2), replacing 8 `uv run --project` wrappers with
  direct-shebang scripts so every session feels faster without
  paying uv project resolution and CLI import cost per hook
  ([GH-959](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/959))
- **Surface per-hook execution timing for latency triage** —
  `@audit_hook` plus an `audit-wrap` shell wrapper capture
  body-phase and total (including uv startup) timing per
  invocation to `/tmp/Dev10x/logs/hooks-*.jsonl`, with
  `dev10x hook audit summary` and `prune` subcommands so slow
  hooks are diagnosable before users complain ([GH-860](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/860))
- **Let users dial hook strictness per session** — validator
  specs now carry `rule_id` (DX001–DX008), `profile`
  (minimal/standard/strict), and `experimental` flags, so
  `DEV10X_HOOK_PROFILE`, `DEV10X_HOOK_DISABLE`, and
  `DEV10X_HOOK_EXPERIMENTAL` can drop opinionated rules for
  throwaway work while keeping safety-critical guardrails on
  shared-repo commits ([GH-413](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/413))
- **Guide users to reconnect MCP instead of bypassing hook** —
  when the `Dev10x_cli` MCP server is unavailable, use-tool
  block messages now instruct the agent to ask the user to
  reconnect rather than fall back to wrapper scripts or reach
  for `DEV10X_SKIP_CMD_VALIDATION`, which users reject for
  transient outages ([GH-957](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/957))

## 0.64.0 — Platform Reach & Merge Safety

Released 2026-04-18

### Features

- **Support multi-platform installs via unified CLI** — register
  any AI assistant (Claude Code, Copilot, Windsurf, Continue,
  Cursor, or custom targets) with `dev10x platform add/list/remove`
  so Dev10x can extend beyond its original two-host scope without
  per-user path editing ([GH-908](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/908))
- **Automate PyPI publishing on release tags** — `v*` tag pushes
  publish the `dev10x` package via OIDC trusted publishing, so
  users can `pip install Dev10x` for CI scripts and hook
  integration without manual upload steps ([GH-953](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/953))
- **Guide new users through Dev10x onboarding** — `dev10x init`
  seeds starter config and prints a Next 5 Commands quick-start
  card, replacing the zero-direction `/help` landing with a
  frictionless guided setup ([GH-906](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/906))
- **Prevent silent merges past unresolved CI checks** —
  `Dev10x:gh-pr-merge` now blocks on `PENDING`, `IN_PROGRESS`, or
  any `bucket:fail` state and requires an explicit reason for
  override, closing the gap that shipped a bundle while e2e was
  still running ([GH-955](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/955))
- **Enforce instruction budget for large skills** — new
  `dev10x skill count-instructions` command measures actionable
  instructions and warns when skills exceed the 150-instruction
  reliability threshold from QRSPI research ([GH-882](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/882))
- **Offer structured retry after rejected commands** — when a
  user rejects a CLI command, `Dev10x:skill-reinforcement` now
  fires `AskUserQuestion` with retry/manual/cancel options
  instead of a plain-text follow-up that could silently auto-
  advance ([GH-952](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/952))
- **Prefer bundled PR for same-milestone multi-issue work** —
  `Dev10x:work-on` auto-selects a bundled PR strategy when all
  tickets share a milestone under solo-maintainer mode, cutting
  N branch switches, CI cycles, and merges down to one
  ([GH-948](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/948))
- **Enable MCP glob enumeration in upgrade-cleanup** — new
  `dev10x permission enumerate-mcp` subcommand replaces
  `mcp__plugin_Dev10x_*` wildcards with enumerated tool names,
  eliminating the manual approval prompts Claude Code fires when
  globs silently match nothing ([GH-947](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/947))
- **Enable Supabase env bootstrap in worktree hooks** — post-
  checkout hooks now copy `.env.supabase` into new worktrees so
  local Supabase connectivity works without manual file copying
  ([GH-946](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/946))

### Refactors

- **Isolate Dev10x scratch files under /tmp/Dev10x/** — plugin
  scratch files, session state, and the mktmp binary moved from
  the shared `/tmp/claude/` namespace to `/tmp/Dev10x/`, letting
  users scope allow rules to plugin-only paths ([GH-949](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/949))

### Chores

- **Keep scheduled_tasks.lock out of version control** — the
  session-local scheduler lock file is now gitignored so it
  cannot land alongside unrelated skill changes ([GH-955](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/955))

## 0.63.0 — Solo Shipping & Playbook Resilience

Released 2026-04-15

### Features

- **Enable auto-merge in solo-maintainer shipping pipeline** —
  solo maintainers no longer need to manually merge every PR;
  the shipping pipeline now includes a conditional merge step
  ([GH-940](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/940))
- **Enable playbook schema version tracking** — playbook files
  include a version field bumped automatically on release so
  drift between skills and core plugin is detectable ([GH-910](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/910))
- **Enable decision-aware session resume guidance** — resumed
  sessions surface pending decisions from task metadata and
  inject friction-level guidance so agents re-ask or
  auto-advance correctly ([GH-934](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/934))

### Fixes

- **Prevent non-functional MCP wildcards from masking
  permissions** — upgrade cleanup detects and removes top-level
  MCP wildcard patterns that Claude Code ignores at runtime,
  preventing false coverage from hiding missing tool entries
  ([GH-943](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/943), [GH-942](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/942))
- **Prevent fragment shadowing from dropping skills** — user
  playbook fragments that shadow defaults now inherit skills,
  agent, model, and modes fields instead of silently dropping
  them ([GH-938](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/938))
- **Prevent ACC review-requested from failing solo mode** —
  review-requested checks are skipped in solo-maintainer mode
  where no reviewers are ever assigned ([GH-939](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/939))
- **Resolve upgrade-cleanup broken script flags** — MCP tool
  routes ensure-base, generalize, and ensure-scripts to Python
  functions directly instead of passing invalid CLI flags
  ([GH-936](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/936))

### Refactors

- **Simplify onboarding skill with reference redirect** —
  extracted tour content to a references file, reducing
  SKILL.md from 202 to ~40 lines ([GH-897](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/897))

### Docs

- **Document CLI startup performance baseline** — baseline
  metrics and monitoring instructions for regression tracking
  ([GH-907](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/907))
- **Clarify tier 2 path after old projects/ removal** — config
  resolution docs updated to reflect the canonical
  `~/.claude/memory/Dev10x/` path ([GH-941](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/941))
- **Update gitignore for backup settings files** — settings
  backup files are now excluded from version control

## 0.62.0 — Issue Milestones & Permission Safety

Released 2026-04-14

### Features

- **Enable milestone assignment on issue creation** — ticket-create
  skill assigns milestones when specified, keeping project tracking
  aligned from the start ([GH-926](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/926))
- **Enable rollback for upgrade-cleanup bulk edits** — bulk settings
  modifications create timestamped backups so changes can be reverted
  if something goes wrong ([GH-921](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/921))
- **Enable CLI access to permission scripts** — permission audit and
  cleanup scripts are accessible from the dev10x CLI entry point
  ([GH-924](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/924))

### Fixes

- **Prevent wildcard rules from stripping permissions** — upgrade
  cleanup no longer removes valid allow rules when wildcard patterns
  overlap with specific entries ([GH-922](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/922))
- **Strengthen recurring audit finding guards** — audit-report skill
  checks for duplicate findings before filing, preventing redundant
  GitHub issues ([GH-928](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/928))

### Docs

- **Improve README with cover image and badges** — README now leads
  with marketplace badge, version badge, and a cover image for better
  first impressions

## 0.61.0 — Permission Diagnostics & Skill Refinements

Released 2026-04-14

### Features

- **Surface permission-denied diagnostics** — hooks detect blocked
  tool calls and provide actionable guidance on missing allow rules
  or hook configuration ([GH-918](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/918))
- **Improve upgrade-cleanup audit reporting** — upgrade-cleanup
  produces structured, severity-categorized findings instead of
  flat text output ([GH-914](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/914))
- **Enable direct review thread resolution** — gh-pr-respond can
  resolve review threads directly after posting fixup commits,
  reducing round-trips ([GH-902](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/902))

### Fixes

- **Stabilize uv dep resolution test assertion** — fix flaky test
  that depended on exact pip resolver output ordering ([GH-913](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/913))

### Tests

- **Validate uv shebang script dependencies** — new test ensures
  all PEP 723 inline-metadata scripts declare valid, resolvable
  dependencies ([GH-913](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/913))

### Docs & Skills

- **Persist session state across context resets** — session-stop
  hook preserves branch, plan, and task state so resumed sessions
  recover context automatically ([GH-917](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/917))
- **Detect architecture violations in PR review** — review skill
  checks for Clean Architecture boundary crossings ([GH-916](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/916))
- **Ensure monitor fallback on permission failure** — PR monitor
  retries with reduced permissions instead of failing silently
  ([GH-901](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/901))
- **Support natural-language input in work-on** — work-on accepts
  free-text task descriptions alongside ticket URLs ([GH-886](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/886))
- **Prefer vertical slice decomposition in scope** — scope skill
  favors feature slices over horizontal layer splits ([GH-885](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/885))
- **Monitor context fill at phase boundaries** — work-on tracks
  context window usage and warns before overflow ([GH-884](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/884))
- **Surface design analysis as a review gate** — scope skill
  requires design review before implementation begins ([GH-883](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/883))
- **Prevent confirmation bias with blind research** — brainstorming
  skill gathers evidence before presenting options ([GH-881](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/881))
- **Enable skill instruction count tracking** — skill-index reports
  instruction line counts for budget monitoring ([GH-877](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/877))
- **Resolve hook error handling standardization** — align hook exit
  codes and error messages across Python and shell ([GH-826](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/826))
- **Resolve milestone findings** — address M3–M6 architecture,
  pattern adoption, test coverage, and cross-cutting consistency
  findings ([GH-811](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/811), [GH-812](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/812), [GH-813](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/813), [GH-814](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/814))

## 0.60.0 — Multi-Issue Bundling & Audit Clarity

Released 2026-04-13

### Features

- **Bundle multiple issues in work-on** — work-on skill accepts
  multiple ticket URLs or IDs in a single invocation, gathering
  context in parallel and building a unified task list ([GH-868](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/868))
- **Separate audit detection from solution design** — permission
  auditor splits finding identification from fix proposals so
  users review problems before seeing solutions ([GH-904](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/904))

### Fixes

- **Restore MCP server dependencies** — re-add yaml and msgpack
  dependencies removed during consolidation so MCP servers start
  without import errors ([GH-911](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/911))
- **Enforce PR reference update after groom force-push** — groom
  skill now updates the PR head ref after force-pushing rebased
  commits, preventing stale SHA references ([GH-900](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/900))
- **Prevent misleading completion messages in fixup** — fixup
  skill no longer reports success when the underlying commit
  was not created ([GH-899](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/899))
- **Prevent wildcard allow-rule proposals in audit** — permission
  auditor blocks overly broad glob patterns that would bypass
  security boundaries ([GH-903](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/903))

### Docs

- **Clarify gh-pr-respond as PR comment entry point** — update
  skill description to direct users to gh-pr-respond instead
  of gh-pr-fixup for handling review comments ([GH-898](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/898))

## 0.59.0 — Permission Automation & Review Intelligence

Released 2026-04-13

### Features

- **Auto-detect semantic-release config** — release-notes skill
  now discovers project-specific ticket patterns and output
  targets without manual configuration ([GH-585](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/585))
- **Auto-groom fixup commits in CI** — PR monitor detects
  fixup! commits and triggers automatic interactive rebase
  before merge readiness ([GH-869](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/869))
- **Pre-approve temp file and MCP permissions** — new permission
  namespaces eliminate approval prompts for temp files, plugin
  scripts, MCP tools, and git aliases ([GH-878](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/878))
- **Simplify code after review** — post-review pipeline step
  scans changed files for reuse and quality improvements
  ([GH-874](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/874))
- **Filter review findings by confidence** — review skill drops
  low-confidence findings to reduce noise in PR comments
  ([GH-872](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/872))
- **Detect silent failures in reviews** — new reviewer agent
  catches swallowed exceptions and missing error logging
  ([GH-873](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/873))
- **Verify plugin script coverage** — pre-PR check ensures all
  plugin scripts referenced in skills have test coverage
  ([GH-876](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/876))
- **Invoke scripts via MCP instead of paths** — MCP server
  wraps plugin scripts so skills avoid path-dependent Bash
  allow rules ([GH-807](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/807))
- **Persist upgrade-cleanup config** — cleanup preferences
  survive across sessions via YAML settings file ([GH-862](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/862))

### Improvements

- **Extensible PR comment action dispatch** — comment handler
  uses registry pattern for adding new reply actions ([GH-827](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/827))
- **Self-formatting session state objects** — state dataclasses
  render their own display strings, removing format duplication
  ([GH-820](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/820), [GH-823](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/823))
- **Canonical rule evaluation via RuleEngine** — single
  evaluation path replaces scattered rule-checking code
  ([GH-818](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/818))
- **Single-source YAML rule parsing** — rule definitions load
  from YAML instead of duplicated Python dicts ([GH-822](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/822))
- **Path-independent plan context updates** — plan sync works
  from any working directory without hardcoded paths ([GH-802](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/802))
- **Type-safe MCP tool returns** — MCP tools return typed dicts
  instead of raw strings, catching schema mismatches early
  ([GH-819](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/819))
- **Validated repository references** — repo URL construction
  uses validated objects instead of string concatenation
  ([GH-821](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/821))

### Fixes

- **Prevent shipping pipeline skill regressions** — pin
  eval assertions that caught behavioral drift in PR create,
  groom, and merge skills ([GH-851](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/851))
- **Block fanout completion before monitors finish** — gate
  now waits for all background PR monitors before advancing
  ([GH-859](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/859))
- **Fix plugin cache lookup after repo rename** — cache key
  derivation uses canonical repo name, not stale path
  ([GH-861](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/861))
- **Detect stale plugin paths with different casing** — path
  comparison is now case-insensitive on case-folding
  filesystems ([GH-864](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/864))

### Tests

- **MCP GitHub tool coverage** — add unit tests for PR detect,
  issue get, and comment reply MCP tools ([GH-825](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/825))
- **Domain module regression safety** — add integration tests
  for core domain module imports and wiring ([GH-824](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/824))

## 0.58.0 — Session Safety & Config Hygiene

Released 2026-04-09

### Features

- **Surface background agent progress in caller** — add
  caller-side task tracking for background monitor agents so
  supervisors see in-progress work instead of an idle session
  ([GH-854](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/854))
- **Prevent auditing wrong session via gate** — skill-audit
  now confirms resolved session identity before proceeding,
  blocking silent fallback to alternate path encodings
  ([GH-805](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/805))

### Improvements

- **Normalize config paths to canonical locations** — remove
  deprecated Tier 3 path references from 16 skills, consolidate
  bare memory configs under Dev10x/ subdirectory, and align
  config-resolution docs with actual resolution order ([GH-849](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/849))

### Fixes

- **Preserve git alias rules from cleanup** — permission
  maintenance no longer removes git alias allow rules that
  worktree sessions depend on for branch-switching and commit
  grooming ([GH-852](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/852), [GH-853](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/853))
- **Prevent session.yaml overwrite of active modes** — Phase 0
  now reads before writing, preserving existing active_modes
  instead of overwriting with empty defaults ([GH-846](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/846))

## 0.57.0 — Plugin Naming Consistency

Released 2026-04-09

### Improvements

- **Update plugin naming for Dev10x consistency** — align
  plugin.json and marketplace.json name fields to "Dev10x"

## 0.56.0 — Concurrency Safety & Context Efficiency

Released 2026-04-09

### New Skills

- **Enable parallel fanout experimentation** — dispatch
  worktree-isolated agents in parallel to validate newer
  Claude Code capability assumptions ([GH-781](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/781))
- **Allow maintenance commits to bypass JTBD** — configurable
  bypass gitmoji set lets changelog/version-bump commits skip
  outcome-focused title enforcement ([GH-797](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/797))

### Improvements

- **Delegate tracker CRUD to background agents** — project-scope
  and ticket-create offload Linear/GitHub API calls to a haiku
  agent, returning compact summaries instead of dumping 26k token
  API responses into context ([GH-842](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/842))
- **Unblock MCP event loop from subprocess calls** — convert all
  MCP tool handlers to async using asyncio subprocess, eliminating
  up to 60s blocking during shell execution ([GH-815](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/815))
- **Enable batch thread resolution in PR comments** — resolve
  all review threads in two GraphQL calls instead of O(2N)
  sequential calls, avoiding rate limits in large PRs ([GH-828](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/828))
- **Surface lesson-learned guidance from stale PRs** — extract
  orchestration anti-patterns, test-pattern checks, and hook
  state documentation from 5 stale draft PRs into rules

### Fixes

- **Enforce named parameter Skill() syntax** — fix positional
  Skill() calls in ticket-create and ticket-jtbd that caused
  agent misrouting ([GH-804](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/804))
- **Enforce PR comment resolution in fanout** — Phase 5 now
  blocks completion until all PR review comments are resolved;
  per-item check added in Phase 3 ([GH-829](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/829))
- **Prevent plan gate skip at adaptive friction** — clarify
  that auto-select means execute the recommended option, not
  skip the approval gate entirely ([GH-808](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/808))
- **Enable portable plugin path in pr-monitor** — replace
  hardcoded versioned path with ${CLAUDE_PLUGIN_ROOT} variable
  ([GH-806](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/806))
- **Prevent session state race between sessions** — atomic
  os.rename() claim prevents two concurrent sessions from
  reading and deleting the same state file ([GH-816](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/816))

### Security

- **Protect settings.json from concurrent writes** — introduce
  fcntl advisory locking with atomic write-then-rename so
  concurrent sessions cannot overwrite each other's changes
  ([GH-817](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/817))

### Breaking Changes

- **Isolate codex port to separate repo** — remove codex-skills/
  directory (45 skill ports), codex install/validate scripts,
  and docs/codex.md ([GH-678](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/678))
- **Unify documentation under docs/ directory** — ADRs moved
  from doc/adr/ to docs/adr/; update any external links or
  scripts referencing the old path ([GH-838](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/838))

## 0.55.0 — Merge Safety & Skill Guardrails

Released 2026-04-08

### Features

- **Resolve skill-audit findings across 5 skills** — address
  accumulated audit findings for improved compliance ([GH-760](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/760))
- **Preserve fixup commit links after grooming** — groom no
  longer drops fixup commit references from PR threads ([GH-777](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/777))
- **Strengthen skill delegation guardrails** — prevent agents
  from bypassing skill orchestration contracts ([GH-759](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/759))
- **Prevent undetected cd+git chaining** — hook now catches
  cd-then-git patterns that break allow rules ([GH-763](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/763))
- **Prevent false positives on skill-required rules** — permission
  auditor no longer flags rules that skills actively need ([GH-790](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/790))
- **Enable publisher rename in permission paths** — update-paths
  handles publisher directory renames correctly ([GH-791](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/791))

### Refactoring

- **Enable single-source hook implementations** — consolidate
  12 standalone hook scripts into dev10x CLI subcommands ([GH-748](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/748))

### Fixes

- **Prevent false green on draft-to-ready** — CI monitor now
  re-checks status after PR transitions from draft ([GH-774](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/774))
- **Prevent orchestrator from pre-empting groom** — merge skill
  waits for groom completion before proceeding ([GH-776](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/776))
- **Prevent inline CI polling in merge skill** — delegates
  polling to monitor agent instead of inline loops ([GH-775](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/775))
- **Prevent merge failure in worktree setups** — gh pr merge
  now uses --repo flag in worktree contexts ([GH-773](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/773))
- **Prevent CI check cascade failure** — handle partial check
  results without aborting the entire merge flow ([GH-772](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/772))

## 0.54.0 — Hook Consolidation & Lazy Imports

Released 2026-04-08

### Features

- **Enable SessionStart hooks via dev10x hook session** — unified
  hook entry point for session startup ([GH-741](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/741))
- **Enable SessionStop hooks via dev10x hook session** — unified
  hook entry point for session teardown ([GH-742](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/742))
- **Enable Skill and PostToolUse hooks via dev10x hook** — unified
  hook entry point for tool-use lifecycle ([GH-743](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/743))
- **Centralize config into ~/.claude/memory/Dev10x** — single
  location for all plugin configuration ([GH-726](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/726))

### Performance

- **Defer heavy imports to command invocation** — lazy-load
  expensive modules to reduce CLI startup time ([GH-746](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/746))

### Refactoring

- **Enable cli_server as thin uv shim** — reduce server startup
  overhead with lightweight wrapper ([GH-744](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/744))
- **Enable db_server as thin uv shim** — reduce server startup
  overhead with lightweight wrapper ([GH-745](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/745))

### Fixes

- **Resolve hook failures on systems without PyYAML** — graceful
  fallback when optional dependency is missing ([GH-766](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/766))
- **Prevent false positive on explicit JSONL path** — path
  validation no longer flags valid JSONL files ([GH-762](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/762))

### Documentation

- **Clarify glob pattern syntax in config-resolution** — improve
  examples for file matching patterns ([GH-757](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/757))

### Tests

- **Enable CLI startup time benchmarking** — measure and track
  startup performance regressions ([GH-749](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/749))
- **Enable server tests to measure mcp package coverage** —
  expanded test coverage for MCP servers ([GH-745](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/745))

## 0.52.0 — Marketplace & Repo Migration

Released 2026-04-07

### Refactoring

- **Standardize JSON format for marketplace name** — align
  marketplace.json naming convention to hyphenated format
  (Dev10x-Guru)

## 0.51.0 — Repository Migration

Released 2026-04-07

### Infrastructure

- **Migrate repo references to Dev10x-Guru/dev10x-claude** —
  update all installation instructions, plugin manifests, code
  paths, tests, and documentation to reflect the new repository
  location

## 0.50.0 — Fanout Safety & CI Overrides

Released 2026-04-07

### Features

- **Allow user override for infrastructure CI failures** — users
  can bypass infrastructure-only CI failures when appropriate
  ([GH-730](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/730))

### Fixes

- **Enforce fanout audit, monitor, and fixup safety** — fanout
  skill validates audit completion, monitors, and fixup commits
  before proceeding ([GH-724](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/724))
- **Enforce Check 1b in gh-pr-merge** — merge gate validates
  all required checks before allowing merge ([GH-728](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/728))
- **Prevent play step collapsing in work-on** — work-on skill
  preserves individual play steps during execution ([GH-729](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/729))
- **Prevent CI actions from running on merged PRs** — CI
  workflows skip already-merged pull requests ([GH-721](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/721))

### Tooling

- **Enable direct invocation of entry-point scripts** — scripts
  can be called directly without wrapper commands ([GH-732](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/732))
- **Update partner name in marketplace configuration** — align
  marketplace metadata with current branding

### Tests

- **Prevent script permission regressions** — test coverage for
  script file permissions ([GH-731](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/731))

## 0.49.0 — Cross-Context Auditing & Review Coverage

Released 2026-04-06

### Features

- **Ensure reviewers flag new classes without tests** — code
  review agents detect untested new classes ([GH-704](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/704))
- **Enable cross-context query detection in audits** — skill
  audit detects queries spanning multiple contexts ([GH-713](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/713))

### Fixes

- **Resolve plugin install failure from invalid key** — fix
  invalid configuration key blocking plugin installation
  ([GH-723](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/723))
- **Align phase selection spec with Phase I addition** — phase
  selection matches updated phase definitions ([GH-713](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/713))
- **Resolve batch review findings from 6 PRs** — address
  accumulated review findings across multiple PRs ([GH-709](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/709))

### Documentation

- **Document merge_mode and merge_strategy config** — add
  configuration reference for merge behavior options ([GH-707](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/707))
- **Clarify reference file discoverability and template
  guidance** — improve documentation for reference files

## 0.48.0 — Playbook Modes & Merge Safety

Released 2026-04-05

### Features

- **Per-step modes and friction in playbooks** — playbook steps
  can declare execution modes and friction levels independently
  ([GH-712](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/712))

### Fixes

- **Ensure acceptance criteria run before merge** — acceptance
  criteria checks execute before merge gate proceeds ([GH-711](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/711))

## 0.47.0 — Skill Reinforcement & Merge Safety

Released 2026-04-05

### Features

- **PermissionDenied hook corrections** — hooks detect and
  correct permission-denied errors with targeted guidance
  ([GH-705](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/705))
- **Merged PR audit for unaddressed findings** — surface
  unresolved review threads after merge ([GH-699](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/699))
- **Autonomous merge cascade in AFK mode** — unattended
  merge pipelines complete without manual intervention
  ([GH-688](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/688))
- **Session friction level prompt** — prompt users to select
  friction level at session start ([GH-689](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/689))
- **Comprehensive architecture auditing** — architecture
  advisor covers broader design evaluation ([GH-687](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/687))

### Fixes

- **Prevent merging with unaddressed review comments** —
  merge gate blocks when review threads remain open
  ([GH-698](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/698))
- **Prevent false positive on uv shebang hooks** — rule
  engine skips uv shebang lines in script validation
  ([GH-705](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/705))
- **Enable background CI monitor to poll autonomously** —
  CI monitor runs without blocking the session ([GH-695](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/695))
- **Resolve unaddressed PR #691 review findings** — fix
  outstanding review comments from prior PR ([GH-697](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/697))
- **Resolve circular import in rule_engine** — break import
  cycle in Python package structure ([GH-681](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/681))
- **Resolve fanout audit findings** — address audit issues
  in parallel work stream orchestrator ([GH-693](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/693))

### Refactoring

- **Rule-engine commit allowlist** — allowlist-based commit
  validation replaces ad-hoc checks ([GH-705](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/705))
- **Global skill-reinforcement overrides** — skill redirect
  rules configurable at global scope ([GH-705](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/705))

### Tests

- **Ensure Python entry point loadability** — verify all
  CLI entry points import without error ([GH-681](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/681))
- **Ensure Python script entry point loadability** — extend
  entry point tests to skill scripts ([GH-681](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/681))

## 0.46.0 — Architecture Consolidation & Performance

Released 2026-04-04

### Features

- **Unified Python package structure** — all validators, hooks,
  and CLI tools consolidated into `src/dev10x/` package with
  lazy-loading entry point ([GH-588](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/588), [GH-589](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/589))
- **RuleEngine for unified rule evaluation** — single engine
  replaces per-validator rule dispatch ([GH-644](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/644))
- **Typed config loading via Protocol** — config system uses
  Protocol-based contracts for type safety ([GH-650](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/650))
- **Friction-level tiered enforcement** — skill redirect hooks
  support configurable friction levels per command ([GH-530](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/530))
- **Executable acceptance criteria checks** — verify
  definition-of-done criteria programmatically ([GH-640](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/640))
- **Structured decision widgets** — AskUserQuestion gates use
  rich option widgets instead of plain text ([GH-636](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/636))
- **Pre-merge validation gate** — blocking check before merge
  ensures CI and review requirements are met ([GH-635](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/635))
- **On-demand PR review audits** — trigger review audits
  outside the normal PR lifecycle ([GH-551](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/551))
- **Configurable protected branch lists** — per-project
  protected branches without hardcoding ([GH-578](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/578))
- **Permission-aware dispatch in fanout** — parallel work
  streams respect permission boundaries ([GH-562](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/562))
- **Project-level commit gitmoji mapping** — projects can
  override default gitmoji conventions ([GH-585](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/585))
- **Groom skill conflict resolution** — interactive rebase
  handles merge conflicts gracefully ([GH-625](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/625))

### Performance

- **msgpack-cached config loading** — config reads use msgpack
  cache, reducing hook latency ([GH-591](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/591), [GH-652](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/652), [GH-653](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/653))
- **Lazy validator imports** — validators load only when
  needed, cutting startup time ([GH-654](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/654))
- **Startup time regression tests** — benchmark suite prevents
  hook performance regressions ([GH-656](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/656), [GH-657](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/657), [GH-658](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/658))

### Refactoring

- **Domain-driven validator architecture** — validators use
  Protocol conformance, shared GitContext, and reusable domain
  value objects ([GH-648](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/648), [GH-649](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/649), [GH-651](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/651))
- **Unified Rule/Config across all validators** — single Rule
  and Config types replace per-validator duplicates ([GH-645](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/645))
- **Single SQL validation source** — SQL checks consolidated
  into one module ([GH-647](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/647))
- **Domain-driven plan persistence** — plan storage uses
  domain models instead of raw file I/O ([GH-646](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/646))
- **Tell Don't Ask on EditRule** — EditRule encapsulates its
  own decision logic ([GH-643](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/643))
- **First-class skill script packages** — skill scripts are
  proper Python packages with imports ([GH-604](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/604))
- **Isolated tool modules** — Git, GitHub, and utility tools
  split into focused modules ([GH-600](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/600), [GH-601](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/601))
- **Python-based session hook dispatch** — session hooks
  migrate from shell to Python ([GH-598](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/598))
- **CLI-based validators** — Edit/Write and Bash validation
  use Click CLI commands ([GH-594](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/594), [GH-596](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/596), [GH-597](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/597))
- **Unified test directory** — all tests under `tests/`
  mirroring `src/` structure ([GH-595](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/595), [GH-607](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/607))
- **Deterministic test data via fakers** — factory-based
  test data generation ([GH-592](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/592))
- **Deprecated hook scripts removed** — old shell shims
  cleaned up ([GH-610](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/610))

### Fixes

- **Resolve macOS bash 3.2 hook errors** — hooks now work
  on macOS default bash ([GH-661](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/661))
- **Resolve permission-maintenance noise filter gaps** —
  false positive noise in permission audits ([GH-579](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/579))

### Docs

- **Reflect new src/ and tests/ layout** — documentation
  updated to match consolidated structure ([GH-611](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/611))
- **Document TOML vs YAML benchmark decision** — ADR for
  config format choice ([GH-655](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/655))
- **Showcase orchestration and planning in README** —
  feature highlights for new users
- **Coverage reporting in pytest runs** — test output
  includes coverage data ([GH-608](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/608))

### Tests

- **End-to-end validation of refactored plugin** — full
  plugin integration test suite ([GH-612](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/612))
- **Regex compilation benchmarking** — benchmark suite for
  compiled regex patterns ([GH-657](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/657))
- **Hook performance benchmarking** — pytest-benchmark
  integration for hook validators ([GH-656](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/656))

## 0.45.0 — CI Safety & Hook Config

Released 2026-04-01

### Features

- **CI merge-conflict detection** — CI pipeline now detects
  merge conflicts before allowing PR progression ([GH-563](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/563))
- **Safe deterministic transcript analysis** — enable
  transcript analysis with reproducible, safe parsing ([GH-565](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/565))

### Improvements

- **Config-driven hook validation** — all hooks use YAML-driven
  validation instead of hardcoded patterns ([GH-572](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/572))
- **Clarify memory path conventions** — db skill documents
  correct memory file path patterns ([GH-567](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/567))

### Fixes

- **Prevent PR ready with unaddressed findings** — PR cannot
  be marked ready when body-level findings remain ([GH-564](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/564))
- **Detect quoted paths in cd/git-C checks** — noop detection
  handles quoted directory paths correctly ([GH-568](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/568))
- **Remove unused CD_PREFIX_RE pattern** — dead regex cleanup

### Tests

- **Hook rule validation coverage** — ensure allow rules
  permit legitimate skill command invocations ([GH-572](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/572))

## 0.44.0 — MCP Expansion & Hook Hardening

Released 2026-03-31

### Features

- **MCP redirect for gh issue create** — issue creation routes
  through MCP tool instead of raw CLI ([GH-552](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/552))

### Improvements

- **Block direct git-push-safe invocation** — prevent users from
  calling push-safe directly via CLI, redirect to skill wrapper
  with safety guards ([GH-560](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/560))

### Fixes

- **Prevent monitor green during CI run** — monitor no longer
  reports premature success before CI completion ([GH-553](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/553))
- **Unblock commit from non-mktmp temp files** — allow commits
  from temporary files created outside mktmp system ([GH-554](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/554))

## 0.43.0 — Skill Ecosystem & Compliance Hardening

Released 2026-03-30

### Features

- **Competitive multi-agent design exploration** — ADR evaluation
  dispatches domain-specific architect agents in parallel for
  adversarial trade-off analysis ([GH-483](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/483))
- **YAML-driven skill redirect with friction levels** — PreToolUse
  hooks intercept raw CLI commands and redirect to skill wrappers
  with configurable friction ([GH-418](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/418))
- **Automated security review of changes** — reviewer-security
  agent scans diffs for OWASP vulnerabilities and hardcoded
  secrets ([GH-490](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/490))
- **CI-enforced test coverage for servers** — MCP server Python
  code now requires pytest coverage in CI ([GH-493](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/493))
- **Guided discovery for new users** — onboarding skill index
  and MOTD help new users find relevant skills ([GH-488](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/488))
- **Context window optimization** — systematic compaction
  patterns reduce token usage in long sessions ([GH-489](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/489))
- **Per-project model selection for dispatch** — playbook steps
  can override agent model tier per project ([GH-491](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/491))
- **Skill reinforcement for missing commands** — agent detects
  raw CLI usage and redirects to proper skills ([GH-506](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/506))
- **Proactive skill-audit triggers** — audit phase fires
  automatically when session processes 3+ items ([GH-537](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/537))
- **MCP redirect for gh issue view** — issue fetching routes
  through MCP tool instead of raw CLI ([GH-539](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/539))
- **Harden gh-pr-create skill compliance** — PR creation
  enforces all delegation and formatting rules ([GH-533](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/533))

### Improvements

- **Standardize tracker detection via MCP tool** — all skills
  use `detect_tracker` MCP call instead of script ([GH-507](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/507))
- **Reduce scoping wall-clock time** — background exploration
  agents parallelize codebase analysis ([GH-485](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/485))
- **Standardize skill trigger suffixes** — consistent TRIGGER/
  DO NOT TRIGGER patterns across all skills ([GH-484](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/484))
- **Enable standalone invocation of pipeline steps** — skills
  in pipelines can run independently ([GH-487](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/487))
- **Prefer MCP tool for PR context detection** — gh-context
  routes through MCP by default ([GH-534](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/534))
- **Allow inline synthesis when context suffices** — JTBD
  drafting skips full skill when session has rich context
  ([GH-536](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/536))
- **Establish canonical eval schema** — standardized JSON
  format for skill evaluation assertions ([GH-515](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/515))
- **Clarify decision gate assertion naming** — eval patterns
  use consistent signal names ([GH-488](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/488))
- **Prevent uv.lock drift after version bumps** — lock file
  stays in sync with pyproject.toml ([9630a11])

### Bug Fixes

- **Harden fanout and git skill guardrails** — Phase 5 checks
  PR comments, issues use sequential Skill(), MCP push_safe
  promoted, bypassPermissions documented ([GH-549](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/549))
- **Enforce test skill delegation in routing** — test step
  routes through skill wrapper, not raw pytest ([GH-504](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/504))
- **Enforce skill-create delegation in routing** — skill
  creation uses proper skill, not inline logic ([GH-503](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/503))
- **Prevent skill-audit from targeting current session** —
  audit dispatches to separate session context ([GH-508](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/508))
- **Resolve 3 complex skill-audit findings** — mixed
  compliance gaps in multiple skills ([d88ef81])
- **Self-healing for wrong mktmp namespace** — mktmp
  auto-corrects misrouted temp files ([d0acaf4])
- **Block cd+rev-parse chaining in hooks** — PreToolUse
  hook catches compound commands ([GH-528](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/528))
- **Prevent inline audit summary deviation** — audit
  results use structured output, not free text ([GH-531](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/531))
- **Mandate mktmp for commit message temp files** — commit
  skill always uses mktmp for collision-free paths ([GH-532](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/532))
- **Harden scope skill review compliance** — scope skill
  follows all review checklist items ([GH-485](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/485))
- **Resolve checklist numbering conflict** — PR body
  checklist renders correctly ([GH-486](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/486))

### Security

- **Enforce SKILL.md size discipline in reviewer** — reviewer
  flags skills exceeding line budgets ([GH-486](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/486))

### Documentation

- **Surface skill-pipelines in rule index** — pipeline
  composition patterns documented in INDEX.md ([GH-487](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/487))
- **Prevent MCP tool names used as CLI commands** — docs
  clarify MCP names are tool-call primitives only ([GH-535](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/535))
- **Enable prospective users to evaluate Dev10x** — public
  evaluation guide for potential adopters ([GH-492](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/492))

### CI

- **Tighten git commit -F allow pattern** — CI allow rules
  match the mktmp-based commit flow ([GH-418](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/418))

[9630a11]: https://github.com/Dev10x-Guru/dev10x-claude/commit/9630a11
[d88ef81]: https://github.com/Dev10x-Guru/dev10x-claude/commit/d88ef81
[d0acaf4]: https://github.com/Dev10x-Guru/dev10x-claude/commit/d0acaf4

## 0.42.0 — Plan Persistence & Audit Compliance

Released 2026-03-28

### Features

- **Persistent plan tracking across compaction** — task plans
  survive context window compaction via file-backed state
  ([GH-482](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/482))

### Bug Fixes

- **Resolve skill-audit TaskCreate validation failures** —
  audit skill handles missing task fields gracefully ([GH-496](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/496))
- **Ensure audit-report delegates to ticket-create** — report
  filing routes through proper skill wrapper ([GH-498](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/498))
- **Resolve script allow-rule permission friction** — script
  paths match updated plugin directory layout ([GH-499](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/499))
- **Prevent premature merge from SKIPPING checks** — CI
  monitor excludes SKIPPING from pass count ([GH-501](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/501))
- **Prevent inline triage bypass in gh-pr-respond** — all
  comments route through triage before fixup ([GH-502](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/502))
- **Prevent groom step bypass via self-assessment** — groom
  skill always presents strategy gate ([GH-505](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/505))

## 0.41.0 — Orchestration Guardrails & Plan Persistence

Released 2026-03-27

### Features

- **Per-skill model selection for agents** — agent specs and
  skill dispatch choose model tier based on task complexity
  ([GH-470](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/470))
- **Harden work-on orchestration guardrails** — skill routing
  enforcement table survives context compaction ([GH-477](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/477))
- **Plan persistence across compaction** — plans backed by
  files survive context window resets ([GH-414](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/414))

### Improvements

- **Clarify skill docs for nested mode and push** — nested
  invocation exemptions and push safety documented ([GH-475](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/475))

### Bug Fixes

- **Prevent marking PR ready with unaddressed comments** —
  post-CI comment re-check catches late bot reviews ([GH-465](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/465))

### Security

- **Enforce git-commit skill via PreToolUse hook** — raw
  `git commit` blocked; must use Dev10x:git-commit ([GH-473](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/473))

### Tests

- **Ensure dispatcher tests match commit hook rules** —
  test suite validates hook-to-skill routing ([GH-473](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/473))

## 0.40.0 — Delegation Hardening & Fixup Skill Gaps

Released 2026-03-26

### Features

- **Frictionless issue creation from skills** — skills can now
  create GitHub issues without approval prompts ([GH-445](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/445))
- **Strengthen delegation bypass prevention** — skills enforce
  proper delegation chains instead of raw CLI calls ([GH-458](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/458))
- **Resolve gh-pr-fixup skill gaps** — fixup skill now handles
  all edge cases surfaced by audit ([GH-459](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/459))

### Improvements

- **Harden work-on skill against audit regressions** — work-on
  orchestration no longer drifts when audit findings change
  ([GH-448](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/448))
- **Prevent raw command bypass in PR creation** — PR creation
  enforces skill delegation instead of raw `gh pr create`
  ([GH-448](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/448))
- **Prevent delegation bypass in gh-pr-respond** — response skill
  enforces proper triage-then-fixup pipeline ([GH-447](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/447))
- **Prevent premature CI exit in gh-pr-monitor** — monitor waits
  for all checks before declaring success ([GH-447](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/447))
- **Enforce triage delegation for all comment types** — every
  review comment routes through triage before fixup ([GH-463](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/463))
- **Enhance eval signal patterns** — delegation bypass detection
  uses more precise signal matching ([a09a2d6])
- **Clear PR merge policy and consolidation guidance** — document
  when to merge vs. consolidate PRs ([cf14b16])

### Bug Fixes

- **Resolve pr_comment_reply HTTP 422 on integer fields** — MCP
  tool now serialises numeric fields correctly ([GH-447](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/447))
- **Resolve skill audit findings in fixup and respond** — fix
  compliance gaps found during audit ([GH-459](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/459))
- **Prevent false positive unaddressed thread reports** — thread
  status detection no longer flags resolved threads ([GH-464](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/464))

### Documentation

- **Embed asciinema demo in README** — interactive terminal demo
  on the project landing page ([64d4a2e])

[a09a2d6]: https://github.com/Dev10x-Guru/dev10x-claude/commit/a09a2d6
[cf14b16]: https://github.com/Dev10x-Guru/dev10x-claude/commit/cf14b16
[64d4a2e]: https://github.com/Dev10x-Guru/dev10x-claude/commit/64d4a2e

## 0.39.0 — Generic Agents & Permission Hardening

Released 2026-03-25

### Features

- **Generic agent library for any project** — review, testing,
  architecture, and infrastructure agents now ship with the plugin
  for use on any codebase ([57e3830])
- **Quiet mode for update-paths.py** — suppress noisy output when
  running permission path updates ([GH-428](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/428))
- **Allow git reset without permission friction** — reset commands
  no longer trigger unnecessary approval prompts ([GH-441](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/441))

### Improvements

- **Promote review agents to plugin distribution** — domain-specific
  reviewer agents moved from internal to plugin-distributed so all
  users benefit ([23229f3])
- **Rebrand repo from dev10x-ai to Dev10x** — repository name,
  URLs, and marketplace references updated ([#442])
- **Tighten work-on approval gate and routing** — stricter approval
  flow prevents unintended auto-advance past decision gates ([GH-429](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/429))

### Bug Fixes

- **Prevent permission-maintenance bootstrap loop** — break the
  cycle where permission maintenance triggers itself ([GH-426](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/426))
- **Prevent stale permissions after worktree merge** — merged
  worktree rules are cleaned up so they don't cause false
  allow/deny matches ([GH-427](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/427))

### Documentation

- **Prevent misclassification of hook-enabled rules** — clarify
  that allow rules enabling hooks must not be removed even when
  the hook redirects the command ([GH-419](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/419))

[#442]: https://github.com/Dev10x-Guru/dev10x-claude/pull/442
[23229f3]: https://github.com/Dev10x-Guru/dev10x-claude/commit/23229f3
[57e3830]: https://github.com/Dev10x-Guru/dev10x-claude/commit/57e3830

## 0.38.0 — Brave-Labs Rebrand & Version Visibility

Released 2026-03-24

### Features

- **Version visibility in marketplace** — plugin description now
  leads with the installed version (e.g., `v0.38.0`) so users
  can tell at a glance what they're running
- **Automatic version in description** — bumpversion config
  updates both the `version` field and the description prefix
  in plugin.json

### Improvements

- **Repo rename to Brave-Labs** — all URLs, marketplace commands,
  and installation docs updated from `Brave-Labs/dev10x-ai` to
  `Brave-Labs/Dev10x`
- **Skill count update** — README and plugin description now
  reflect 59 skills (was 40)

### Bug Fixes

- **Restore PR comment and review tools** — re-enable
  `pr_comment_reply` and review MCP tools that were
  inadvertently disabled ([GH-422](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/422))

### Documentation

- **Data-driven skill redirect ADR** — propose friction-level
  based redirect system for hook validators ([GH-417](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/417))

## 0.37.0 — Skill Compliance Enforcement

Released 2026-03-24

Agents can no longer bypass skill delegations or use raw CLI
commands where skills exist. A new PreToolUse hook auto-denies
known CLI anti-patterns, SKILL.md enforcement markers prevent
inline handling of sub-skill operations, and a new MCP tool
eliminates the permission friction that incentivized bypasses.

### Features

- **Auto-deny wrong-tool drift** — PreToolUse hook blocks raw
  CLI commands (git commit -m, gh pr create, git push) that
  should go through skill wrappers, while allowing skill-internal
  patterns like -F and --fixup ([GH-397](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/397))
- **Frictionless PR comment replies** — new `pr_comment_reply`
  MCP tool replaces raw `gh api` calls in gh-pr-fixup,
  gh-pr-respond, and gh-pr-triage, removing per-invocation
  Bash permission prompts ([GH-399](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/399))

### Improvements

- **Sub-skill delegation enforcement** — gh-pr-respond gains
  REQUIRED: Skill() markers at all 5 delegation points (triage,
  fixup, groom, push, monitor), plus branch location pre-check
  and stash guard in git-groom ([GH-400](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/400))
- **Review delegation bypass prevention** — gh-pr-respond adds
  negative instruction prohibiting manual fixes; skill-reinforcement
  gains workflow-context checking for delegation bypasses ([GH-401](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/401))
- **Audit-driven skill hardening** — gh-pr-respond, gh-pr-fixup,
  and git-fixup gain mandatory markers for parallel dispatch,
  test gates, and CWD pre-checks based on audit findings ([GH-407](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/407))
- **Eval schema for Skill() assertions** — evaluation schema
  documents Skill() invocation assertion patterns, enabling
  detection of enforcement bypass regressions ([b90c5de])

[b90c5de]: https://github.com/Dev10x-Guru/dev10x-claude/commit/b90c5de

## 0.36.0 — PR Monitor Visibility & MCP Bugfix

Released 2026-03-23

PR monitoring reports full status context, and the MCP
pr_comments tool resolves a parameter mapping bug that
blocked all comment operations.

### Features

- **PR monitor status reporting** — monitor agent surfaces
  CI check details, unhandled review comments, and reviewer
  assignment status instead of completing silently ([GH-392](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/392))

### Bug Fixes

- **pr_comments parameter mapping** — fix `--pr-number` to
  `--pr` in cli_server.py so reply, resolve, and thread
  operations work correctly ([GH-393](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/393))

## 0.35.0 — Orchestration Integrity & Maintenance Skills

Released 2026-03-22

Skill delegation is enforced end-to-end, new maintenance skills
catch memory rot and playbook drift before they cause failures,
and CI deduplication eliminates wasted review runs.

### Features

- **Memory health auditing** — new `Dev10x:memory-maintenance`
  skill detects stale paths, script-calling instructions,
  contradictions, and MEMORY.md index drift ([GH-375](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/375))
- **Playbook drift detection** — new `Dev10x:playbook-maintenance`
  skill compares user overrides against defaults, surfacing new
  steps and prompt changes with severity levels ([GH-366](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/366))
- **Skill-usage reinforcement** — orchestration skill identifies
  CLI commands that should be replaced by dedicated skills or MCP
  tools, with prefix-matched command-to-skill mapping ([GH-384](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/384))
- **Project settings cleanup** — permission-maintenance gains
  Step 6 to strip duplicate, wildcard-covered, and stale rules
  from project settings files ([GH-386](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/386))
- **CI SHA deduplication** — GitHub Actions workflows skip
  redundant runs when a peer workflow already handles the same
  commit SHA ([GH-382](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/382))

### Improvements

- **Skill delegation enforcement** — work-on requires post-step
  Skill() verification and prohibits pipeline collapse during
  fanout execution ([GH-367](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/367))
- **CI re-monitoring after force push** — git-groom and work-on
  mandate `Dev10x:gh-pr-monitor` after any force push to avoid
  stale CI results ([GH-371](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/371))
- **Task reconciliation after delegation** — work-on reconciles
  parent task state after child skill completion, preventing
  orphaned tasks ([GH-376](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/376))
- **Wrong-database prevention** — db-psql requires target database
  comment prefix on manual SQL and sets PGAPPNAME for process
  identification ([GH-363](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/363))
- **Scope-aware fanout parsing** — fanout distinguishes scope URLs
  from specific item URLs, restricting scans to matching commands
  ([GH-351](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/351))
- **Skill routing through compaction** — compaction preservation
  directive keeps routing tables intact across context compression
  ([GH-358](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/358))
- **Unmatched play fallback** — work-on routes unmatched plays to
  the feature play instead of failing, and bans merge operations
  in gh-pr-monitor ([GH-357](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/357))
- **CWD-based worktree detection** — ticket-branch detects
  worktree context from current working directory ([GH-353](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/353))
- **Auto-filing audit findings** — skill-audit findings file
  automatically as GitHub issues ([GH-356](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/356))
- **Nested-mode task exemption** — formalized exemption for
  TaskCreate in nested skill invocations ([GH-355](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/355))

### Bug Fixes

- **Auditor deny-rule overreach** — permission-auditor now uses
  three-tier classification (deny/ask/hook-protected/skip) instead
  of blanket deny recommendations that blocked legitimate skills
  ([GH-385](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/385))
- **Premature completion gate** — work-on completion gate no longer
  fires before all tasks are finished ([GH-354](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/354))
- **Explore agent source failures** — GitHub/JIRA fetch subagents
  switched from Explore to general-purpose to gain Bash access
  ([GH-348](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/348))

## 0.34.0 — Fanout Safety & Skill Consistency

Released 2026-03-21

Fanout delegation is hardened against bypass and wrong-branch
commits, and trigger/skip documentation is standardized across
all skills.

### Bug Fixes

- **Fanout delegation safety** — prevent delegation bypass and
  wrong-branch commits with stricter orchestration guards
  ([GH-345](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/345))

### Improvements

- **Trigger/skip standardization** — consistent trigger and skip
  documentation across all skills, completing the effort started
  in v0.33.0 ([GH-313](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/313))

## 0.33.0 — Orchestration Discipline & Session Resilience

Released 2026-03-21

Fanout enforces structured work-on delegation, session state
survives compaction and restarts, and acceptance criteria
verification becomes a reusable skill.

### Features

- **Session resilience** — pre-compaction hook preserves critical
  context, session state persists across restarts, and skill
  invocation metrics are tracked for audit ([GH-310](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/310)–[GH-317](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/317))
- **Fanout orchestration discipline** — work-on delegation is now
  REQUIRED with enforcement language, per-issue subtask tracking,
  and new Monitor + Audit phases ([GH-338](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/338), [GH-339](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/339))
- **Full shipping pipeline in gh-pr-respond** — post-response
  continuation expanded from groom+push+monitor to the complete
  groom → push → ready → monitor → merge lifecycle with
  solo-maintainer auto-merge support ([GH-338](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/338), [GH-339](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/339))
- **Reusable definition-of-done verification** — extracted
  `Dev10x:verify-acc-dod` skill for consistent acceptance checks
  across work-on, fanout, and future orchestrators ([GH-340](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/340))

### Improvements

- **Task tracking in DDD and permission-maintenance** — both skills
  gain TaskCreate/TaskUpdate orchestration for supervisor visibility
  ([GH-41](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/41))
- **Statusline enrichment** — branch name and worktree context shown
  in terminal statusline ([GH-312](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/312))
- **Skill scaffolding** — `Dev10x:skill-create` generates directory
  structure with scripts via `scaffold.sh` ([GH-314](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/314))
- **Plugin health verification** — install and verify scripts validate
  plugin structure after updates ([GH-315](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/315))
- **Marketplace metadata** — enriched `marketplace.json` for better
  plugin discovery ([GH-317](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/317))
- **Trigger/skip standardization** — consistent trigger and skip
  documentation across 13+ skills ([GH-313](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/313))

## 0.32.0 — Permission Friction & Review Hardening

Released 2026-03-20

Permission friction eliminated across skill-audit, project-scope, and
py-uv skills. Code review agents gain stricter verification checks,
and work-on enforces playbook verification before plan generation.

### Features

- **Playbook verification in work-on** — Phase 3 now requires reading
  and verifying a playbook file before generating tasks, preventing
  ad-hoc plan generation that skips configured steps ([GH-308](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/308))
- **GitHub async timing checks** — code review agents detect stale
  `gh pr checks` results after force-pushes by verifying check count
  against expected baselines ([GH-318](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/318))
- **Table/implementation skew detection** — code review agents flag
  documentation tables that diverge from actual implementation

### Improvements

- **Reduced permission friction** — normalized `scripts/:*` to
  `scripts/*:*` across all `allowed-tools` declarations in skill-audit,
  py-uv, skill-create, and codex-skills equivalents ([GH-321](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/321))
- **Smarter sensitive file hook** — `block-sensitive-file-write.py` now
  uses basename matching instead of substring, eliminating false
  positives on sidecar metadata files like `.vars` ([GH-322](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/322))
- **Project-scope anti-patterns** — documented command substitution and
  env var prefix friction patterns to avoid in `gh` commands, switched
  sidecar files from `.env` to `.vars` ([GH-322](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/322))
- **Autosquash alias prefix** — `env` command prefix added to
  `GIT_SEQUENCE_EDITOR=true` in autosquash aliases for consistent
  shell expansion ([GH-319](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/319))
- **Skill name normalization** — Dev10x skill names normalized across
  documentation and scripts for consistency
- **Semicolon false positive fix** — SQL safety hook no longer blocks
  semicolons inside string literals like `STRING_AGG(name, '; ')`
  ([GH-320](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/320))

### Bug Fixes

- **Skill-audit permission prompt** — `extract-session.sh` no longer
  triggers approval prompts on every invocation due to mismatched
  `allowed-tools` glob pattern ([GH-321](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/321))

### Documentation

- **Updated skill pattern references** — all `scripts/:*` documentation
  examples updated to `scripts/*:*` across skill-audit, skill-create,
  and their codex-skills equivalents ([GH-309](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/309))

## 0.31.0 — MCP Consolidation & Parallel Workflows

Released 2026-03-20

MCP servers consolidate from 4 to 2, PR creation runs through native
MCP tools, macOS Keychain credentials land, and work-on gains parallel
stream processing with context compaction.

### Features

- **MCP tools for PR creation** — 6 gh-pr-create scripts and pr-notify
  wrapped as 7 MCP tools in gh_server.py, enabling dual-path transition
  with existing Bash paths ([GH-191](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/191))
- **Universal branch aliases** — git log, diff, rebase, and autosquash
  aliases now support main and master alongside existing develop,
  development, and trunk variants ([GH-288](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/288))
- **Non-destructive CTE in db queries** — db hook allows WITH clauses
  that don't modify data, unblocking analytical queries ([GH-303](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/303))
- **Slack thread investigation** — new plugin skill investigates Slack
  bug reports, root-causes in codebase, and creates Linear tickets
  ([#298])
- **Guided Slack integration setup** — interactive skill walks through
  Slack app creation, token configuration, and channel setup ([GH-14](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/14))
- **macOS Keychain credential retrieval** — secrets can be stored and
  retrieved via macOS Keychain as an alternative to env vars ([GH-119](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/119))

### Improvements

- **MCP server consolidation** — reduced from 4 servers to 2 (cli →
  git + utils, gh stays), cutting startup overhead ([GH-194](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/194))
- **Parallel work stream processing** — work-on dispatches independent
  tasks concurrently instead of sequentially ([#301])
- **Context compaction in orchestration** — skills compact context at
  phase boundaries to stay within token limits ([#299])
- **Work-on audit enforcement** — audit findings from GH-295, GH-296,
  GH-297 enforced as playbook and eval updates ([#300])
- **False positive prevention** — shared code patterns (MCP imports,
  PEP 723 inlining) no longer trigger review warnings ([#294])
- **Broader permission maintenance** — permission update workflow
  covers more path patterns and project configurations
- **Playbook pattern documentation** — reviewer guidance for validating
  playbook-powered skills and reference file patterns ([#243])
- **External tool declaration requirements** — skill authors must
  declare all external tool dependencies in SKILL.md front matter
  ([#270])
- **Invocation-name enforcement** — reviewer checklist enforces
  mandatory invocation-name field with exact-match rule ([#267])

### Testing

- **Automated hook testing** — pytest CI pipeline validates hook
  scripts with unit tests ([GH-214](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/214))
- **CI concurrency groups** — prevent duplicate CI runs on rapid
  pushes to the same branch ([GH-214](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/214))

### Bug Fixes

- **Non-interactive autosquash** — autosquash aliases wrap
  GIT_SEQUENCE_EDITOR=true to avoid escaping issues that broke alias
  expansion ([GH-288](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/288))

## 0.30.0 — Disciplined Orchestration

Released 2026-03-19

Work-on orchestration gets guardrails — mechanical plan generation,
mandatory phase tasks, and supervisor sign-off prevent shortcuts.
Git-domain skills gain MCP tool access, session skills get aligned
names, and script-path leaks are eliminated across the tooling surface.

### Features

- **MCP tool access for git skills** — git-domain skills can call MCP
  tools directly instead of shelling out via Bash wrappers ([GH-192](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/192))
- **Permission management skill** — base permission management enables
  structured allow/deny rule handling ([GH-274](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/274))
- **Slack file cleanup** — cleanup Slack config files and prompt for
  missing configuration ([GH-271](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/271))
- **Goodbye message** — session exit shows a resume command so users can
  pick up where they left off ([GH-272](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/272))
- **Block `$(cat ...)` substitution** — hook blocks command substitution
  via `cat` to prevent file content leaks in shell commands ([GH-277](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/277))

### Improvements

- **Aligned session skill names** — 11 session skills get consistent
  `Dev10x:` prefixed invocation names ([GH-224](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/224), [GH-102](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/102))
- **Script-path leak elimination** — skill tooling no longer leaks
  resolved cache paths in allowed-tools or Bash calls ([GH-280](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/280),
  [GH-275](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/275), [GH-283](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/283))
- **Destructive git commands ADR** — documented the decision to block
  destructive git operations by default ([GH-269](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/269))
- **Orchestration guardrail evals** — eval assertions enforce Phase 3
  mechanical planning and supervisor sign-off ([GH-248](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/248), [GH-273](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/273))

### Bug Fixes

- **Supervisor sign-off required** — plan completion gate now requires
  explicit supervisor confirmation instead of auto-completing ([GH-273](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/273))
- **Natural language plan mapping** — phrases like "show me the plan"
  route to AskUserQuestion gate, not plan mode ([GH-248](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/248))
- **Mechanical Phase 3** — plan generation enforces 1:1 task-to-step
  mapping from playbook, preventing step collapsing ([GH-248](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/248), [GH-273](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/273))
- **Phase task verification** — Phase 2 blocked until all 4 phase tasks
  are confirmed to exist ([GH-248](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/248))
- **ExitPlanMode prohibition** — work-on sessions cannot use Claude
  Code's built-in plan mode, preserving task tracking ([GH-248](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/248))
- **MCP-aware subagent routing** — Phase 2 fetches requiring MCP tools
  (Linear, Slack, Sentry) route to general-purpose agents, not Explore
  agents which lack MCP access ([GH-155](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/155))

## 0.29.0 — Smoother Shipping

Released 2026-03-16

Worktrees handle Husky v4 and Yarn Berry correctly, fish shell stops
breaking GraphQL queries, and delegated skills skip redundant task
tracking for faster unattended execution.

### Improvements

- **Unattended PR creation** — gh-pr-create supports `--unattended` flag
  with documented detection conditions and gate bypass rules ([GH-263](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/263))
- **Delegated skills skip TaskCreate** — skills invoked as subtasks of a
  parent orchestrator skip internal task tracking, reducing noise ([GH-258](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/258))
- **Body-only review handling** — gh-pr-respond Mode B handles reviews with
  body text but no inline comments, common from CI bots ([GH-258](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/258))
- **Non-skippable monitor output** — gh-pr-monitor Step 4 marked as
  non-skippable so users always see background agent progress ([GH-259](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/259))
- **Reduced work-on friction** — workspace detection extracted to script,
  implicit plan approval when user provides a complete plan ([GH-253](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/253))
- **Friction-free grooming** — raw GIT_SEQUENCE_EDITOR rebase replaced with
  git autosquash-develop alias to avoid env-prefix permission friction ([GH-253](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/253))

### Bug Fixes

- **Husky v4 and Yarn Berry in worktrees** — detect Husky version, bootstrap
  ~/.huskyrc for v4, use version-aware yarn install flags ([GH-222](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/222))
- **Fish shell GraphQL compatibility** — convert GraphQL examples to
  double-quoted with escaped `$` to prevent fish interpolation ([GH-258](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/258))

## 0.28.0 — Conflict-Free PRs

Released 2026-03-16

PRs now auto-detect and resolve merge conflicts before they reach reviewers.
MCP servers start reliably, and jq queries no longer trigger false-positive
obfuscation blocks.

### Improvements

- **Conflict-free PRs** — PR creation and monitoring detect merge conflicts
  via `git merge-tree` and GitHub's mergeable API, with auto-rebase +
  force-with-lease resolution ([GH-261](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/261))
- **Consistent skill naming** — 9 skills get proper `Dev10x:` invocation
  names with documented branding rationale ([GH-234](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/234))
- **Friction-free issue status checks** — jq concatenation pattern replaces
  interpolation to avoid obfuscation detection ([GH-260](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/260))
- **Full changelog** — all 22 releases (v0.2.0–v0.27.0) documented with
  themed headlines and linked issue references
- **MCP server permission review checks** — reviewer-infra now explicitly
  requires `+x` on server scripts

### Bug Fixes

- **MCP server startup** — 3 server scripts (db, gh, git) were missing
  execute permissions, causing "Permission denied" on startup

## 0.27.0 — Self-Healing Code Review

Released 2026-03-15

The shipping pipeline now fixes its own review findings autonomously.
Also: GitHub Issues support in project-scope and auto-approval for safe
subshell commands.

### Features

- **Self-healing code review** — work-on shipping pipeline now dispatches
  `Dev10x:review` + `Dev10x:review-fix` to autonomously create fixup commits
  for review findings ([GH-252](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/252))
- **Full task visibility in unattended mode** — git-commit and gh-pr-create
  create all startup tasks regardless of mode; auto-skipped tasks are
  immediately marked completed with reason ([GH-251](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/251))
- **GitHub Issues in project-scope** — Phase 3 Tracker Dispatch now supports
  GitHub Issues alongside Linear and JIRA, with batch creation pattern for
  10+ issues ([GH-244](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/244))
- **Auto-approval for safe subshells** — new `HookAllow` result type lets
  read-only subshell commands like `basename "$(git rev-parse ...)"` pass
  without permission prompts ([GH-247](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/247))
- **Worktree permission merging** — merge allow rules accumulated in worktree
  sessions back into the main project settings
- **Batch plugin permission updates** — auto-detect latest plugin version
  and update stale versioned paths across all projects in one pass

### Bug Fixes

- Prevent path errors when CWD drifts during session ([GH-251](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/251))

## 0.26.0 — Release Notes as a Skill

Released 2026-03-15

Track what you ship with playbook-powered release notes — configurable
ticket patterns, output targets (stdout/GitHub/Slack), and release/hotfix
plays.

### Features

- **Release notes skill** — generic, playbook-powered release notes generation
  with configurable ticket patterns, output targets (stdout/GitHub/Slack),
  and release/hotfix plays

## 0.25.0 — Unattended Shipping

Released 2026-03-15

Skills can now commit, format, and ship without human intervention.
Playbook fragments eliminate duplication, unattended git-commit bypasses
all interactive gates, and ruff formatting runs automatically on every
Python edit.

### Features

- **Reusable playbook fragments** — extract shared step sequences (like the
  9-step shipping pipeline) into named fragments, reducing duplication from
  36 of 55 steps across 4 plays ([GH-232](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/232))
- **Unattended git-commit** — when invoked by an orchestrating skill with
  an active task list, all interactive gates are bypassed: auto-stage,
  auto-select commit type, auto-generate problem/solution ([GH-237](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/237))
- **Automated ruff formatting** — PostToolUse hook runs `ruff format` +
  `ruff check --fix` on every Python file edit ([GH-231](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/231))
- **Post-response shipping continuation** — gh-pr-respond now offers to
  groom, push, and monitor CI after fixup commits ([GH-225](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/225))
- **Redundant command detection** — hook blocks `git -C <path>` when CWD
  already matches, and `cd <cwd> && ...` noop chains ([GH-225](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/225))
- **Respond playbook comment hiding** — gh-pr-respond can hide obsolete
  review comments after addressing them ([GH-226](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/226))
- **uv-managed test execution** — pyproject.toml with pytest/ruff dev deps
  so `uv run pytest` works without extra flags ([GH-225](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/225))

### Bug Fixes

- **Skill-audit enforcement gaps** — AskUserQuestion rule extended to global
  scope, Linear API fallback for non-autolinked prefixes ([GH-227](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/227))
- Ensure release script stages pyproject.toml after bump

## 0.24.0 — Auto-Advance Pipeline

Released 2026-03-14

The shipping pipeline no longer blocks on preview approval. Commits and
draft PR creation proceed automatically with a code-reviewer agent step.

### Features

- **Auto-advance shipping pipeline** — commits and draft PR creation proceed
  without blocking on preview approval, with code-reviewer agent step ([GH-213](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/213))
- Community link added to README

## 0.23.0 — Domain-Driven Design Workshops

Released 2026-03-12

Explore and model domain architecture with Event Storming directly from
Claude Code sessions.

### Features

- **DDD workshop skill** — bootstrap Domain-Driven Design Event Storming
  workshops for domain exploration and modeling ([GH-219](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/219))

### Bug Fixes

- Declare missing `allowed-tools` in 6 skills to eliminate per-invocation
  approval prompts ([GH-70](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/70))

## 0.22.0 — Playbook Architecture

Released 2026-03-12

The biggest architectural release to date. Work plans become reusable,
customizable playbooks. The hook dispatcher consolidates 7 processes into
one with ~80% overhead reduction. User-space config overrides ship.

### Features

- **Playbook architecture** — generalize work plans into reusable,
  customizable playbooks with convention-based discovery. Any orchestration
  skill can become playbook-powered by adding `references/playbook.yaml`.
  User overrides stored per-skill in memory ([GH-209](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/209))
- **Guided work plan customization** — dedicated `Dev10x:work-plan` skill
  with list, view, edit, and reset subcommands ([GH-209](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/209))
- **Per-project work plan customization** — projects can override plan
  templates without modifying plugin source ([GH-140](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/140))
- **Consolidated hook dispatcher** — replace 7 separate hook processes
  with one unified Python dispatcher using a validator registry.
  ~80-85% hook overhead reduction ([GH-208](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/208))
- **User-space config overrides** — `~/.claude/skill-index/` for
  `families.yaml` and `hidden.yaml` without modifying plugin source ([GH-10](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/10))
- **Alias enforcement** — block raw `git` commands with env-var prefixes
  or `$(git merge-base ...)` subshells when aliases exist ([GH-200](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/200))
- **Automated issue closing** — GitHub Actions workflow parses `Fixes:` URLs
  from merged PR bodies and closes referenced issues ([GH-209](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/209))

### Refactoring

- Split reviewer-skill into structure and behavior specs
- Trim CLAUDE.md to stay within 100-line budget
- Prefer jq and yq over manual JSON/YAML parsing ([GH-196](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/196))

## 0.21.0 — One-Command Review Requests

Released 2026-03-11

Assign GitHub reviewers and notify Slack in a single skill invocation.
PR creation now works in repos without a develop branch.

### Features

- **Combined review request skill** — `Dev10x:request-review` assigns
  GitHub reviewers and posts Slack notification in one command ([GH-188](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/188))
- **PR creation without develop** — gh-pr-create works in repos that
  use main as their only branch ([GH-180](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/180))
- **Prevent WIP in worktrees** — new worktrees no longer inherit
  uncommitted changes from the parent branch
- **Dynamic base branch validation** — hook validates PR target branch
  at creation time ([GH-187](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/187))

### Bug Fixes

- Prevent silent project linkage failures in Linear ([GH-153](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/153))

## 0.20.0 — Reliable Skill Orchestration

Released 2026-03-09

Numbered lists replace code blocks across 39 skills so decision gates and
orchestration steps actually fire instead of being skipped as examples.

### Features

- **Bundled call spec pattern** — complex tool call specifications live
  in `tool-calls/` sidecar files, referenced from SKILL.md enforcement
  markers ([GH-179](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/179))
- **Numbered list enforcement** — 39 skills updated to use numbered lists
  (not code blocks) for mandatory TaskCreate/AskUserQuestion calls ([GH-179](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/179))
- Centralize rules documentation into INDEX.md

## 0.19.0 — MCP Tools & Project Scoping

Released 2026-03-08

Native MCP server tools replace fragile Bash wrappers. Multi-ticket
projects get first-class scoping with Linear, JIRA, and GitHub Issues.
Dozens of enforcement fixes improve skill reliability.

### Features

- **MCP tools** — GitHub, Git, and Database operations exposed as MCP
  server tools, replacing fragile Bash-based wrappers ([GH-126](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/126))
- **Project-scope skill** — scaffold multi-ticket projects with milestones,
  blocking relationships, and tracker integration. Supports Linear, JIRA,
  and GitHub Issues ([GH-154](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/154))
- **Skill eval criteria** — measurable quality gates for skill behavior,
  enabling automated detection of decision gate violations ([GH-133](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/133))
- **Auto-resolved PR reviewers** — GitHub team reviewers resolved
  automatically from CODEOWNERS ([GH-118](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/118))
- **Temp file MCP tool** — `mktmp` tool prevents temp file collisions
  across concurrent sessions ([GH-143](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/143))
- **Upstream issue filing from audits** — skill-audit findings can be
  filed as GitHub issues at the plugin repo ([GH-135](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/135))
- **Parallel subagent dispatch** — skill-audit runs analysis phases
  concurrently ([GH-131](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/131))
- **Pre-approved tool access** — 17 skills declare `allowed-tools`
  to eliminate per-invocation approval prompts ([GH-70](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/70))

### Bug Fixes

- Enforce AskUserQuestion at all decision gates ([GH-133](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/133), [GH-151](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/151))
- Enforce TaskCreate orchestration at startup ([GH-134](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/134))
- Prevent Write tool error in commit workflow ([GH-126](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/126))
- Prevent GIT_SEQUENCE_EDITOR permission friction ([GH-121](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/121))
- Exclude .claude/worktrees/ from hook copies ([GH-144](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/144))
- Allow bare fixup commits from humans ([GH-159](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/159))

## 0.18.0 — Documentation

Released 2026-03-07

Updated README with installation instructions.

## 0.17.0 — Task Orchestration Everywhere

Released 2026-03-07

Every skill now tracks progress with structured tasks. Orchestration
patterns (auto-advance, batched decisions, tier-based complexity)
retrofitted across the entire skill catalog.

### Features

- **Task orchestration framework** — define patterns for task tracking,
  auto-advance, batched decisions, and tier-based complexity across all
  skills
- **Mandatory task tracking** — every skill now creates startup tasks
  and updates them as phases complete
- Retrofit orchestration into 4 flagship skills, Tier Full, Tier Standard,
  and PR lifecycle skills

## 0.16.0 — Documentation

Released 2026-03-06

Document external tool dependencies in README.

## 0.15.0 — Cross-Platform Skills

Released 2026-03-06

Skills now work in OpenAI Codex alongside Claude Code via a compatible
skill pack and install tooling.

### Features

- **Codex-compatible skill pack** — install tooling for OpenAI Codex
  environments alongside Claude Code
- Fix local type and test discovery for mirrored skills

### Self-Improving Review System

- Clarify PR title gitmoji mapping and JTBD third-party variants
- Clarify self-motivated work conventions

## 0.14.0 — The Great Consolidation

Released 2026-03-05

11 sub-plugins merged into one unified Dev10x plugin with a consistent
`Dev10x:` namespace and cross-script compatible directory resolution.

### Refactoring

- **Single plugin consolidation** — merge 11 separate plugin directories
  into one unified Dev10x plugin with consistent `Dev10x:` namespace
- Refactor directory resolution for cross-script compatibility
- Remove unused session-start-git-aliases hook
- Clarify hook-blocked and advisory patterns in session guidance

## 0.13.0 — Convention Polish

Released 2026-03-04

Surface @mentions at start of Slack review messages and establish
conventions for agent directories and skill naming.

### Refactoring

- Surface @mentions at start of Slack review messages
- Establish conventions for agent directories and skill naming

## 0.12.0 — Namespace Unification

Released 2026-03-04

Every skill gets the `Dev10x:` prefix. Skills are isolated into 11
domain-specific sub-plugins with distributed hooks and marketplace
discovery.

### Refactoring

- **Namespace unification** — standardize all skill invocation names
  from mixed `dx:`, `ticket:`, `pr:`, `qa:` prefixes to `Dev10x:`
- **Multi-plugin architecture** — isolate skills into 11 domain-specific
  sub-plugins (fundamentals, git, gh, db, tickets, sessions, parking,
  py, skills, slack, qa) with distributed hooks
- Enable marketplace to discover all sub-plugins

## 0.11.0 — Permission Auditing

Released 2026-03-04

Systematically audit Claude Code permission settings for security gaps.
Config-driven Slack notifications and dual-format skill index also ship.

### Features

- **Permission security auditing** — systematic audit agent for
  Claude Code permission settings
- **Config-driven Slack notifications** — per-project Slack channel
  and mention configuration for review requests
- **Dual-format skill index** — MOTD and SKILLS.md output formats
  with proper `Dev10x:` invocation prefixes
- Use Haiku model in GitHub Actions for faster CI

### Refactoring

- Delegate Slack and reviewer steps from pr-monitor to dedicated skills
- Stabilize test suite with proper dependencies

## 0.10.0 — Database Access & Session Guidance

Released 2026-03-03

Safe database querying with SQL validation hooks and intelligent
session-start recommendations. Family-grouped skill index and acceptance
criteria verification round out the release.

### Features

- **Database querying** — safe, customizable database access via plugin
  with SQL validation hooks
- **Family-grouped skill index** — adaptive-density display with YAML
  config for families and hidden skills
- **Acceptance criteria verification** — work-on checks criteria before
  shipping ([GH-86](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/86))
- **Session guidance** — surface wrapper discovery and git alias
  recommendations at session start ([GH-87](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/87))
- **Slack review readability** — improved formatting ([GH-54](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/54))
- Preserve plugin permissions across upgrades ([GH-79](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/79))

### Bug Fixes

- Detect `postgresql://` scheme in SQL safety hook
- Detect `psql` in chained commands
- Stabilize mktmp.sh and groom script paths

## 0.9.0 — Release Stability

Released 2026-03-02

Prevent version number skipping in releases.

### Bug Fixes

- Prevent version number skipping in releases

## 0.6.0 — Ticket Management & QA Automation

Released 2026-03-02

Full ticket lifecycle from branch creation to technical scoping. QA test
execution as a portable plugin skill. Context-aware rule loading reduces
always-loaded token overhead.

### Features

- **Ticket management suite** — branch creation, ticket creation, JTBD
  story write-back, and technical scoping for Linear tickets
- **QA automation** — portable plugin skills for QA test execution
- **ADR creation** — Architecture Decision Records as a plugin skill
- **Context-aware rule loading** — reduce always-loaded rules by scoping
  them to relevant file patterns ([GH-68](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/68))
- **Obsolete review summary hiding** — automatically hide stale PR review
  summaries in interactive and CI modes ([GH-44](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/44))
- **User task injection** — inject tasks during work-on execution ([GH-59](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/59))
- **Temp file collision prevention** — namespace-based temp files ([GH-19](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/19))
- **Workspace-agnostic Slack** — notifications work from any directory
- **Reusable technical scoping** — base scoping workflow for tickets and ADRs

### Bug Fixes

- Prevent review workflow self-cancellation

## 0.4.0 — Cleanup

Released 2026-03-02

Remove obsolete docs plans.

## 0.2.0 — Genesis

Released 2026-03-02

Initial release with 40+ skills covering the full development lifecycle
in a single plugin.

### Features

- **Plugin scaffold** — manifest, marketplace installation, semver releases
- **Session management** — task tracking, skill-usage audit, session wrap-up,
  MOTD with available skills
- **Work orchestration** — task-list-driven `work-on` skill with acceptance
  criteria verification
- **Git workflow** — safe rebase/force-push with branch protection, structured
  commits, atomic commit splitting, branch history grooming, retroactive
  ticket tracking, scoped fixup commits, git alias detection
- **PR lifecycle** — automated PR creation with JTBD stories, autonomous
  monitoring, review requests, comment response orchestration, comment
  triage/validation, session bookmarking, inline review findings, fixup
  commits from review comments
- **Parking/deferral** — code-level deferrals, smart routing, Slack DM
  reminders, cross-source discovery
- **JTBD drafting** — reusable Job Story generation for consistent business
  narratives
- **Worktrees** — isolated worktrees with IDE-safe branch separation,
  dual-mode creation
- **Linear integration** — MCP operations reference without tool duplication
- **Skill authoring** — creation without permission friction, templates,
  JTBD guidance
- **Plugin-distributed hooks** — safety and quality hooks shipped with
  the plugin
- **Self-executing Python** — UV-based script execution ([GH-17](https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/17))
- **Self-improving review system** — lessons from PR reviews automatically
  strengthen review checks

---

[#243]: https://github.com/Dev10x-Guru/dev10x-claude/pull/243
[#267]: https://github.com/Dev10x-Guru/dev10x-claude/pull/267
[#270]: https://github.com/Dev10x-Guru/dev10x-claude/pull/270
