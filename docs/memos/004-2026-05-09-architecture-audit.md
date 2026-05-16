# Architecture Audit — 2026-05-09

Comprehensive 9-phase audit of the Dev10x plugin codebase
(`/work/dx/Dev10x-Claude` @ `develop` / 0.72.0.dev0).

- **Method**: 9 parallel `Explore` sub-agents (Phases A–I) on 86 source
  files (`src/dev10x/`), 106 test files, 73 skills, 22 plugin agents.
- **Total findings**: 87 (15 HIGH, 47 MEDIUM, 25 LOW).
- **Cross-phase signal**: six recurring themes account for ~60% of
  findings — see § Recurring Themes.

## Phase Summary

| Phase | Topic | Findings | HIGH |
|-------|-------|---------:|-----:|
| A | Pattern Catalog | 14 | 2 |
| B | Domain Model Health | 10 | 2 |
| C | Value Object Discovery | 10 | 3 |
| D | Archetype Stress Test | 9 | 0 |
| E | Concurrency Audit | 8 | 2 |
| F | Behavioral Pattern Fit | 9 | 0 |
| G | JTBD Coverage Matrix | 10 | 3 |
| H | Cross-Cutting Consistency | 9 | 2 |
| I | Cross-Context Queries | 8 | 1 |

## Top-15 HIGH-Impact Findings

Ranked by risk × leverage. Citations are file:line where available;
full evidence in the per-phase agent transcripts.

