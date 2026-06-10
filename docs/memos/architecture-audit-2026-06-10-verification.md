# Architecture Audit Verification Pass — 2026-06-10 (Phases A–I, second run)

Independent re-run of `/Dev10x:project-audit` (all 9 phases, 9 parallel
read-only Explore agents) executed the same day as the per-package
audit recorded in `architecture-audit-2026-06-10.md` (77 issues,
#494–#570, milestones PKG-M1…PKG-M11). This pass was deduplicated
issue-by-issue against that backlog.

**Outcome:**

- **121 raw findings**, ~110 after intra-run merging
- **~45 independently confirm already-filed issues** (table below) —
  strong signal the morning backlog is real, not agent noise
- **~28 new actionable findings** that escaped the morning run's
  per-agent issue caps (agents bundled LOWs and capped at 5–10 issues)
- **2 corrections to the morning memo's "clean bills of health"**
- No new ADRs needed: every HIGH finding is an enforcement gap against
  ADR-0007/0008/0009/0011, not a new architectural question

## Corrections to "clean bills of health"

The morning memo states two clean bills this pass contradicts:

1. **"CWD discipline: no bare `subprocess.run`/`os.getcwd` in
   long-lived paths"** — found `effective_cwd() or os.getcwd()`
   fallbacks in `domain/events/hook_input.py:29`,
   `hooks/permission_diagnostics.py:148`,
   `audit/permissions_model.py:246`, plus bare `subprocess.run` in
   package module `skills/notifications/slack_notify.py:92` (not a
   uv-script) and an unmarked entry-script
   `skills/git_fixup/find_fixup_target.py` (no `# /// script` header,
   so not clearly exempt).
2. **"MCP boundary: zero ADR-0009 violations"** —
   `mcp/roots_tools.py:35` returns bare dicts (no Result envelope),
   and `platform/registry.py:64,149` raises `KeyError`/`ValueError`
   that no MCP wrapper catches.

## New findings — HIGH priority

### N1. Unlocked read-modify-write on settings files (Phase E)

| Site | Location |
|---|---|
| `update_file` | `src/dev10x/skills/permission/update_paths.py:168` |
| `generalize_permissions` | `src/dev10x/skills/permission/update_paths.py:760` |
| `canonicalize_settings_file` (also no backup) | `src/dev10x/skills/permission/doctor.py:131` |
| `doctor_apply_deprecations` / `doctor_enable_group` | `src/dev10x/commands/permission.py:983,1026` |

Five mutators bypass `locked_json_update` while every sibling settings
mutator in the same files uses it. Parallel fanout agents targeting a
shared `settings.local.json` lose updates (lost-update race).
Fix: wrap each in `locked_json_update` + `create_backup`.
Impact HIGH / Effort S each. → PKG-M11.

### N2. Lock & atomicity model drift (Phase A)

- Two lock-sidecar conventions coexist (`file_lock` appends `.lock`;
  `locked_json_update` replaces the suffix) with a prose-only warning —
  silent mutual-exclusion break if both are ever used on one path
  (`src/dev10x/domain/file_locks.py:20-34`).
- `Plan.save()` hand-rolls mkstemp/rename **without fsync**, out of
  sync with canonical `atomic_write_text`
  (`src/dev10x/domain/documents/plan.py:138-161`).
- Multi-file permission migrations have no Unit of Work: a third-file
  failure leaves files 1–2 mutated with no rollback
  (`src/dev10x/hooks/session_policy.py:110-200`,
  `skills/permission/update_paths.py`).

Impact HIGH / Effort S–M. → PKG-M11 (extends #555/#544 theme).

### N3. Daemon PID-file double-start race (Phase E)

`write_pid_file` is a truncate-write with no `O_EXCL`; two
near-simultaneous daemon starts both pass the stale check and the
second overwrites the first's PID — `shutdown_daemon` then kills the
wrong process and leaves a zombie health server
(`src/dev10x/mcp/daemon.py:108`). Impact HIGH / Effort M. → PKG-M2.

### N4. `DEV10X_HOOK_AUDIT_DIR` default-path conflict (Phase C)

Same env var, two fallbacks: `audit/log_reader.py:39` defaults to
`/tmp/Dev10x/logs`; `audit/__init__.py:37` defaults to
`/tmp/Dev10x/hook-audit`. In a default install the reader and writer
use different directories — `analyze_permissions` finds nothing.
Impact HIGH / Effort S. → PKG-M8.

### N5. `ClaudeDir`/`Dev10xConfigDir` bypasses defeat env overrides (Phase C)

`slack_review_request.py:29`, `slack_notify.py:23` hardcode
`Path.home()/".claude"/"memory"/...`; `analyze_permissions.py:110,135`
uses `os.path.expanduser("~/.claude/...")`. All bypass
`DEV10X_CLAUDE_HOME`/`DEV10X_CONFIG_HOME` and lazy migration — tests
can touch production config. Impact HIGH / Effort S. → PKG-M1.

### N6. `PLUGIN_NAMES` regex divergence (Phase C)

Three independent definitions; `clean_project_files.py:42` also
matches bare `dev10x` while `doctor.py:37` and `update_paths.py:42`
do not — observable behavior difference for short-slug projects.
Impact HIGH / Effort S. → PKG-M1.

### N7. GH-315 Bug C: dual permission config files (Phase D)

`merge-worktree`/`clean` read `upgrade-cleanup-projects.yaml` while
six other subcommands read `projects.yaml`
(`skills/permission/update_paths.py:15` documents this as a known,
unfixed bug). User edits to one file silently don't affect some
subcommands. Impact HIGH / Effort M. → PKG-M1.

### N8. `platform/registry.py` raises through the MCP boundary (Phase H)

`PlatformCatalog.lookup()` raises `KeyError`; `get_platform_config()`
raises `ValueError`; no MCP wrapper catches them (ADR-0009 violation,
see correction 2). Impact HIGH / Effort S. → PKG-M7.

### N9. `os.getcwd()` fallback stragglers post-GH-979 (Phase H)

See correction 1. Replace `effective_cwd() or os.getcwd()` with the
`subprocess_utils` sentinel convention. Extends #495 (spec_drift
only). Impact HIGH / Effort M. → PKG-M11.

### N10. MCP tool adapter modules without direct tests (Phase G)

`git_tools.py`, `misc_tools.py`, `roots_tools.py` (extends #556's
audit/plan scope): `cwd` forwarding, result mapping, and error paths
are invisible — tests mock below the adapter.
Impact HIGH / Effort M. → PKG-M10.

### N11. `update_paths.py`: 1,283 lines / 13 tests (Phase G)

`ensure_base_permissions`, `generalize_permissions`,
`purge_dead_glob_script_rules`, `verify_script_coverage` etc. are
untested — the most destructive, highest-churn permission module.
Impact HIGH / Effort L. → PKG-M10.

### N12. Global 75% coverage floor masks 0% packages (Phase G)

`commands/hook.py` (335 lines, 0 tests), `session/queries.py`, and
the MCP tool modules can sit at 0% while the global gate passes. Add
per-package floors. Impact MEDIUM-HIGH / Effort S. → PKG-M10.

## New findings — MEDIUM (bundle candidates)

| ID | Finding | Location (primary) | Effort | Milestone |
|---|---|---|---|---|
| N13 | Template-Method bundle: `_bulk_execute` ×3, repo-resolution boilerplate ×10 (`_resolve_repo` called twice in issue_edit/close/reopen), `gh_json`/`gh_run` ×2, `_restore` ×3, JSON-envelope emit ×3 | `github/__init__.py:1437-1571,1094-1176`; `skills/permission/*`; `hooks/session_dispatch.py` | M | PKG-M11 (extends #541, #557) |
| N14 | MCP wrapper boilerplate ×30 → `@github_tool` decorator | `mcp/github_tools.py` | L | PKG-M2 |
| N15 | Transcript grammar duplicated & diverged (`TURN_RE` trailing group) | `audit/permissions_model.py:25` vs `skills/audit/analyze_actions.py:27` | M | PKG-M8 |
| N16 | Two `RuleMatch` classes — same name, different semantics | `domain/rules/rule_engine.py:21` vs `hooks/permission_diagnostics.py:40` | S | PKG-M11 |
| N17 | `doctor.Catalog` vs `PolicyCatalog` — two loaders for `baseline-permissions.yaml` | `skills/permission/doctor.py:324` | L | PKG-M1 |
| N18 | Missing `permission/service.py` layer; MCP + CLI adapters reach into `skills/permission` directly (`plan/` shows the correct shape) | `permission/__init__.py:30`, `commands/permission.py` | L | PKG-M11 (extends #525, #529) |
| N19 | `session.yaml` has no Document owner — 3 ad-hoc readers/writers; root cause of #513/#515 | `domain/session_rules.py:41`, `hooks/session_policy.py:89`, `commands/init.py:67` | M | PKG-M11 (fix vehicle for #513/#515) |
| N20 | `domain/` imports `subprocess_utils` — layering inversion vs ADR-0008 | `domain/events/hook_input.py:9`, `domain/git_context.py:21` | M | PKG-M4 |
| N21 | `audit_emit._get_writer()` lazy import instead of startup injection (ADR-0008 "cycles hidden behind lazy imports") | `hooks/audit_emit.py:31-38` | S | PKG-M7 |
| N22 | `github_tools.py` mixes GitHub/CI/release tool contexts; `github/slack.py` misplaced | `mcp/github_tools.py:1232-1301`, `github/slack.py` | S | PKG-M2 |
| N23 | Protected-branch set defined in 4 places (canonical `frozenset` ignored); `detect_base_branch` ×3 implementations | `domain/common/branch_name.py:17` vs `validators/pr_base.py:23`, `skills/git_fixup/find_fixup_target.py:71`, `github/__init__.py:766` | M | PKG-M11 |
| N24 | Partial VO adoption: `RepositoryRef` (30+ `repo: str` MCP params), `BranchName` (`push_safe` takes raw strings), `TicketId` (callers re-compile `TICKET_ID_PATTERN`), shared bash-token regexes (`ENV_VAR_RE` ×2, `GIT_C_RE` ×2 with conflicting semantics) | `mcp/github_tools.py`, `git/__init__.py:65`, `validators/commit_jtbd.py:93` | M | PKG-M11 (extends #508, #510, #514) |
| N25 | Validator Protocol gaps: chain should call `should_run`→`validate` (not overridable `run()`); `Corrector` Protocol declared but never isinstance-checked — capability string mis-declaration raises swallowed `AttributeError` | `validators/base.py:49-95`, `validators/registry.py:212-226` | S | PKG-M3 (sibling of #494) |
| N26 | `RuleEngine` rebuilt from YAML on every hook invocation — no mtime-keyed cache | `domain/rules/rule_engine.py:27-83`, `hooks/edit_validator.py` | S | PKG-M3 |
| N27 | `slack_notify.py`: bare `subprocess.run` + `raise RuntimeError` in package code; Slack sends scattered across 3 call sites with 3 error styles | `skills/notifications/slack_notify.py:87-137` | M | PKG-M1 (sibling of #537) |
| N28 | Smaller items: `collect_prs` pure logic untested; `pr_notify` arg-building untested; upgrade-cleanup / git-worktree skills lack evals; `RemovalResult` accumulator anti-pattern; status-string enums (`DeprecationAction`, `McpSourceType`, `FindingScope`); `_write_if_missing` + `migrate_path` TOCTOU; `install_version` lexicographic version sort breaks at 0.10.x (adds evidence to #506); GitHub App key/config non-atomic writes | various | S–M | PKG-M10 / PKG-M1 / PKG-M2 |

LOW-impact items (naming/docs/hygiene: `Task` wither documentation,
`ValidatorFilter`→Specification naming, `Config` placement, logger
naming, `fetch_*` vs `get_*`, bare `import subprocess` in
`session/queries.py`, 4th Rule archetype doc for `cli_friction.Rule`,
`platform/registry.py` Catalog/Registry file split) should ride along
existing LOW bundles (#534, #539, #566) rather than new issues.

## Already tracked — independent confirmation

| This run re-found | Tracked as |
|---|---|
| `session_persist` spawns 5 `GitContext` per call | #552 |
| `collect_prs` N+1 `gh` per ticket | #550 |
| `review_threads` sequential per-PR API calls | #561 |
| `SessionStore.update` lock-release gap (TOCTOU) | #558 |
| `file_lock` blocking flock without timeout | #555 |
| `write_applied_version` raw `write_text` | #544 |
| `init.py` TOCTOU + roots staleness + audit raw write | #562 |
| `skill_metrics` TextIOWrapper append | #548 |
| Policy-rule file I/O (`ReadFrictionLevelRule`, `BuildAutonomyReassuranceRule`) | #513, #515 |
| Policy rules placed in `hooks/` not `domain/` | #524 |
| `_migrate_rules`/`_deduplicate_rules` compat-shim leak | #521 |
| `Plan.metadata` raw dict + `archive_slug` leak | #527 |
| `Finding.metadata` untyped bag, TDA in 4 remediators | #518 |
| `PlaybookDiff`/`PlayDiff` raw string status | #535 |
| Result[T] gaps in `install_version` + skills layer | #533 |
| Config loading: parallel implementations | #536 |
| Logger naming `log`/`logger`/`_log` | #538 |
| Module-level singletons → named Registry | #522 |
| `ValidatorChain` fail-open on validator exceptions | #494 |
| spec_drift ad-hoc ticket regex / bare subprocess | #514, #495 |
| `_version_tuple` duplication | #506 |
| McpToolName parsing scattered | #508 |
| MCP audit/plan tools passthrough-only tests | #556 |
| Fanout swarm dispatch untested | #553 |
| PR lifecycle skills lack evals | #547 |
| `session/queries.py`, commands CLI untested | #568 |
| MCP daemon/StreamableHTTP no integration tests | #563 |
| session_dispatch emit-skeleton duplication | #551, #557 |
| `permission.py` command boilerplate ×8 | #541 |
| Tool-name dispatch ×4 modules | #543 |
| `ci_check_status` dual gh calls, `pr_notify` import | #566 |

One nuance vs #549 (mixed ISO timestamp formats): timezone-awareness
itself is fully consistent (`datetime.now(UTC)` everywhere) — #549's
scope is format strings only.

## Proposed milestone assignment (new findings)

All new findings map onto **existing** PKG milestones — no new
milestone structure:

- **PKG-M1 (skills)**: N5, N6, N7, N17, N27, parts of N28
- **PKG-M2 (mcp)**: N3, N14, N22, parts of N28
- **PKG-M3 (validators)**: N25, N26
- **PKG-M4 (domain)**: N20
- **PKG-M7 (runtime/infra)**: N8, N21
- **PKG-M8 (workflow/audit)**: N4, N15
- **PKG-M10 (tests)**: N10, N11, N12, parts of N28
- **PKG-M11 (cross-cutting)**: N1, N2, N9, N13, N16, N18, N19, N23, N24

Suggested blocking chains: N2 (lock model) blocks N1 (apply locks);
N19 (`SessionYamlDocument`) blocks #513/#515 remediation; N12
(per-package floors) lands after N10/N11 raise the packages it gates.
