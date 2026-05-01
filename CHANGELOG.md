# Changelog

All notable changes to the Dev10x Claude Code Plugin are documented here.
This project adheres to [Semantic Versioning](https://semver.org/).

## 0.69.0 — Permission Friction & Audit Empiricism

Released 2026-05-01

### Features

- **Enable empirical investigation of permission rule shapes** —
  audit tooling captures real-world permission rule patterns so
  prefix-friction diagnostics rest on observed behavior instead
  of assumptions ([GH-47])
- **Emit per-skill Read rules with `~/` + `/home` twins** —
  `plugin-maintenance` writes both expansions so Read rules match
  regardless of which form Claude resolves at allow-check time
  ([GH-48])
- **Detect Write-overwrite, workspace, and exit-code friction in
  audit** — three new diagnostics surface common permission
  prompt causes that previously slipped past audit reports
  ([GH-46])
- **Prefer working-dir scripts when CWD is plugin source** —
  hooks and skills resolve script paths to the active checkout
  rather than the installed plugin, so local edits take effect
  immediately ([GH-42])
- **Register `/tmp/Dev10x` workspace via `plugin-maintenance`
  bootstrap** — first-run setup adds the workspace allow rule so
  `mktmp` and friends stop prompting on fresh installs ([GH-40])
- **Stop pre-creating files in `mktmp` to avoid Write-overwrite
  prompt** — the MCP tool returns a fresh path without touching
  it, so the first Write call no longer trips the overwrite gate
  ([GH-39])
- **Expose audit-wrap log discovery via MCP tools** —
  `audit_hook_log_path` and `audit_hook_recent` let skills query
  hook timing data without shelling out ([GH-29])
- **Add PoC option to `ticket-scope` approval gate** — scoping a
  proof-of-concept ticket no longer forces the full template
  treatment ([GH-33])
- **Auto-detect Slack state to skip redundant prompts** —
  `slack-review-request` checks for an existing token before
  prompting, smoothing the request-review flow ([GH-19])

### Fixes

- **Fix Server Tests workflow path** — the CI path filter now
  matches the relocated MCP server module ([GH-9])
- **Use REST API for PR body updates to avoid Projects-classic
  exit 1** — `gh-pr-create` update mode bypasses a `gh` GraphQL
  failure on repos still attached to classic projects ([GH-41])
- **Resolve pre-existing mypy errors in MCP github and hook
  audit** — strict typing passes again after the GitHub-domain
  lift
- **Scope pre-PR mypy invocation to `src/`** — match
  `pyproject.toml` so the pre-PR check stops scanning unrelated
  trees

### Refactors

- **Lift the GitHub domain into a top-level package** — MCP
  GitHub helpers move out of the server-internal namespace so
  CLI tools and tests can share them ([GH-9])
- **Lift simple MCP domains into top-level packages** —
  cohesive single-purpose MCP modules become standalone packages
  for easier reuse ([GH-9])
- **Reuse subprocess utilities outside the MCP layer** — the
  shared subprocess helper graduates out of `mcp/` so audit and
  CLI consumers stop duplicating it ([GH-9])
- **Enforce template selection in `ticket-scope` Phase 5.1** —
  skill body blocks free-text drift through the template gate
  ([GH-28])
- **Enforce `jtbd` delegation in `ticket-scope` Phase 4b** —
  Job Story drafting routes through the dedicated skill
  ([GH-27])
- **Enforce `instructions.md` read at `ticket-scope` startup** —
  body content loads explicitly so phase logic is visible to the
  agent ([GH-26])
- **Preserve hook guardrails outside split-rebase docs** —
  `git-commit-split` references hook rules instead of redefining
  them ([GH-15])
- **Enable consistent coverage gates in skill scripts** — every
  skill script enforces the same coverage threshold ([GH-13])
- **Route raw `git` CLI in skill bodies through wrappers** —
  skills call the safe-rebase / safe-push wrappers instead of
  raw `git` so guardrails stay in force ([GH-14])

### Documentation

- **Document fanout-parallel hook propagation surprises** —
  parent hooks may not run inside fanout children; the rule lives
  next to the skill ([GH-32])
- **Document fanout-parallel cold-load budget floor** — children
  pay a fixed cold-load cost, so fanout below the floor is
  slower than serial ([GH-31])
- **Document `--bare` strips OAuth in fanout-parallel children**
  — bare clones lose token auth, breaking `gh` calls inside
  fanout children ([GH-30])
- **Clarify mode prompt overrides preserve skills delegation** —
  override examples no longer suggest dropping skill calls
  ([GH-45])
- **Forbid skill partial-read downgrade in `work-on`** — the
  skill always reads the full body to keep orchestration
  contracts intact ([GH-44])
- **Enforce `gh-pr-respond` for all PR review comments** —
  responding directly via `gh` bypasses validation gates
  ([GH-43])

### Polish

- **Modernize `Result` generics with PEP 695 syntax**
- **Wrap long literal strings in `src/dev10x` and tests**
- **Resolve `RuleEngine F821` in `edit_validator` hook**
- **Sort imports in `skill-audit` script entry points**
- **Remove dead test variables and rename ambiguous loop var**

[GH-1]: https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1
[GH-9]: https://github.com/Dev10x-Guru/Dev10x-Claude/issues/9
[GH-13]: https://github.com/Dev10x-Guru/Dev10x-Claude/issues/13
[GH-14]: https://github.com/Dev10x-Guru/Dev10x-Claude/issues/14
[GH-15]: https://github.com/Dev10x-Guru/Dev10x-Claude/issues/15
[GH-19]: https://github.com/Dev10x-Guru/Dev10x-Claude/issues/19
[GH-26]: https://github.com/Dev10x-Guru/Dev10x-Claude/issues/26
[GH-27]: https://github.com/Dev10x-Guru/Dev10x-Claude/issues/27
[GH-28]: https://github.com/Dev10x-Guru/Dev10x-Claude/issues/28
[GH-29]: https://github.com/Dev10x-Guru/Dev10x-Claude/issues/29
[GH-30]: https://github.com/Dev10x-Guru/Dev10x-Claude/issues/30
[GH-31]: https://github.com/Dev10x-Guru/Dev10x-Claude/issues/31
[GH-32]: https://github.com/Dev10x-Guru/Dev10x-Claude/issues/32
[GH-33]: https://github.com/Dev10x-Guru/Dev10x-Claude/issues/33
[GH-39]: https://github.com/Dev10x-Guru/Dev10x-Claude/issues/39
[GH-40]: https://github.com/Dev10x-Guru/Dev10x-Claude/issues/40
[GH-41]: https://github.com/Dev10x-Guru/Dev10x-Claude/issues/41
[GH-42]: https://github.com/Dev10x-Guru/Dev10x-Claude/issues/42
[GH-43]: https://github.com/Dev10x-Guru/Dev10x-Claude/issues/43
[GH-44]: https://github.com/Dev10x-Guru/Dev10x-Claude/issues/44
[GH-45]: https://github.com/Dev10x-Guru/Dev10x-Claude/issues/45
[GH-46]: https://github.com/Dev10x-Guru/Dev10x-Claude/issues/46
[GH-47]: https://github.com/Dev10x-Guru/Dev10x-Claude/issues/47
[GH-48]: https://github.com/Dev10x-Guru/Dev10x-Claude/issues/48

## 0.68.0 — First-Run Setup & PR-Skill Hardening

Released 2026-04-29

### Features

- **Streamline first-run permission setup** — bootstrap walks new
  users through the minimum permission set so the plugin works
  without per-tool prompting on day one ([GH-1])
- **Detect raw CLI in skill docs to prevent MCP/Skill bypass** —
  reviewer surfaces `gh`/`git` shell-outs in skill bodies that
  should route through MCP tools or sibling skills ([GH-5])
- **Eliminate per-invocation permission prompts in 18 skills** —
  audit-driven sweep adds the missing `allowed-tools` entries so
  these skills run without approval friction ([GH-11])
- **Allow scoped `pr_comments` listings on heavily reviewed PRs**
  — pagination + filtering avoid response-size limits on PRs with
  hundreds of threads ([GH-997])
- **Enable batched comment hiding via single GraphQL mutation** —
  one round-trip hides many comments instead of N requests
  ([GH-987])
- **Enable bootstrap coverage for uv/yq/git/gh patterns** —
  bootstrap allow rules cover the toolchain seen across skills
  out of the box ([GH-20])

### Fixes

- **Halt PR creation when pre-PR checks fail** — `gh-pr-create`
  no longer pushes a draft PR when type-check or test gates
  failed ([GH-998])
- **Enforce ticket-create haiku dispatch and tracker fast-fail**
  — tracker mismatches surface immediately and ticket creation
  uses the right model tier ([GH-998])
- **Enforce slack-review-request prepare script use** — Slack
  notifications go through the prepared script so token handling
  stays consistent ([GH-998])
- **Allow numeric-string comment IDs on `pr_comment` reply** —
  reply tool accepts both forms returned by upstream APIs
  ([GH-995])

### Refactors

- **Eliminate raw `gh` CLI in PR-skill bodies** — PR skills route
  through MCP wrappers, fixing audit findings and removing the
  raw-CLI bypass ([GH-12])
- **Guard `request-review` against approved PR pings** — already-
  approved PRs no longer ping reviewers redundantly ([GH-993])

[GH-987]: https://github.com/Dev10x-Guru/Dev10x-Claude/issues/987
[GH-993]: https://github.com/Dev10x-Guru/Dev10x-Claude/issues/993
[GH-995]: https://github.com/Dev10x-Guru/Dev10x-Claude/issues/995
[GH-997]: https://github.com/Dev10x-Guru/Dev10x-Claude/issues/997
[GH-998]: https://github.com/Dev10x-Guru/Dev10x-Claude/issues/998
[GH-5]: https://github.com/Dev10x-Guru/Dev10x-Claude/issues/5
[GH-11]: https://github.com/Dev10x-Guru/Dev10x-Claude/issues/11
[GH-12]: https://github.com/Dev10x-Guru/Dev10x-Claude/issues/12
[GH-20]: https://github.com/Dev10x-Guru/Dev10x-Claude/issues/20

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
  v0.65.0 upgrade pass no longer needs hand-holding ([GH-965])

### Refactors

- **Rename oversized SKILL.md files to instructions.md** —
  pure rename of 14 skill bodies (work-on, skill-audit,
  git-commit, gh-pr-monitor, gh-pr-respond, fanout, git-groom,
  qa-self, scope, git-commit-split, playbook, ticket-scope,
  gh-pr-merge, gh-pr-create) so `git log --follow` preserves
  history ahead of the frontmatter split ([GH-970])
- **Split skill frontmatter from body via instructions.md** —
  each oversized skill now ships a ~30–50 line SKILL.md (YAML
  frontmatter plus a pointer) with the body in `instructions.md`,
  so MOTD index and skill discovery costs drop and the body only
  loads once a skill is invoked ([GH-970])
- **Split task-orchestration.md into per-pattern files** —
  the 649-line shared reference shrinks to a 50-line index
  that links to per-pattern files under `references/orchestration/`,
  so downstream consumers keep working without edits and
  pattern detail loads only when a skill links the specific
  file ([GH-970])

### Documentation

- **Clarify data-handling practices for adopters** — the
  plugin documentation now describes local-only storage paths,
  states that no telemetry or user data leaves the machine,
  enumerates third-party integrations with credential scopes,
  and provides data deletion commands plus the audit-log
  disable switch, closing the disclosure gap flagged by an
  external security audit ([GH-966])
- **Enable reliable plugin install via shell CLI** — install
  instructions now prefer `claude plugin marketplace add` and
  `claude plugin install` shell commands (run outside a Claude
  Code session) over the unreliable `/plugin` slash commands,
  and drop the non-existent `claude plugin add --local`
  subcommand from the local-development path

[GH-965]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/965
[GH-966]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/966
[GH-970]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/970

## 0.65.0 — Hook Performance & Control

Released 2026-04-19

### Features

- **Shorten session startup by consolidating hooks** —
  SessionStart now runs 5 features in one orchestrator (Stop
  runs 2), replacing 8 `uv run --project` wrappers with
  direct-shebang scripts so every session feels faster without
  paying uv project resolution and CLI import cost per hook
  ([GH-959])
- **Surface per-hook execution timing for latency triage** —
  `@audit_hook` plus an `audit-wrap` shell wrapper capture
  body-phase and total (including uv startup) timing per
  invocation to `/tmp/Dev10x/logs/hooks-*.jsonl`, with
  `dev10x hook audit summary` and `prune` subcommands so slow
  hooks are diagnosable before users complain ([GH-860])
- **Let users dial hook strictness per session** — validator
  specs now carry `rule_id` (DX001–DX008), `profile`
  (minimal/standard/strict), and `experimental` flags, so
  `DEV10X_HOOK_PROFILE`, `DEV10X_HOOK_DISABLE`, and
  `DEV10X_HOOK_EXPERIMENTAL` can drop opinionated rules for
  throwaway work while keeping safety-critical guardrails on
  shared-repo commits ([GH-413])
- **Guide users to reconnect MCP instead of bypassing hook** —
  when the `Dev10x_cli` MCP server is unavailable, use-tool
  block messages now instruct the agent to ask the user to
  reconnect rather than fall back to wrapper scripts or reach
  for `DEV10X_SKIP_CMD_VALIDATION`, which users reject for
  transient outages ([GH-957])

[GH-413]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/413
[GH-860]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/860
[GH-957]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/957
[GH-959]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/959

## 0.64.0 — Platform Reach & Merge Safety

Released 2026-04-18

### Features

- **Support multi-platform installs via unified CLI** — register
  any AI assistant (Claude Code, Copilot, Windsurf, Continue,
  Cursor, or custom targets) with `dev10x platform add/list/remove`
  so Dev10x can extend beyond its original two-host scope without
  per-user path editing ([GH-908])
- **Automate PyPI publishing on release tags** — `v*` tag pushes
  publish the `dev10x` package via OIDC trusted publishing, so
  users can `pip install Dev10x` for CI scripts and hook
  integration without manual upload steps ([GH-953])
- **Guide new users through Dev10x onboarding** — `dev10x init`
  seeds starter config and prints a Next 5 Commands quick-start
  card, replacing the zero-direction `/help` landing with a
  frictionless guided setup ([GH-906])
- **Prevent silent merges past unresolved CI checks** —
  `Dev10x:gh-pr-merge` now blocks on `PENDING`, `IN_PROGRESS`, or
  any `bucket:fail` state and requires an explicit reason for
  override, closing the gap that shipped a bundle while e2e was
  still running ([GH-955])
- **Enforce instruction budget for large skills** — new
  `dev10x skill count-instructions` command measures actionable
  instructions and warns when skills exceed the 150-instruction
  reliability threshold from QRSPI research ([GH-882])
- **Offer structured retry after rejected commands** — when a
  user rejects a CLI command, `Dev10x:skill-reinforcement` now
  fires `AskUserQuestion` with retry/manual/cancel options
  instead of a plain-text follow-up that could silently auto-
  advance ([GH-952])
- **Prefer bundled PR for same-milestone multi-issue work** —
  `Dev10x:work-on` auto-selects a bundled PR strategy when all
  tickets share a milestone under solo-maintainer mode, cutting
  N branch switches, CI cycles, and merges down to one
  ([GH-948])
- **Enable MCP glob enumeration in upgrade-cleanup** — new
  `dev10x permission enumerate-mcp` subcommand replaces
  `mcp__plugin_Dev10x_*` wildcards with enumerated tool names,
  eliminating the manual approval prompts Claude Code fires when
  globs silently match nothing ([GH-947])
- **Enable Supabase env bootstrap in worktree hooks** — post-
  checkout hooks now copy `.env.supabase` into new worktrees so
  local Supabase connectivity works without manual file copying
  ([GH-946])

### Refactors

- **Isolate Dev10x scratch files under /tmp/Dev10x/** — plugin
  scratch files, session state, and the mktmp binary moved from
  the shared `/tmp/claude/` namespace to `/tmp/Dev10x/`, letting
  users scope allow rules to plugin-only paths ([GH-949])

### Chores

- **Keep scheduled_tasks.lock out of version control** — the
  session-local scheduler lock file is now gitignored so it
  cannot land alongside unrelated skill changes ([GH-955])

[GH-882]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/882
[GH-906]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/906
[GH-908]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/908
[GH-946]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/946
[GH-947]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/947
[GH-948]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/948
[GH-949]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/949
[GH-952]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/952
[GH-953]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/953
[GH-955]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/955

## 0.63.0 — Solo Shipping & Playbook Resilience

Released 2026-04-15

### Features

- **Enable auto-merge in solo-maintainer shipping pipeline** —
  solo maintainers no longer need to manually merge every PR;
  the shipping pipeline now includes a conditional merge step
  ([GH-940])
- **Enable playbook schema version tracking** — playbook files
  include a version field bumped automatically on release so
  drift between skills and core plugin is detectable ([GH-910])
- **Enable decision-aware session resume guidance** — resumed
  sessions surface pending decisions from task metadata and
  inject friction-level guidance so agents re-ask or
  auto-advance correctly ([GH-934])

### Fixes

- **Prevent non-functional MCP wildcards from masking
  permissions** — upgrade cleanup detects and removes top-level
  MCP wildcard patterns that Claude Code ignores at runtime,
  preventing false coverage from hiding missing tool entries
  ([GH-943], [GH-942])
- **Prevent fragment shadowing from dropping skills** — user
  playbook fragments that shadow defaults now inherit skills,
  agent, model, and modes fields instead of silently dropping
  them ([GH-938])
- **Prevent ACC review-requested from failing solo mode** —
  review-requested checks are skipped in solo-maintainer mode
  where no reviewers are ever assigned ([GH-939])
- **Resolve upgrade-cleanup broken script flags** — MCP tool
  routes ensure-base, generalize, and ensure-scripts to Python
  functions directly instead of passing invalid CLI flags
  ([GH-936])

### Refactors

- **Simplify onboarding skill with reference redirect** —
  extracted tour content to a references file, reducing
  SKILL.md from 202 to ~40 lines ([GH-897])

### Docs

- **Document CLI startup performance baseline** — baseline
  metrics and monitoring instructions for regression tracking
  ([GH-907])
- **Clarify tier 2 path after old projects/ removal** — config
  resolution docs updated to reflect the canonical
  `~/.claude/memory/Dev10x/` path ([GH-941])
- **Update gitignore for backup settings files** — settings
  backup files are now excluded from version control

[GH-897]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/897
[GH-907]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/907
[GH-910]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/910
[GH-934]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/934
[GH-936]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/936
[GH-938]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/938
[GH-939]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/939
[GH-940]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/940
[GH-941]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/941
[GH-942]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/942
[GH-943]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/943

## 0.62.0 — Issue Milestones & Permission Safety

Released 2026-04-14

### Features

- **Enable milestone assignment on issue creation** — ticket-create
  skill assigns milestones when specified, keeping project tracking
  aligned from the start ([GH-926])
- **Enable rollback for upgrade-cleanup bulk edits** — bulk settings
  modifications create timestamped backups so changes can be reverted
  if something goes wrong ([GH-921])
- **Enable CLI access to permission scripts** — permission audit and
  cleanup scripts are accessible from the dev10x CLI entry point
  ([GH-924])

### Fixes

- **Prevent wildcard rules from stripping permissions** — upgrade
  cleanup no longer removes valid allow rules when wildcard patterns
  overlap with specific entries ([GH-922])
- **Strengthen recurring audit finding guards** — audit-report skill
  checks for duplicate findings before filing, preventing redundant
  GitHub issues ([GH-928])

### Docs

- **Improve README with cover image and badges** — README now leads
  with marketplace badge, version badge, and a cover image for better
  first impressions

## 0.61.0 — Permission Diagnostics & Skill Refinements

Released 2026-04-14

### Features

- **Surface permission-denied diagnostics** — hooks detect blocked
  tool calls and provide actionable guidance on missing allow rules
  or hook configuration ([GH-918])
- **Improve upgrade-cleanup audit reporting** — upgrade-cleanup
  produces structured, severity-categorized findings instead of
  flat text output ([GH-914])
- **Enable direct review thread resolution** — gh-pr-respond can
  resolve review threads directly after posting fixup commits,
  reducing round-trips ([GH-902])

### Fixes

- **Stabilize uv dep resolution test assertion** — fix flaky test
  that depended on exact pip resolver output ordering ([GH-913])

### Tests

- **Validate uv shebang script dependencies** — new test ensures
  all PEP 723 inline-metadata scripts declare valid, resolvable
  dependencies ([GH-913])

### Docs & Skills

- **Persist session state across context resets** — session-stop
  hook preserves branch, plan, and task state so resumed sessions
  recover context automatically ([GH-917])
- **Detect architecture violations in PR review** — review skill
  checks for Clean Architecture boundary crossings ([GH-916])
- **Ensure monitor fallback on permission failure** — PR monitor
  retries with reduced permissions instead of failing silently
  ([GH-901])
- **Support natural-language input in work-on** — work-on accepts
  free-text task descriptions alongside ticket URLs ([GH-886])
- **Prefer vertical slice decomposition in scope** — scope skill
  favors feature slices over horizontal layer splits ([GH-885])
- **Monitor context fill at phase boundaries** — work-on tracks
  context window usage and warns before overflow ([GH-884])
- **Surface design analysis as a review gate** — scope skill
  requires design review before implementation begins ([GH-883])
- **Prevent confirmation bias with blind research** — brainstorming
  skill gathers evidence before presenting options ([GH-881])
- **Enable skill instruction count tracking** — skill-index reports
  instruction line counts for budget monitoring ([GH-877])
- **Resolve hook error handling standardization** — align hook exit
  codes and error messages across Python and shell ([GH-826])
- **Resolve milestone findings** — address M3–M6 architecture,
  pattern adoption, test coverage, and cross-cutting consistency
  findings ([GH-811], [GH-812], [GH-813], [GH-814])

## 0.60.0 — Multi-Issue Bundling & Audit Clarity

Released 2026-04-13

### Features

- **Bundle multiple issues in work-on** — work-on skill accepts
  multiple ticket URLs or IDs in a single invocation, gathering
  context in parallel and building a unified task list ([GH-868])
- **Separate audit detection from solution design** — permission
  auditor splits finding identification from fix proposals so
  users review problems before seeing solutions ([GH-904])

### Fixes

- **Restore MCP server dependencies** — re-add yaml and msgpack
  dependencies removed during consolidation so MCP servers start
  without import errors ([GH-911])
- **Enforce PR reference update after groom force-push** — groom
  skill now updates the PR head ref after force-pushing rebased
  commits, preventing stale SHA references ([GH-900])
- **Prevent misleading completion messages in fixup** — fixup
  skill no longer reports success when the underlying commit
  was not created ([GH-899])
- **Prevent wildcard allow-rule proposals in audit** — permission
  auditor blocks overly broad glob patterns that would bypass
  security boundaries ([GH-903])

### Docs

- **Clarify gh-pr-respond as PR comment entry point** — update
  skill description to direct users to gh-pr-respond instead
  of gh-pr-fixup for handling review comments ([GH-898])

## 0.59.0 — Permission Automation & Review Intelligence

Released 2026-04-13

### Features

- **Auto-detect semantic-release config** — release-notes skill
  now discovers project-specific ticket patterns and output
  targets without manual configuration ([GH-585])
- **Auto-groom fixup commits in CI** — PR monitor detects
  fixup! commits and triggers automatic interactive rebase
  before merge readiness ([GH-869])
- **Pre-approve temp file and MCP permissions** — new permission
  namespaces eliminate approval prompts for temp files, plugin
  scripts, MCP tools, and git aliases ([GH-878])
- **Simplify code after review** — post-review pipeline step
  scans changed files for reuse and quality improvements
  ([GH-874])
- **Filter review findings by confidence** — review skill drops
  low-confidence findings to reduce noise in PR comments
  ([GH-872])
- **Detect silent failures in reviews** — new reviewer agent
  catches swallowed exceptions and missing error logging
  ([GH-873])
- **Verify plugin script coverage** — pre-PR check ensures all
  plugin scripts referenced in skills have test coverage
  ([GH-876])
- **Invoke scripts via MCP instead of paths** — MCP server
  wraps plugin scripts so skills avoid path-dependent Bash
  allow rules ([GH-807])
- **Persist upgrade-cleanup config** — cleanup preferences
  survive across sessions via YAML settings file ([GH-862])

### Improvements

- **Extensible PR comment action dispatch** — comment handler
  uses registry pattern for adding new reply actions ([GH-827])
- **Self-formatting session state objects** — state dataclasses
  render their own display strings, removing format duplication
  ([GH-820], [GH-823])
- **Canonical rule evaluation via RuleEngine** — single
  evaluation path replaces scattered rule-checking code
  ([GH-818])
- **Single-source YAML rule parsing** — rule definitions load
  from YAML instead of duplicated Python dicts ([GH-822])
- **Path-independent plan context updates** — plan sync works
  from any working directory without hardcoded paths ([GH-802])
- **Type-safe MCP tool returns** — MCP tools return typed dicts
  instead of raw strings, catching schema mismatches early
  ([GH-819])
- **Validated repository references** — repo URL construction
  uses validated objects instead of string concatenation
  ([GH-821])

### Fixes

- **Prevent shipping pipeline skill regressions** — pin
  eval assertions that caught behavioral drift in PR create,
  groom, and merge skills ([GH-851])
- **Block fanout completion before monitors finish** — gate
  now waits for all background PR monitors before advancing
  ([GH-859])
- **Fix plugin cache lookup after repo rename** — cache key
  derivation uses canonical repo name, not stale path
  ([GH-861])
- **Detect stale plugin paths with different casing** — path
  comparison is now case-insensitive on case-folding
  filesystems ([GH-864])

### Tests

- **MCP GitHub tool coverage** — add unit tests for PR detect,
  issue get, and comment reply MCP tools ([GH-825])
- **Domain module regression safety** — add integration tests
  for core domain module imports and wiring ([GH-824])

## 0.58.0 — Session Safety & Config Hygiene

Released 2026-04-09

### Features

- **Surface background agent progress in caller** — add
  caller-side task tracking for background monitor agents so
  supervisors see in-progress work instead of an idle session
  ([GH-854])
- **Prevent auditing wrong session via gate** — skill-audit
  now confirms resolved session identity before proceeding,
  blocking silent fallback to alternate path encodings
  ([GH-805])

### Improvements

- **Normalize config paths to canonical locations** — remove
  deprecated Tier 3 path references from 16 skills, consolidate
  bare memory configs under Dev10x/ subdirectory, and align
  config-resolution docs with actual resolution order ([GH-849])

### Fixes

- **Preserve git alias rules from cleanup** — permission
  maintenance no longer removes git alias allow rules that
  worktree sessions depend on for branch-switching and commit
  grooming ([GH-852], [GH-853])
- **Prevent session.yaml overwrite of active modes** — Phase 0
  now reads before writing, preserving existing active_modes
  instead of overwriting with empty defaults ([GH-846])

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
  Claude Code capability assumptions ([GH-781])
- **Allow maintenance commits to bypass JTBD** — configurable
  bypass gitmoji set lets changelog/version-bump commits skip
  outcome-focused title enforcement ([GH-797])

### Improvements

- **Delegate tracker CRUD to background agents** — project-scope
  and ticket-create offload Linear/GitHub API calls to a haiku
  agent, returning compact summaries instead of dumping 26k token
  API responses into context ([GH-842])
- **Unblock MCP event loop from subprocess calls** — convert all
  MCP tool handlers to async using asyncio subprocess, eliminating
  up to 60s blocking during shell execution ([GH-815])
- **Enable batch thread resolution in PR comments** — resolve
  all review threads in two GraphQL calls instead of O(2N)
  sequential calls, avoiding rate limits in large PRs ([GH-828])
- **Surface lesson-learned guidance from stale PRs** — extract
  orchestration anti-patterns, test-pattern checks, and hook
  state documentation from 5 stale draft PRs into rules

### Fixes

- **Enforce named parameter Skill() syntax** — fix positional
  Skill() calls in ticket-create and ticket-jtbd that caused
  agent misrouting ([GH-804])
- **Enforce PR comment resolution in fanout** — Phase 5 now
  blocks completion until all PR review comments are resolved;
  per-item check added in Phase 3 ([GH-829])
- **Prevent plan gate skip at adaptive friction** — clarify
  that auto-select means execute the recommended option, not
  skip the approval gate entirely ([GH-808])
- **Enable portable plugin path in pr-monitor** — replace
  hardcoded versioned path with ${CLAUDE_PLUGIN_ROOT} variable
  ([GH-806])
- **Prevent session state race between sessions** — atomic
  os.rename() claim prevents two concurrent sessions from
  reading and deleting the same state file ([GH-816])

### Security

- **Protect settings.json from concurrent writes** — introduce
  fcntl advisory locking with atomic write-then-rename so
  concurrent sessions cannot overwrite each other's changes
  ([GH-817])

### Breaking Changes

- **Isolate codex port to separate repo** — remove codex-skills/
  directory (45 skill ports), codex install/validate scripts,
  and docs/codex.md ([GH-678])
- **Unify documentation under docs/ directory** — ADRs moved
  from doc/adr/ to docs/adr/; update any external links or
  scripts referencing the old path ([GH-838])

## 0.55.0 — Merge Safety & Skill Guardrails

Released 2026-04-08

### Features

- **Resolve skill-audit findings across 5 skills** — address
  accumulated audit findings for improved compliance ([GH-760])
- **Preserve fixup commit links after grooming** — groom no
  longer drops fixup commit references from PR threads ([GH-777])
- **Strengthen skill delegation guardrails** — prevent agents
  from bypassing skill orchestration contracts ([GH-759])
- **Prevent undetected cd+git chaining** — hook now catches
  cd-then-git patterns that break allow rules ([GH-763])
- **Prevent false positives on skill-required rules** — permission
  auditor no longer flags rules that skills actively need ([GH-790])
- **Enable publisher rename in permission paths** — update-paths
  handles publisher directory renames correctly ([GH-791])

### Refactoring

- **Enable single-source hook implementations** — consolidate
  12 standalone hook scripts into dev10x CLI subcommands ([GH-748])

### Fixes

- **Prevent false green on draft-to-ready** — CI monitor now
  re-checks status after PR transitions from draft ([GH-774])
- **Prevent orchestrator from pre-empting groom** — merge skill
  waits for groom completion before proceeding ([GH-776])
- **Prevent inline CI polling in merge skill** — delegates
  polling to monitor agent instead of inline loops ([GH-775])
- **Prevent merge failure in worktree setups** — gh pr merge
  now uses --repo flag in worktree contexts ([GH-773])
- **Prevent CI check cascade failure** — handle partial check
  results without aborting the entire merge flow ([GH-772])

## 0.54.0 — Hook Consolidation & Lazy Imports

Released 2026-04-08

### Features

- **Enable SessionStart hooks via dev10x hook session** — unified
  hook entry point for session startup ([GH-741])
- **Enable SessionStop hooks via dev10x hook session** — unified
  hook entry point for session teardown ([GH-742])
- **Enable Skill and PostToolUse hooks via dev10x hook** — unified
  hook entry point for tool-use lifecycle ([GH-743])
- **Centralize config into ~/.claude/memory/Dev10x** — single
  location for all plugin configuration ([GH-726])

### Performance

- **Defer heavy imports to command invocation** — lazy-load
  expensive modules to reduce CLI startup time ([GH-746])

### Refactoring

- **Enable cli_server as thin uv shim** — reduce server startup
  overhead with lightweight wrapper ([GH-744])
- **Enable db_server as thin uv shim** — reduce server startup
  overhead with lightweight wrapper ([GH-745])

### Fixes

- **Resolve hook failures on systems without PyYAML** — graceful
  fallback when optional dependency is missing ([GH-766])
- **Prevent false positive on explicit JSONL path** — path
  validation no longer flags valid JSONL files ([GH-762])

### Documentation

- **Clarify glob pattern syntax in config-resolution** — improve
  examples for file matching patterns ([GH-757])

### Tests

- **Enable CLI startup time benchmarking** — measure and track
  startup performance regressions ([GH-749])
- **Enable server tests to measure mcp package coverage** —
  expanded test coverage for MCP servers ([GH-745])

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
  ([GH-730])

### Fixes

- **Enforce fanout audit, monitor, and fixup safety** — fanout
  skill validates audit completion, monitors, and fixup commits
  before proceeding ([GH-724])
- **Enforce Check 1b in gh-pr-merge** — merge gate validates
  all required checks before allowing merge ([GH-728])
- **Prevent play step collapsing in work-on** — work-on skill
  preserves individual play steps during execution ([GH-729])
- **Prevent CI actions from running on merged PRs** — CI
  workflows skip already-merged pull requests ([GH-721])

### Tooling

- **Enable direct invocation of entry-point scripts** — scripts
  can be called directly without wrapper commands ([GH-732])
- **Update partner name in marketplace configuration** — align
  marketplace metadata with current branding

### Tests

- **Prevent script permission regressions** — test coverage for
  script file permissions ([GH-731])

## 0.49.0 — Cross-Context Auditing & Review Coverage

Released 2026-04-06

### Features

- **Ensure reviewers flag new classes without tests** — code
  review agents detect untested new classes ([GH-704])
- **Enable cross-context query detection in audits** — skill
  audit detects queries spanning multiple contexts ([GH-713])

### Fixes

- **Resolve plugin install failure from invalid key** — fix
  invalid configuration key blocking plugin installation
  ([GH-723])
- **Align phase selection spec with Phase I addition** — phase
  selection matches updated phase definitions ([GH-713])
- **Resolve batch review findings from 6 PRs** — address
  accumulated review findings across multiple PRs ([GH-709])

### Documentation

- **Document merge_mode and merge_strategy config** — add
  configuration reference for merge behavior options ([GH-707])
- **Clarify reference file discoverability and template
  guidance** — improve documentation for reference files

## 0.48.0 — Playbook Modes & Merge Safety

Released 2026-04-05

### Features

- **Per-step modes and friction in playbooks** — playbook steps
  can declare execution modes and friction levels independently
  ([GH-712])

### Fixes

- **Ensure acceptance criteria run before merge** — acceptance
  criteria checks execute before merge gate proceeds ([GH-711])

## 0.47.0 — Skill Reinforcement & Merge Safety

Released 2026-04-05

### Features

- **PermissionDenied hook corrections** — hooks detect and
  correct permission-denied errors with targeted guidance
  ([GH-705])
- **Merged PR audit for unaddressed findings** — surface
  unresolved review threads after merge ([GH-699])
- **Autonomous merge cascade in AFK mode** — unattended
  merge pipelines complete without manual intervention
  ([GH-688])
- **Session friction level prompt** — prompt users to select
  friction level at session start ([GH-689])
- **Comprehensive architecture auditing** — architecture
  advisor covers broader design evaluation ([GH-687])

### Fixes

- **Prevent merging with unaddressed review comments** —
  merge gate blocks when review threads remain open
  ([GH-698])
- **Prevent false positive on uv shebang hooks** — rule
  engine skips uv shebang lines in script validation
  ([GH-705])
- **Enable background CI monitor to poll autonomously** —
  CI monitor runs without blocking the session ([GH-695])
- **Resolve unaddressed PR #691 review findings** — fix
  outstanding review comments from prior PR ([GH-697])
- **Resolve circular import in rule_engine** — break import
  cycle in Python package structure ([GH-681])
- **Resolve fanout audit findings** — address audit issues
  in parallel work stream orchestrator ([GH-693])

### Refactoring

- **Rule-engine commit allowlist** — allowlist-based commit
  validation replaces ad-hoc checks ([GH-705])
- **Global skill-reinforcement overrides** — skill redirect
  rules configurable at global scope ([GH-705])

### Tests

- **Ensure Python entry point loadability** — verify all
  CLI entry points import without error ([GH-681])
- **Ensure Python script entry point loadability** — extend
  entry point tests to skill scripts ([GH-681])

## 0.46.0 — Architecture Consolidation & Performance

Released 2026-04-04

### Features

- **Unified Python package structure** — all validators, hooks,
  and CLI tools consolidated into `src/dev10x/` package with
  lazy-loading entry point ([GH-588], [GH-589])
- **RuleEngine for unified rule evaluation** — single engine
  replaces per-validator rule dispatch ([GH-644])
- **Typed config loading via Protocol** — config system uses
  Protocol-based contracts for type safety ([GH-650])
- **Friction-level tiered enforcement** — skill redirect hooks
  support configurable friction levels per command ([GH-530])
- **Executable acceptance criteria checks** — verify
  definition-of-done criteria programmatically ([GH-640])
- **Structured decision widgets** — AskUserQuestion gates use
  rich option widgets instead of plain text ([GH-636])
- **Pre-merge validation gate** — blocking check before merge
  ensures CI and review requirements are met ([GH-635])
- **On-demand PR review audits** — trigger review audits
  outside the normal PR lifecycle ([GH-551])
- **Configurable protected branch lists** — per-project
  protected branches without hardcoding ([GH-578])
- **Permission-aware dispatch in fanout** — parallel work
  streams respect permission boundaries ([GH-562])
- **Project-level commit gitmoji mapping** — projects can
  override default gitmoji conventions ([GH-585])
- **Groom skill conflict resolution** — interactive rebase
  handles merge conflicts gracefully ([GH-625])

### Performance

- **msgpack-cached config loading** — config reads use msgpack
  cache, reducing hook latency ([GH-591], [GH-652], [GH-653])
- **Lazy validator imports** — validators load only when
  needed, cutting startup time ([GH-654])
- **Startup time regression tests** — benchmark suite prevents
  hook performance regressions ([GH-656], [GH-657], [GH-658])

### Refactoring

- **Domain-driven validator architecture** — validators use
  Protocol conformance, shared GitContext, and reusable domain
  value objects ([GH-648], [GH-649], [GH-651])
- **Unified Rule/Config across all validators** — single Rule
  and Config types replace per-validator duplicates ([GH-645])
- **Single SQL validation source** — SQL checks consolidated
  into one module ([GH-647])
- **Domain-driven plan persistence** — plan storage uses
  domain models instead of raw file I/O ([GH-646])
- **Tell Don't Ask on EditRule** — EditRule encapsulates its
  own decision logic ([GH-643])
- **First-class skill script packages** — skill scripts are
  proper Python packages with imports ([GH-604])
- **Isolated tool modules** — Git, GitHub, and utility tools
  split into focused modules ([GH-600], [GH-601])
- **Python-based session hook dispatch** — session hooks
  migrate from shell to Python ([GH-598])
- **CLI-based validators** — Edit/Write and Bash validation
  use Click CLI commands ([GH-594], [GH-596], [GH-597])
- **Unified test directory** — all tests under `tests/`
  mirroring `src/` structure ([GH-595], [GH-607])
- **Deterministic test data via fakers** — factory-based
  test data generation ([GH-592])
- **Deprecated hook scripts removed** — old shell shims
  cleaned up ([GH-610])

### Fixes

- **Resolve macOS bash 3.2 hook errors** — hooks now work
  on macOS default bash ([GH-661])
- **Resolve permission-maintenance noise filter gaps** —
  false positive noise in permission audits ([GH-579])

### Docs

- **Reflect new src/ and tests/ layout** — documentation
  updated to match consolidated structure ([GH-611])
- **Document TOML vs YAML benchmark decision** — ADR for
  config format choice ([GH-655])
- **Showcase orchestration and planning in README** —
  feature highlights for new users
- **Coverage reporting in pytest runs** — test output
  includes coverage data ([GH-608])

### Tests

- **End-to-end validation of refactored plugin** — full
  plugin integration test suite ([GH-612])
- **Regex compilation benchmarking** — benchmark suite for
  compiled regex patterns ([GH-657])
- **Hook performance benchmarking** — pytest-benchmark
  integration for hook validators ([GH-656])

## 0.45.0 — CI Safety & Hook Config

Released 2026-04-01

### Features

- **CI merge-conflict detection** — CI pipeline now detects
  merge conflicts before allowing PR progression ([GH-563])
- **Safe deterministic transcript analysis** — enable
  transcript analysis with reproducible, safe parsing ([GH-565])

### Improvements

- **Config-driven hook validation** — all hooks use YAML-driven
  validation instead of hardcoded patterns ([GH-572])
- **Clarify memory path conventions** — db skill documents
  correct memory file path patterns ([GH-567])

### Fixes

- **Prevent PR ready with unaddressed findings** — PR cannot
  be marked ready when body-level findings remain ([GH-564])
- **Detect quoted paths in cd/git-C checks** — noop detection
  handles quoted directory paths correctly ([GH-568])
- **Remove unused CD_PREFIX_RE pattern** — dead regex cleanup

### Tests

- **Hook rule validation coverage** — ensure allow rules
  permit legitimate skill command invocations ([GH-572])

## 0.44.0 — MCP Expansion & Hook Hardening

Released 2026-03-31

### Features

- **MCP redirect for gh issue create** — issue creation routes
  through MCP tool instead of raw CLI ([GH-552])

### Improvements

- **Block direct git-push-safe invocation** — prevent users from
  calling push-safe directly via CLI, redirect to skill wrapper
  with safety guards ([GH-560])

### Fixes

- **Prevent monitor green during CI run** — monitor no longer
  reports premature success before CI completion ([GH-553])
- **Unblock commit from non-mktmp temp files** — allow commits
  from temporary files created outside mktmp system ([GH-554])

## 0.43.0 — Skill Ecosystem & Compliance Hardening

Released 2026-03-30

### Features

- **Competitive multi-agent design exploration** — ADR evaluation
  dispatches domain-specific architect agents in parallel for
  adversarial trade-off analysis ([GH-483])
- **YAML-driven skill redirect with friction levels** — PreToolUse
  hooks intercept raw CLI commands and redirect to skill wrappers
  with configurable friction ([GH-418])
- **Automated security review of changes** — reviewer-security
  agent scans diffs for OWASP vulnerabilities and hardcoded
  secrets ([GH-490])
- **CI-enforced test coverage for servers** — MCP server Python
  code now requires pytest coverage in CI ([GH-493])
- **Guided discovery for new users** — onboarding skill index
  and MOTD help new users find relevant skills ([GH-488])
- **Context window optimization** — systematic compaction
  patterns reduce token usage in long sessions ([GH-489])
- **Per-project model selection for dispatch** — playbook steps
  can override agent model tier per project ([GH-491])
- **Skill reinforcement for missing commands** — agent detects
  raw CLI usage and redirects to proper skills ([GH-506])
- **Proactive skill-audit triggers** — audit phase fires
  automatically when session processes 3+ items ([GH-537])
- **MCP redirect for gh issue view** — issue fetching routes
  through MCP tool instead of raw CLI ([GH-539])
- **Harden gh-pr-create skill compliance** — PR creation
  enforces all delegation and formatting rules ([GH-533])

### Improvements

- **Standardize tracker detection via MCP tool** — all skills
  use `detect_tracker` MCP call instead of script ([GH-507])
- **Reduce scoping wall-clock time** — background exploration
  agents parallelize codebase analysis ([GH-485])
- **Standardize skill trigger suffixes** — consistent TRIGGER/
  DO NOT TRIGGER patterns across all skills ([GH-484])
- **Enable standalone invocation of pipeline steps** — skills
  in pipelines can run independently ([GH-487])
- **Prefer MCP tool for PR context detection** — gh-context
  routes through MCP by default ([GH-534])
- **Allow inline synthesis when context suffices** — JTBD
  drafting skips full skill when session has rich context
  ([GH-536])
- **Establish canonical eval schema** — standardized JSON
  format for skill evaluation assertions ([GH-515])
- **Clarify decision gate assertion naming** — eval patterns
  use consistent signal names ([GH-488])
- **Prevent uv.lock drift after version bumps** — lock file
  stays in sync with pyproject.toml ([9630a11])

### Bug Fixes

- **Harden fanout and git skill guardrails** — Phase 5 checks
  PR comments, issues use sequential Skill(), MCP push_safe
  promoted, bypassPermissions documented ([GH-549])
- **Enforce test skill delegation in routing** — test step
  routes through skill wrapper, not raw pytest ([GH-504])
- **Enforce skill-create delegation in routing** — skill
  creation uses proper skill, not inline logic ([GH-503])
- **Prevent skill-audit from targeting current session** —
  audit dispatches to separate session context ([GH-508])
- **Resolve 3 complex skill-audit findings** — mixed
  compliance gaps in multiple skills ([d88ef81])
- **Self-healing for wrong mktmp namespace** — mktmp
  auto-corrects misrouted temp files ([d0acaf4])
- **Block cd+rev-parse chaining in hooks** — PreToolUse
  hook catches compound commands ([GH-528])
- **Prevent inline audit summary deviation** — audit
  results use structured output, not free text ([GH-531])
- **Mandate mktmp for commit message temp files** — commit
  skill always uses mktmp for collision-free paths ([GH-532])
- **Harden scope skill review compliance** — scope skill
  follows all review checklist items ([GH-485])
- **Resolve checklist numbering conflict** — PR body
  checklist renders correctly ([GH-486])

### Security

- **Enforce SKILL.md size discipline in reviewer** — reviewer
  flags skills exceeding line budgets ([GH-486])

### Documentation

- **Surface skill-pipelines in rule index** — pipeline
  composition patterns documented in INDEX.md ([GH-487])
- **Prevent MCP tool names used as CLI commands** — docs
  clarify MCP names are tool-call primitives only ([GH-535])
- **Enable prospective users to evaluate Dev10x** — public
  evaluation guide for potential adopters ([GH-492])

### CI

- **Tighten git commit -F allow pattern** — CI allow rules
  match the mktmp-based commit flow ([GH-418])

[GH-418]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/418
[GH-483]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/483
[GH-484]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/484
[GH-485]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/485
[GH-486]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/486
[GH-487]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/487
[GH-488]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/488
[GH-489]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/489
[GH-490]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/490
[GH-491]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/491
[GH-492]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/492
[GH-493]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/493
[GH-503]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/503
[GH-504]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/504
[GH-506]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/506
[GH-507]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/507
[GH-508]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/508
[GH-515]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/515
[GH-528]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/528
[GH-531]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/531
[GH-532]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/532
[GH-533]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/533
[GH-534]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/534
[GH-535]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/535
[GH-536]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/536
[GH-537]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/537
[GH-539]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/539
[GH-549]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/549
[9630a11]: https://github.com/Dev10x-Guru/dev10x-claude/commit/9630a11
[d88ef81]: https://github.com/Dev10x-Guru/dev10x-claude/commit/d88ef81
[d0acaf4]: https://github.com/Dev10x-Guru/dev10x-claude/commit/d0acaf4

## 0.42.0 — Plan Persistence & Audit Compliance

Released 2026-03-28

### Features

- **Persistent plan tracking across compaction** — task plans
  survive context window compaction via file-backed state
  ([GH-482])

### Bug Fixes

- **Resolve skill-audit TaskCreate validation failures** —
  audit skill handles missing task fields gracefully ([GH-496])
- **Ensure audit-report delegates to ticket-create** — report
  filing routes through proper skill wrapper ([GH-498])
- **Resolve script allow-rule permission friction** — script
  paths match updated plugin directory layout ([GH-499])
- **Prevent premature merge from SKIPPING checks** — CI
  monitor excludes SKIPPING from pass count ([GH-501])
- **Prevent inline triage bypass in gh-pr-respond** — all
  comments route through triage before fixup ([GH-502])
- **Prevent groom step bypass via self-assessment** — groom
  skill always presents strategy gate ([GH-505])

[GH-482]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/482
[GH-496]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/496
[GH-498]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/498
[GH-499]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/499
[GH-501]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/501
[GH-502]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/502
[GH-505]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/505

## 0.41.0 — Orchestration Guardrails & Plan Persistence

Released 2026-03-27

### Features

- **Per-skill model selection for agents** — agent specs and
  skill dispatch choose model tier based on task complexity
  ([GH-470])
- **Harden work-on orchestration guardrails** — skill routing
  enforcement table survives context compaction ([GH-477])
- **Plan persistence across compaction** — plans backed by
  files survive context window resets ([GH-414])

### Improvements

- **Clarify skill docs for nested mode and push** — nested
  invocation exemptions and push safety documented ([GH-475])

### Bug Fixes

- **Prevent marking PR ready with unaddressed comments** —
  post-CI comment re-check catches late bot reviews ([GH-465])

### Security

- **Enforce git-commit skill via PreToolUse hook** — raw
  `git commit` blocked; must use Dev10x:git-commit ([GH-473])

### Tests

- **Ensure dispatcher tests match commit hook rules** —
  test suite validates hook-to-skill routing ([GH-473])

[GH-414]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/414
[GH-465]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/465
[GH-470]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/470
[GH-473]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/473
[GH-475]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/475
[GH-477]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/477

## 0.40.0 — Delegation Hardening & Fixup Skill Gaps

Released 2026-03-26

### Features

- **Frictionless issue creation from skills** — skills can now
  create GitHub issues without approval prompts ([GH-445])
- **Strengthen delegation bypass prevention** — skills enforce
  proper delegation chains instead of raw CLI calls ([GH-458])
- **Resolve gh-pr-fixup skill gaps** — fixup skill now handles
  all edge cases surfaced by audit ([GH-459])

### Improvements

- **Harden work-on skill against audit regressions** — work-on
  orchestration no longer drifts when audit findings change
  ([GH-448])
- **Prevent raw command bypass in PR creation** — PR creation
  enforces skill delegation instead of raw `gh pr create`
  ([GH-448])
- **Prevent delegation bypass in gh-pr-respond** — response skill
  enforces proper triage-then-fixup pipeline ([GH-447])
- **Prevent premature CI exit in gh-pr-monitor** — monitor waits
  for all checks before declaring success ([GH-447])
- **Enforce triage delegation for all comment types** — every
  review comment routes through triage before fixup ([GH-463])
- **Enhance eval signal patterns** — delegation bypass detection
  uses more precise signal matching ([a09a2d6])
- **Clear PR merge policy and consolidation guidance** — document
  when to merge vs. consolidate PRs ([cf14b16])

### Bug Fixes

- **Resolve pr_comment_reply HTTP 422 on integer fields** — MCP
  tool now serialises numeric fields correctly ([GH-447])
- **Resolve skill audit findings in fixup and respond** — fix
  compliance gaps found during audit ([GH-459])
- **Prevent false positive unaddressed thread reports** — thread
  status detection no longer flags resolved threads ([GH-464])

### Documentation

- **Embed asciinema demo in README** — interactive terminal demo
  on the project landing page ([64d4a2e])

[GH-445]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/445
[GH-447]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/447
[GH-448]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/448
[GH-458]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/458
[GH-459]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/459
[GH-463]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/463
[GH-464]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/464
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
  running permission path updates ([GH-428])
- **Allow git reset without permission friction** — reset commands
  no longer trigger unnecessary approval prompts ([GH-441])

### Improvements

- **Promote review agents to plugin distribution** — domain-specific
  reviewer agents moved from internal to plugin-distributed so all
  users benefit ([23229f3])
- **Rebrand repo from dev10x-ai to Dev10x** — repository name,
  URLs, and marketplace references updated ([#442])
- **Tighten work-on approval gate and routing** — stricter approval
  flow prevents unintended auto-advance past decision gates ([GH-429])

### Bug Fixes

- **Prevent permission-maintenance bootstrap loop** — break the
  cycle where permission maintenance triggers itself ([GH-426])
- **Prevent stale permissions after worktree merge** — merged
  worktree rules are cleaned up so they don't cause false
  allow/deny matches ([GH-427])

### Documentation

- **Prevent misclassification of hook-enabled rules** — clarify
  that allow rules enabling hooks must not be removed even when
  the hook redirects the command ([GH-419])

[GH-419]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/419
[GH-426]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/426
[GH-427]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/427
[GH-428]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/428
[GH-429]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/429
[GH-441]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/441
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
  inadvertently disabled ([GH-422])

### Documentation

- **Data-driven skill redirect ADR** — propose friction-level
  based redirect system for hook validators ([GH-417])

[GH-417]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/417
[GH-422]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/422

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
  patterns like -F and --fixup ([GH-397])
- **Frictionless PR comment replies** — new `pr_comment_reply`
  MCP tool replaces raw `gh api` calls in gh-pr-fixup,
  gh-pr-respond, and gh-pr-triage, removing per-invocation
  Bash permission prompts ([GH-399])

### Improvements

- **Sub-skill delegation enforcement** — gh-pr-respond gains
  REQUIRED: Skill() markers at all 5 delegation points (triage,
  fixup, groom, push, monitor), plus branch location pre-check
  and stash guard in git-groom ([GH-400])
- **Review delegation bypass prevention** — gh-pr-respond adds
  negative instruction prohibiting manual fixes; skill-reinforcement
  gains workflow-context checking for delegation bypasses ([GH-401])
- **Audit-driven skill hardening** — gh-pr-respond, gh-pr-fixup,
  and git-fixup gain mandatory markers for parallel dispatch,
  test gates, and CWD pre-checks based on audit findings ([GH-407])
- **Eval schema for Skill() assertions** — evaluation schema
  documents Skill() invocation assertion patterns, enabling
  detection of enforcement bypass regressions ([b90c5de])

[GH-397]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/397
[GH-399]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/399
[GH-400]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/400
[GH-401]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/401
[GH-407]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/407
[b90c5de]: https://github.com/Dev10x-Guru/dev10x-claude/commit/b90c5de

## 0.36.0 — PR Monitor Visibility & MCP Bugfix

Released 2026-03-23

PR monitoring reports full status context, and the MCP
pr_comments tool resolves a parameter mapping bug that
blocked all comment operations.

### Features

- **PR monitor status reporting** — monitor agent surfaces
  CI check details, unhandled review comments, and reviewer
  assignment status instead of completing silently ([GH-392])

### Bug Fixes

- **pr_comments parameter mapping** — fix `--pr-number` to
  `--pr` in cli_server.py so reply, resolve, and thread
  operations work correctly ([GH-393])

[GH-392]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/392
[GH-393]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/393

## 0.35.0 — Orchestration Integrity & Maintenance Skills

Released 2026-03-22

Skill delegation is enforced end-to-end, new maintenance skills
catch memory rot and playbook drift before they cause failures,
and CI deduplication eliminates wasted review runs.

### Features

- **Memory health auditing** — new `Dev10x:memory-maintenance`
  skill detects stale paths, script-calling instructions,
  contradictions, and MEMORY.md index drift ([GH-375])
- **Playbook drift detection** — new `Dev10x:playbook-maintenance`
  skill compares user overrides against defaults, surfacing new
  steps and prompt changes with severity levels ([GH-366])
- **Skill-usage reinforcement** — orchestration skill identifies
  CLI commands that should be replaced by dedicated skills or MCP
  tools, with prefix-matched command-to-skill mapping ([GH-384])
- **Project settings cleanup** — permission-maintenance gains
  Step 6 to strip duplicate, wildcard-covered, and stale rules
  from project settings files ([GH-386])
- **CI SHA deduplication** — GitHub Actions workflows skip
  redundant runs when a peer workflow already handles the same
  commit SHA ([GH-382])

### Improvements

- **Skill delegation enforcement** — work-on requires post-step
  Skill() verification and prohibits pipeline collapse during
  fanout execution ([GH-367])
- **CI re-monitoring after force push** — git-groom and work-on
  mandate `Dev10x:gh-pr-monitor` after any force push to avoid
  stale CI results ([GH-371])
- **Task reconciliation after delegation** — work-on reconciles
  parent task state after child skill completion, preventing
  orphaned tasks ([GH-376])
- **Wrong-database prevention** — db-psql requires target database
  comment prefix on manual SQL and sets PGAPPNAME for process
  identification ([GH-363])
- **Scope-aware fanout parsing** — fanout distinguishes scope URLs
  from specific item URLs, restricting scans to matching commands
  ([GH-351])
- **Skill routing through compaction** — compaction preservation
  directive keeps routing tables intact across context compression
  ([GH-358])
- **Unmatched play fallback** — work-on routes unmatched plays to
  the feature play instead of failing, and bans merge operations
  in gh-pr-monitor ([GH-357])
- **CWD-based worktree detection** — ticket-branch detects
  worktree context from current working directory ([GH-353])
- **Auto-filing audit findings** — skill-audit findings file
  automatically as GitHub issues ([GH-356])
- **Nested-mode task exemption** — formalized exemption for
  TaskCreate in nested skill invocations ([GH-355])

### Bug Fixes

- **Auditor deny-rule overreach** — permission-auditor now uses
  three-tier classification (deny/ask/hook-protected/skip) instead
  of blanket deny recommendations that blocked legitimate skills
  ([GH-385])
- **Premature completion gate** — work-on completion gate no longer
  fires before all tasks are finished ([GH-354])
- **Explore agent source failures** — GitHub/JIRA fetch subagents
  switched from Explore to general-purpose to gain Bash access
  ([GH-348])

## 0.34.0 — Fanout Safety & Skill Consistency

Released 2026-03-21

Fanout delegation is hardened against bypass and wrong-branch
commits, and trigger/skip documentation is standardized across
all skills.

### Bug Fixes

- **Fanout delegation safety** — prevent delegation bypass and
  wrong-branch commits with stricter orchestration guards
  ([GH-345])

### Improvements

- **Trigger/skip standardization** — consistent trigger and skip
  documentation across all skills, completing the effort started
  in v0.33.0 ([GH-313])

## 0.33.0 — Orchestration Discipline & Session Resilience

Released 2026-03-21

Fanout enforces structured work-on delegation, session state
survives compaction and restarts, and acceptance criteria
verification becomes a reusable skill.

### Features

- **Session resilience** — pre-compaction hook preserves critical
  context, session state persists across restarts, and skill
  invocation metrics are tracked for audit ([GH-310]–[GH-317])
- **Fanout orchestration discipline** — work-on delegation is now
  REQUIRED with enforcement language, per-issue subtask tracking,
  and new Monitor + Audit phases ([GH-338], [GH-339])
- **Full shipping pipeline in gh-pr-respond** — post-response
  continuation expanded from groom+push+monitor to the complete
  groom → push → ready → monitor → merge lifecycle with
  solo-maintainer auto-merge support ([GH-338], [GH-339])
- **Reusable definition-of-done verification** — extracted
  `Dev10x:verify-acc-dod` skill for consistent acceptance checks
  across work-on, fanout, and future orchestrators ([GH-340])

### Improvements

- **Task tracking in DDD and permission-maintenance** — both skills
  gain TaskCreate/TaskUpdate orchestration for supervisor visibility
  ([GH-41])
- **Statusline enrichment** — branch name and worktree context shown
  in terminal statusline ([GH-312])
- **Skill scaffolding** — `Dev10x:skill-create` generates directory
  structure with scripts via `scaffold.sh` ([GH-314])
- **Plugin health verification** — install and verify scripts validate
  plugin structure after updates ([GH-315])
- **Marketplace metadata** — enriched `marketplace.json` for better
  plugin discovery ([GH-317])
- **Trigger/skip standardization** — consistent trigger and skip
  documentation across 13+ skills ([GH-313])

## 0.32.0 — Permission Friction & Review Hardening

Released 2026-03-20

Permission friction eliminated across skill-audit, project-scope, and
py-uv skills. Code review agents gain stricter verification checks,
and work-on enforces playbook verification before plan generation.

### Features

- **Playbook verification in work-on** — Phase 3 now requires reading
  and verifying a playbook file before generating tasks, preventing
  ad-hoc plan generation that skips configured steps ([GH-308])
- **GitHub async timing checks** — code review agents detect stale
  `gh pr checks` results after force-pushes by verifying check count
  against expected baselines ([GH-318])
- **Table/implementation skew detection** — code review agents flag
  documentation tables that diverge from actual implementation

### Improvements

- **Reduced permission friction** — normalized `scripts/:*` to
  `scripts/*:*` across all `allowed-tools` declarations in skill-audit,
  py-uv, skill-create, and codex-skills equivalents ([GH-321])
- **Smarter sensitive file hook** — `block-sensitive-file-write.py` now
  uses basename matching instead of substring, eliminating false
  positives on sidecar metadata files like `.vars` ([GH-322])
- **Project-scope anti-patterns** — documented command substitution and
  env var prefix friction patterns to avoid in `gh` commands, switched
  sidecar files from `.env` to `.vars` ([GH-322])
- **Autosquash alias prefix** — `env` command prefix added to
  `GIT_SEQUENCE_EDITOR=true` in autosquash aliases for consistent
  shell expansion ([GH-319])
- **Skill name normalization** — Dev10x skill names normalized across
  documentation and scripts for consistency
- **Semicolon false positive fix** — SQL safety hook no longer blocks
  semicolons inside string literals like `STRING_AGG(name, '; ')`
  ([GH-320])

### Bug Fixes

- **Skill-audit permission prompt** — `extract-session.sh` no longer
  triggers approval prompts on every invocation due to mismatched
  `allowed-tools` glob pattern ([GH-321])

### Documentation

- **Updated skill pattern references** — all `scripts/:*` documentation
  examples updated to `scripts/*:*` across skill-audit, skill-create,
  and their codex-skills equivalents ([GH-309])

## 0.31.0 — MCP Consolidation & Parallel Workflows

Released 2026-03-20

MCP servers consolidate from 4 to 2, PR creation runs through native
MCP tools, macOS Keychain credentials land, and work-on gains parallel
stream processing with context compaction.

### Features

- **MCP tools for PR creation** — 6 gh-pr-create scripts and pr-notify
  wrapped as 7 MCP tools in gh_server.py, enabling dual-path transition
  with existing Bash paths ([GH-191])
- **Universal branch aliases** — git log, diff, rebase, and autosquash
  aliases now support main and master alongside existing develop,
  development, and trunk variants ([GH-288])
- **Non-destructive CTE in db queries** — db hook allows WITH clauses
  that don't modify data, unblocking analytical queries ([GH-303])
- **Slack thread investigation** — new plugin skill investigates Slack
  bug reports, root-causes in codebase, and creates Linear tickets
  ([#298])
- **Guided Slack integration setup** — interactive skill walks through
  Slack app creation, token configuration, and channel setup ([GH-14])
- **macOS Keychain credential retrieval** — secrets can be stored and
  retrieved via macOS Keychain as an alternative to env vars ([GH-119])

### Improvements

- **MCP server consolidation** — reduced from 4 servers to 2 (cli →
  git + utils, gh stays), cutting startup overhead ([GH-194])
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
  scripts with unit tests ([GH-214])
- **CI concurrency groups** — prevent duplicate CI runs on rapid
  pushes to the same branch ([GH-214])

### Bug Fixes

- **Non-interactive autosquash** — autosquash aliases wrap
  GIT_SEQUENCE_EDITOR=true to avoid escaping issues that broke alias
  expansion ([GH-288])

## 0.30.0 — Disciplined Orchestration

Released 2026-03-19

Work-on orchestration gets guardrails — mechanical plan generation,
mandatory phase tasks, and supervisor sign-off prevent shortcuts.
Git-domain skills gain MCP tool access, session skills get aligned
names, and script-path leaks are eliminated across the tooling surface.

### Features

- **MCP tool access for git skills** — git-domain skills can call MCP
  tools directly instead of shelling out via Bash wrappers ([GH-192])
- **Permission management skill** — base permission management enables
  structured allow/deny rule handling ([GH-274])
- **Slack file cleanup** — cleanup Slack config files and prompt for
  missing configuration ([GH-271])
- **Goodbye message** — session exit shows a resume command so users can
  pick up where they left off ([GH-272])
- **Block `$(cat ...)` substitution** — hook blocks command substitution
  via `cat` to prevent file content leaks in shell commands ([GH-277])

### Improvements

- **Aligned session skill names** — 11 session skills get consistent
  `Dev10x:` prefixed invocation names ([GH-224], [GH-102])
- **Script-path leak elimination** — skill tooling no longer leaks
  resolved cache paths in allowed-tools or Bash calls ([GH-280],
  [GH-275], [GH-283])
- **Destructive git commands ADR** — documented the decision to block
  destructive git operations by default ([GH-269])
- **Orchestration guardrail evals** — eval assertions enforce Phase 3
  mechanical planning and supervisor sign-off ([GH-248], [GH-273])

### Bug Fixes

- **Supervisor sign-off required** — plan completion gate now requires
  explicit supervisor confirmation instead of auto-completing ([GH-273])
- **Natural language plan mapping** — phrases like "show me the plan"
  route to AskUserQuestion gate, not plan mode ([GH-248])
- **Mechanical Phase 3** — plan generation enforces 1:1 task-to-step
  mapping from playbook, preventing step collapsing ([GH-248], [GH-273])
- **Phase task verification** — Phase 2 blocked until all 4 phase tasks
  are confirmed to exist ([GH-248])
- **ExitPlanMode prohibition** — work-on sessions cannot use Claude
  Code's built-in plan mode, preserving task tracking ([GH-248])
- **MCP-aware subagent routing** — Phase 2 fetches requiring MCP tools
  (Linear, Slack, Sentry) route to general-purpose agents, not Explore
  agents which lack MCP access ([GH-155])

## 0.29.0 — Smoother Shipping

Released 2026-03-16

Worktrees handle Husky v4 and Yarn Berry correctly, fish shell stops
breaking GraphQL queries, and delegated skills skip redundant task
tracking for faster unattended execution.

### Improvements

- **Unattended PR creation** — gh-pr-create supports `--unattended` flag
  with documented detection conditions and gate bypass rules ([GH-263])
- **Delegated skills skip TaskCreate** — skills invoked as subtasks of a
  parent orchestrator skip internal task tracking, reducing noise ([GH-258])
- **Body-only review handling** — gh-pr-respond Mode B handles reviews with
  body text but no inline comments, common from CI bots ([GH-258])
- **Non-skippable monitor output** — gh-pr-monitor Step 4 marked as
  non-skippable so users always see background agent progress ([GH-259])
- **Reduced work-on friction** — workspace detection extracted to script,
  implicit plan approval when user provides a complete plan ([GH-253])
- **Friction-free grooming** — raw GIT_SEQUENCE_EDITOR rebase replaced with
  git autosquash-develop alias to avoid env-prefix permission friction ([GH-253])

### Bug Fixes

- **Husky v4 and Yarn Berry in worktrees** — detect Husky version, bootstrap
  ~/.huskyrc for v4, use version-aware yarn install flags ([GH-222])
- **Fish shell GraphQL compatibility** — convert GraphQL examples to
  double-quoted with escaped `$` to prevent fish interpolation ([GH-258])

## 0.28.0 — Conflict-Free PRs

Released 2026-03-16

PRs now auto-detect and resolve merge conflicts before they reach reviewers.
MCP servers start reliably, and jq queries no longer trigger false-positive
obfuscation blocks.

### Improvements

- **Conflict-free PRs** — PR creation and monitoring detect merge conflicts
  via `git merge-tree` and GitHub's mergeable API, with auto-rebase +
  force-with-lease resolution ([GH-261])
- **Consistent skill naming** — 9 skills get proper `Dev10x:` invocation
  names with documented branding rationale ([GH-234])
- **Friction-free issue status checks** — jq concatenation pattern replaces
  interpolation to avoid obfuscation detection ([GH-260])
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
  for review findings ([GH-252])
- **Full task visibility in unattended mode** — git-commit and gh-pr-create
  create all startup tasks regardless of mode; auto-skipped tasks are
  immediately marked completed with reason ([GH-251])
- **GitHub Issues in project-scope** — Phase 3 Tracker Dispatch now supports
  GitHub Issues alongside Linear and JIRA, with batch creation pattern for
  10+ issues ([GH-244])
- **Auto-approval for safe subshells** — new `HookAllow` result type lets
  read-only subshell commands like `basename "$(git rev-parse ...)"` pass
  without permission prompts ([GH-247])
- **Worktree permission merging** — merge allow rules accumulated in worktree
  sessions back into the main project settings
- **Batch plugin permission updates** — auto-detect latest plugin version
  and update stale versioned paths across all projects in one pass

### Bug Fixes

- Prevent path errors when CWD drifts during session ([GH-251])

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
  36 of 55 steps across 4 plays ([GH-232])
- **Unattended git-commit** — when invoked by an orchestrating skill with
  an active task list, all interactive gates are bypassed: auto-stage,
  auto-select commit type, auto-generate problem/solution ([GH-237])
- **Automated ruff formatting** — PostToolUse hook runs `ruff format` +
  `ruff check --fix` on every Python file edit ([GH-231])
- **Post-response shipping continuation** — gh-pr-respond now offers to
  groom, push, and monitor CI after fixup commits ([GH-225])
- **Redundant command detection** — hook blocks `git -C <path>` when CWD
  already matches, and `cd <cwd> && ...` noop chains ([GH-225])
- **Respond playbook comment hiding** — gh-pr-respond can hide obsolete
  review comments after addressing them ([GH-226])
- **uv-managed test execution** — pyproject.toml with pytest/ruff dev deps
  so `uv run pytest` works without extra flags ([GH-225])

### Bug Fixes

- **Skill-audit enforcement gaps** — AskUserQuestion rule extended to global
  scope, Linear API fallback for non-autolinked prefixes ([GH-227])
- Ensure release script stages pyproject.toml after bump

## 0.24.0 — Auto-Advance Pipeline

Released 2026-03-14

The shipping pipeline no longer blocks on preview approval. Commits and
draft PR creation proceed automatically with a code-reviewer agent step.

### Features

- **Auto-advance shipping pipeline** — commits and draft PR creation proceed
  without blocking on preview approval, with code-reviewer agent step ([GH-213])
- Community link added to README

## 0.23.0 — Domain-Driven Design Workshops

Released 2026-03-12

Explore and model domain architecture with Event Storming directly from
Claude Code sessions.

### Features

- **DDD workshop skill** — bootstrap Domain-Driven Design Event Storming
  workshops for domain exploration and modeling ([GH-219])

### Bug Fixes

- Declare missing `allowed-tools` in 6 skills to eliminate per-invocation
  approval prompts ([GH-70])

## 0.22.0 — Playbook Architecture

Released 2026-03-12

The biggest architectural release to date. Work plans become reusable,
customizable playbooks. The hook dispatcher consolidates 7 processes into
one with ~80% overhead reduction. User-space config overrides ship.

### Features

- **Playbook architecture** — generalize work plans into reusable,
  customizable playbooks with convention-based discovery. Any orchestration
  skill can become playbook-powered by adding `references/playbook.yaml`.
  User overrides stored per-skill in memory ([GH-209])
- **Guided work plan customization** — dedicated `Dev10x:work-plan` skill
  with list, view, edit, and reset subcommands ([GH-209])
- **Per-project work plan customization** — projects can override plan
  templates without modifying plugin source ([GH-140])
- **Consolidated hook dispatcher** — replace 7 separate hook processes
  with one unified Python dispatcher using a validator registry.
  ~80-85% hook overhead reduction ([GH-208])
- **User-space config overrides** — `~/.claude/skill-index/` for
  `families.yaml` and `hidden.yaml` without modifying plugin source ([GH-10])
- **Alias enforcement** — block raw `git` commands with env-var prefixes
  or `$(git merge-base ...)` subshells when aliases exist ([GH-200])
- **Automated issue closing** — GitHub Actions workflow parses `Fixes:` URLs
  from merged PR bodies and closes referenced issues ([GH-209])

### Refactoring

- Split reviewer-skill into structure and behavior specs
- Trim CLAUDE.md to stay within 100-line budget
- Prefer jq and yq over manual JSON/YAML parsing ([GH-196])

## 0.21.0 — One-Command Review Requests

Released 2026-03-11

Assign GitHub reviewers and notify Slack in a single skill invocation.
PR creation now works in repos without a develop branch.

### Features

- **Combined review request skill** — `Dev10x:request-review` assigns
  GitHub reviewers and posts Slack notification in one command ([GH-188])
- **PR creation without develop** — gh-pr-create works in repos that
  use main as their only branch ([GH-180])
- **Prevent WIP in worktrees** — new worktrees no longer inherit
  uncommitted changes from the parent branch
- **Dynamic base branch validation** — hook validates PR target branch
  at creation time ([GH-187])

### Bug Fixes

- Prevent silent project linkage failures in Linear ([GH-153])

## 0.20.0 — Reliable Skill Orchestration

Released 2026-03-09

Numbered lists replace code blocks across 39 skills so decision gates and
orchestration steps actually fire instead of being skipped as examples.

### Features

- **Bundled call spec pattern** — complex tool call specifications live
  in `tool-calls/` sidecar files, referenced from SKILL.md enforcement
  markers ([GH-179])
- **Numbered list enforcement** — 39 skills updated to use numbered lists
  (not code blocks) for mandatory TaskCreate/AskUserQuestion calls ([GH-179])
- Centralize rules documentation into INDEX.md

## 0.19.0 — MCP Tools & Project Scoping

Released 2026-03-08

Native MCP server tools replace fragile Bash wrappers. Multi-ticket
projects get first-class scoping with Linear, JIRA, and GitHub Issues.
Dozens of enforcement fixes improve skill reliability.

### Features

- **MCP tools** — GitHub, Git, and Database operations exposed as MCP
  server tools, replacing fragile Bash-based wrappers ([GH-126])
- **Project-scope skill** — scaffold multi-ticket projects with milestones,
  blocking relationships, and tracker integration. Supports Linear, JIRA,
  and GitHub Issues ([GH-154])
- **Skill eval criteria** — measurable quality gates for skill behavior,
  enabling automated detection of decision gate violations ([GH-133])
- **Auto-resolved PR reviewers** — GitHub team reviewers resolved
  automatically from CODEOWNERS ([GH-118])
- **Temp file MCP tool** — `mktmp` tool prevents temp file collisions
  across concurrent sessions ([GH-143])
- **Upstream issue filing from audits** — skill-audit findings can be
  filed as GitHub issues at the plugin repo ([GH-135])
- **Parallel subagent dispatch** — skill-audit runs analysis phases
  concurrently ([GH-131])
- **Pre-approved tool access** — 17 skills declare `allowed-tools`
  to eliminate per-invocation approval prompts ([GH-70])

### Bug Fixes

- Enforce AskUserQuestion at all decision gates ([GH-133], [GH-151])
- Enforce TaskCreate orchestration at startup ([GH-134])
- Prevent Write tool error in commit workflow ([GH-126])
- Prevent GIT_SEQUENCE_EDITOR permission friction ([GH-121])
- Exclude .claude/worktrees/ from hook copies ([GH-144])
- Allow bare fixup commits from humans ([GH-159])

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
  shipping ([GH-86])
- **Session guidance** — surface wrapper discovery and git alias
  recommendations at session start ([GH-87])
- **Slack review readability** — improved formatting ([GH-54])
- Preserve plugin permissions across upgrades ([GH-79])

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
  them to relevant file patterns ([GH-68])
- **Obsolete review summary hiding** — automatically hide stale PR review
  summaries in interactive and CI modes ([GH-44])
- **User task injection** — inject tasks during work-on execution ([GH-59])
- **Temp file collision prevention** — namespace-based temp files ([GH-19])
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
- **Self-executing Python** — UV-based script execution ([GH-17])
- **Self-improving review system** — lessons from PR reviews automatically
  strengthen review checks

---

[GH-1]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/1
[GH-7]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/7
[GH-10]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/10
[GH-15]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/15
[GH-17]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/17
[GH-19]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/19
[GH-31]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/31
[GH-33]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/33
[GH-35]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/35
[GH-44]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/44
[GH-45]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/45
[GH-50]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/50
[GH-54]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/54
[GH-59]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/59
[GH-68]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/68
[GH-70]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/70
[GH-79]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/79
[GH-84]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/84
[GH-86]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/86
[GH-87]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/87
[GH-118]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/118
[GH-121]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/121
[GH-126]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/126
[GH-131]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/131
[GH-133]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/133
[GH-134]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/134
[GH-135]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/135
[GH-140]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/140
[GH-143]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/143
[GH-144]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/144
[GH-151]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/151
[GH-153]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/153
[GH-154]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/154
[GH-157]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/157
[GH-159]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/159
[GH-179]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/179
[GH-180]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/180
[GH-187]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/187
[GH-188]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/188
[GH-196]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/196
[GH-200]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/200
[GH-208]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/208
[GH-209]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/209
[GH-213]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/213
[GH-219]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/219
[GH-225]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/225
[GH-226]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/226
[GH-227]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/227
[GH-231]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/231
[GH-232]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/232
[GH-237]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/237
[GH-244]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/244
[GH-247]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/247
[GH-251]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/251
[GH-252]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/252
[GH-253]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/253
[GH-258]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/258
[GH-259]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/259
[GH-260]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/260
[GH-261]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/261
[GH-263]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/263
[GH-267]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/267
[GH-269]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/269
[GH-270]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/270
[GH-271]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/271
[GH-272]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/272
[GH-273]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/273
[GH-274]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/274
[GH-275]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/275
[GH-277]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/277
[GH-280]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/280
[GH-283]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/283
[GH-288]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/288
[GH-313]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/313
[GH-345]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/345
[GH-348]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/348
[GH-351]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/351
[GH-353]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/353
[GH-354]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/354
[GH-355]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/355
[GH-356]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/356
[GH-357]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/357
[GH-358]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/358
[GH-363]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/363
[GH-366]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/366
[GH-367]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/367
[GH-371]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/371
[GH-375]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/375
[GH-376]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/376
[GH-382]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/382
[GH-384]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/384
[GH-385]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/385
[GH-386]: https://github.com/Dev10x-Guru/Dev10x-Claude2/issues/386
[#243]: https://github.com/Dev10x-Guru/dev10x-claude/pull/243
[#267]: https://github.com/Dev10x-Guru/dev10x-claude/pull/267
[#270]: https://github.com/Dev10x-Guru/dev10x-claude/pull/270