| # | Title | Phase | Effort |
|---|-------|------:|-------:|
| 1 | `session_migrate_permissions` rewrites `~/.claude/settings.json` non-atomically from concurrent sessions — can corrupt and break hook dispatch | E | M |
| 2 | Plan YAML load-mutate-save is unlocked; parallel `Dev10x:fanout` agents silently discard each other's `TaskCreate`/`TaskUpdate` records (`hooks/task_plan_sync.py:123-144`) | E | M |
| 3 | `permission/__init__.py` (MCP service) calls underscore-private `_ensure_*` functions in `skills/permission/update_paths.py` via `redirect_stdout` capture — broken API boundary | I | M |
| 4 | `plan.json_summary()` returns `{}` on git-not-found instead of `{"error": …}` — silent MCP error contract violation (`plan/__init__.py:47`) | H | S |
| 5 | `subprocess_utils.run_script` raises uncaught `FileNotFoundError` through the MCP layer instead of returning structured error — every MCP module affected | H | S |
| 6 | `_effective_cwd` ContextVar has no `@requires_cwd` enforcement — new MCP tools silently fall back to startup CWD (root cause class of GH-979) | A | S |
| 7 | 3-tier config resolver documented in `references/config-resolution.md` is reimplemented inline by 13+ skills — no shared `ConfigResolver` Chain of Responsibility | A | L |
| 8 | `ProfileTier` is bare `str` with `.index()` ordinal compare and silent `except ValueError` fallback — invalid `DEV10X_HOOK_PROFILE` falls through (`validators/__init__.py:60-75`) | C | S |
| 9 | `McpToolName` parsed via 4 different regexes across `enumerate_mcp.py`, `update_paths.py`, `permission_diagnostics.py`, `privacy.py` — two wildcard patterns are subtly different | C | M |
| 10 | `~/.claude/...` path constructed 20+ times; `USERSPACE_CONFIG` triplicated identically across three `skills/permission/` modules — no `ClaudeDir` constants module | C | M |
| 11 | No `Task` domain object — `PlanSummary.tasks: list[dict]` forces `t.get("status")` access in 3+ format methods (`domain/session_state.py:83-200`) | B | M |
| 12 | `analyze_permissions.main()` is a 40-line procedural pipeline with no `AuditReport` model; MCP wrapper shells out instead of importing | B | M |
| 13 | MCP handler test gap: ~27 of 40 handlers untested (`create_pr`, `update_pr`, `push_safe`, `post_summary_comment`, `pr_comment_reply` bot identity); `cwd` parameter from PR #66/GH-979 has zero MCP-layer test | G | L |
| 14 | `post_summary_comment` (called at end of every `gh-pr-create`) has no test in either `test_github.py` or `test_cli_server.py` despite carrying bot-identity `as_bot=True` | G | M |
| 15 | All 6 `dev10x permission investigate` CLI subcommands (~240 LOC, PR #50 / GH-47) have zero integration tests — `restore` could leave dangling test fixtures, `record` could silently drop measurements | G | M |

## Recurring Themes

Findings cluster around six structural issues. Fixing one root cause
typically retires 3–6 individual findings.

### T1. The `Plan` complex
Touched by 8 findings across A, B, D, E, F, I. Symptoms:
- `Plan.metadata: dict[str, Any]` is publicly mutated by callers; archive
  logic (`metadata["archived_at"] = …`) duplicated in `plan/__init__.py`
  and `hooks/task_plan_sync.py`.
- `plan/__init__.py` (MCP) deep-imports `Plan`, `get_plan_path`,
  `get_toplevel` from `hooks/task_plan_sync` instead of `domain/plan`.
- No `Task` value object; status transitions are `if status == "completed"`
  string compares with no allowed-from invariants.
- Load-mutate-save is unlocked → silent record loss under concurrent agents.

**Single fix**: extract `plan/service.py`; promote `Plan` and `Task` as
the canonical domain types; move `archive()` onto `Plan`; wrap
load-mutate-save in `fcntl.flock`-guarded transaction.

### T2. The validator registry should be a Registry
Touched by A1/A2/A3, B6, C2/C4, D3, F4. Symptoms:
- `_VALIDATOR_SPECS` is a 5-tuple list mutated post-init by monkey-patching
  `instance.rule_id`/`profile`/`experimental` onto each validator.
- `ProfileTier` is a tuple of strings with `.index()` ordinal compare.
- `_load_profile_config` parses `DEV10X_HOOK_DISABLE` env var with
  duplicate `.upper()` normalisation; no `RuleId` value object.
- `Config.is_guided()`/`is_strict()` predicates absent — friction-level
  branching scattered across 3 modules with two different vocabularies
  (validator profile vs config friction-level — both contain `"strict"`).

**Single fix**: `ValidatorBase` dataclass with declared metadata fields;
`ValidatorRegistry` class with `lookup`/`is_active`; `ProfileTier`,
`FrictionLevel`, `ValidatorRuleId` as enums/VOs.

### T3. MCP error contract is non-uniform
Touched by H1/H2/H9, I2, A5. Symptoms:
- `github` and `db` use `Result[T]`; `audit`/`release`/`monitor`/
  `permission`/`plan`/`skill_index`/`utilities` return bare `{"error": …}`.
- Some return `{}` on failure (silent success).
- `subprocess_utils` raises `FileNotFoundError` past the boundary.
- `_effective_cwd` ContextVar isn't enforced — easy to omit `with use_cwd(cwd):`.

**Single fix**: adopt `Result[T]` everywhere with `.to_dict()` at the
server layer; `@requires_cwd` decorator for MCP tool handlers; convert
`run_script` `FileNotFoundError` to a structured error result.

### T4. `hooks/session.py` is a 532-line archetype mix
Touched by A7, D2, E1/E3, F1/F9, I3. Mixes Event dispatch + Document
persistence + Rule/Policy enforcement + Place provisioning. Two functions
(`build_reload_context`, `context_compact`) duplicate the same multi-context
data assembly. `_format_decision_guidance` silently falls through on unknown
friction-level strings.

**Single fix**: split into `hooks/session_dispatch.py` (Event), `domain/session_document.py` (already partially exists), `hooks/session_policy.py` (migration + friction rules), `session/queries.py` (`SessionContextQuery`).

### T5. Audit log lives in two modules
Touched by D1, D5, F8, I8. `hooks/audit.py` (349 LOC) provides
`@audit_hook` decorator + `iter_records`/`summarize`/`prune`.
`audit/__init__.py` reimplements `hook_recent` with its own JSONL parser.
`hooks/audit.py` is in the wrong bounded context (it's a reader, not an
event handler).

**Single fix**: consolidate readers into `audit/log_reader.py`; keep
`@audit_hook` decorator in `hooks/audit_emit.py` delegating writes to
the reader's append API.

### T6. Path & format primitives unmodelled
Touched by C1, C5, C6, C8, C10, H4, H6. `~/.claude/...`, ticket IDs,
gitmoji, MCP tool names, skill names, permission rules — all circulate
as `str` with regex/parsing repeated across files. `USERSPACE_CONFIG`
defined identically in 3 files.

**Single fix**: `domain/claude_paths.py`, `domain/ticket_id.py`,
`domain/mcp_tool_name.py`, `domain/skill_name.py`, etc. — small
self-contained value objects.

## Proposed Milestones

Sequenced for risk-first → leverage. Each milestone is independently
shippable; later milestones build on earlier domain types.

### M1 — Concurrency Safety (HIGHEST URGENCY · ~3 days)
Prevent corruption that already affects parallel-agent workflows.
- Lock + atomic-write `~/.claude/settings.json` rewrites in
  `session_migrate_permissions` (Finding #1).
- Wrap `task_plan_sync.cmd_hook` load-mutate-save in `fcntl.flock`
  using existing `skills/permission/file_lock.py` pattern (Finding #2).
- Atomic tmp+rename for `session_persist`, `SKILLS.md`,
  `Registry.save`, config msgpack cache (E3, E4, E5, E6).

### M2 — MCP Boundary Hardening (~3 days)
Close error-contract holes and silent fallbacks. Foundation for the
rest of the work.
- Convert `audit`/`release`/`monitor`/`permission`/`plan`/`skill_index`/
  `utilities` MCP modules to `Result[T]` (Finding #4, T3).
- Convert `subprocess_utils` `FileNotFoundError` → structured
  `ErrorResult` (Finding #5).
- Add `@requires_cwd` decorator (Finding #6).
- Promote `_ensure_*` private functions in `update_paths.py` to public
  API; remove `redirect_stdout` capture in `permission/__init__.py`
  (Finding #3).

### M3 — Test Coverage on Critical Paths (~5 days)
The 38% global coverage gate masks meaningful gaps.
- MCP handler tests: `create_pr`, `update_pr`, `post_summary_comment`,
  `pr_comment_reply` (with `as_bot` assertions), `push_safe`,
  `pr_comments`, `generate_commit_list` (Finding #13).
- `cwd` parameter parametric tests across all CWD-sensitive handlers.
- All 6 `permission investigate` subcommands via `CliRunner`
  (Finding #15).
- `git/__init__.py` async functions (`push_safe`, `create_worktree`,
  `start_split_rebase`).
- `session_reload`, `context_compact`, `build_reload_context`.
- Extract `parse_subagent_status_line` from doc into
  `domain/subagent_status.py` and add tests (PR #71 has no testable
  Python artifact today).

### M4 — Domain Type Safety (~4 days)
Value Objects + Enums to eliminate primitive obsession.
- `ProfileTier`, `FrictionLevel`, `ValidatorRuleId`, `HookPhase`,
  `HookOutcome` as enums (Findings #8, T2).
- `ClaudeDir` constants module — replace 20+ `Path.home() / ".claude"`
  sites; deduplicate triplicated `USERSPACE_CONFIG` (Finding #10).
- `TicketId`, `GitmojiPrefix`, `McpToolName`, `SkillName`,
  `PermissionRule`, `PrReviewThreadId` (Findings #9, T6).
- Introduce `Task` domain object; migrate `PlanSummary.tasks` to
  `list[Task]` (Finding #11).

### M5 — Plan Domain Consolidation (~3 days)
Resolve T1 in one coordinated change.
- Promote `Plan`, `get_plan_path`, `get_toplevel` to `domain/plan.py`.
- Extract `plan/service.py` Transaction layer; deduplicate `archive()`
  between MCP and CLI entry points.
- Move `metadata["archived_at"]` mutation behind `Plan.archive(path)`.
- Define `TaskStatus` enum + transition table.

### M6 — Pattern Promotion (~5 days)
Make implicit patterns named and testable.
- `ValidatorRegistry` class + `ValidatorBase` dataclass (T2).
- `ConfigResolver` Chain of Responsibility for the 3-tier resolution
  documented in `references/config-resolution.md` (Finding #7).
- `ValidatorChain` with per-step decision logging via `@audit_hook`.
- `FrictionStrategy` Protocol + `CompensationFormatter` Protocol —
  collapse the duplicated friction-level branching (F1, F3, F9).
- `SessionFeature` Protocol for the `session-start.py` orchestrator
  (A7).

### M7 — Archetype Boundary Refactors (~7 days, lowest urgency)
Structural splits with no behavioural change.
- Decompose `hooks/session.py` (T4).
- Consolidate audit log reading (T5).
- Reorganize `domain/` into `events/`, `rules/`, `documents/`, `common/`.
- Split `platform/registry.py` into `PlatformCatalog` + `Registry` +
  service.
- Extract `AuditReport` model from `analyze_permissions.main()`
  (Finding #12).

## ADR Candidates

Three findings rise to architectural-decision level and warrant ADRs
once milestone work begins:

- **ADR-0004**: MCP error contract — adopt `Result[T]` universally.
  Triggered by Findings #4, #5, T3.
- **ADR-0005**: ContextVar-based CWD propagation — formalize the
  pattern, mandate `@requires_cwd` enforcement. Triggered by
  Finding #6.
- **ADR-0006**: 3-tier config resolution as Chain of Responsibility —
  single shared resolver replaces 13 inline implementations.
  Triggered by Finding #7.

## Notes

- Phase 1 context detection used existing PR history (`gh pr list
  --limit 50`); no Linear/JIRA tracker is configured for this repo.
- Coverage gate is 38% (`pyproject.toml`), masking the gaps Phase G
  surfaced. Raising the gate is itself an M3 follow-up.
- The repo already has 3 ADRs (`docs/adr/0001`, `0002`, `0003`) — new
  ADRs continue the existing numbering convention.
