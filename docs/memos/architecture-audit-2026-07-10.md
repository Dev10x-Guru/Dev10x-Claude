# Architecture Audit — 2026-07-10 (Phases A–I)

Full nine-phase architecture audit of the Dev10x plugin, run via
`Dev10x:project-audit` with one parallel Explore agent per phase.
Baseline: `architecture-audit-2026-06-10.md` and its verification memo.
Scope: `src/dev10x/` (~38.7k lines, 226 files), `skills/` (82),
`hooks/`, `agents/`, `tests/` (~52.8k lines, 279 files), ADRs 0001–0017.

## Executive Summary

The codebase is in markedly better architectural health than the
2026-06-10 baseline.
The PKG-M1..M11 remediation wave held: the domain dependency rule is
clean (zero domain→infra imports), the Result contract is uniformly
enforced at the MCP boundary, value-object adoption is unusually mature,
and no type leakage or facade bypasses were found.

This pass produced **37 findings: 4 HIGH (1 new), 15 MEDIUM, 18 LOW**.
The dominant theme is no longer missing architecture — it is
**"decision made, not executed"**: accepted standards (ADR-0015
config-io helper, GH-575 path centralization, GH-567 subprocess
timeouts, ADR-0011 atomic writes) exist but stalled at partial
adoption, and the enforcement gap is structural (no lint/CI gate keeps
new code on the standard).
The second theme is a **skill-eval coverage cliff**: Python code ships
with tests, but 26 of 55 decision-gated skills ship with zero eval
assertions.

### Top priorities (Impact HIGH, sorted by effort)

> Adjusted same-day by the post-merge re-verification addendum at the
> end of this memo: the dual permission-catalog finding (D3/N7) was
> resolved by GH-799 and is removed from this list.

| # | Finding | Phase | Effort | Status |
|---|---------|-------|--------|--------|
| 1 | `rule_confidence.py` feedback store: unlocked read-modify-write (lost updates + truncation on crash) | E | S | NEW |
| 2 | `gh-pr-monitor` / `gh-pr-request-review` eval-blind despite 48h-old hardening churn | G | M | NEW |
| 3 | Unresolved-threads repo sweep still N+1 (2 subprocesses/PR; GH-710 fixed only single-PR path) | I | M | carried (partial) |
| 4 | ADR-0015 config-io helper never implemented; `rule_engine.py`/`platform/registry.py` still raise unguarded YAML errors into the hook path | H | L | carried (ADR accepted 2026-06-29) |

### Carried-over reconciliation

- **N7 (dual permission catalog)** — re-verified OPEN (Phase D).
- **N8 (PlatformCatalog raise past MCP boundary)** — **RESOLVED /
  reclassified**. Phases D and H disagreed; orchestrator verification
  confirmed Phase H: `PlatformCatalog.lookup()` is reached only from
  `PlatformRepository.add` (`platform/registry.py:186`) and no `mcp/`
  module imports the platform package (the only "platform" hit in
  `mcp/github_tools.py` is a docstring). The raising path is
  CLI-only (`commands/platform.py`), which legitimately owns exit
  codes. No ADR-0009 violation exists today.
- **N12 (per-package coverage floor)** — OPEN. Remediation PRs added
  tests, not the structural floor.
- **N13/N14 (github wrapper duplication)** — PARTIAL. `@github_tool`
  decorator shipped for the wire layer; the domain-layer run→parse
  skeleton below it is still duplicated ~15×.
- **#541 (permission.py command boilerplate)** — OPEN, verbatim.
- **GH-462 (MCP parameter-name drift)** — OPEN by explicit choice
  (documented as contract in `mcp-tools.md`); tracked separately.
- **GH-538 timestamps, GH-555/572 locking, GH-558/562 async races,
  GH-498/620 daemon PID** — all verified HELD; no regressions.

---

## Findings by Phase

Full per-phase reports (with complete finding blocks) were produced by
the phase agents; this memo consolidates them. Locations are exact as
of `develop` @ 2026-07-10.

### Phase A — Pattern Catalog (3 findings: 1 MEDIUM, 2 LOW)

| ID | Finding | Location | Impact | Effort |
|----|---------|----------|--------|--------|
| A1 | `resource_watcher.py` reimplements the `global/get/set` trio that `SingletonHolder[T]` (GH-522) eliminated in its two sibling modules | `mcp/resource_watcher.py:362-378` | LOW | S |
| A2 | Two independent Plugin-loaders: `ValidatorRegistry` vs doctor `load_strategies`; doctor loader has no metadata-consistency check | `skills/doctor/registry.py:1-15` vs `validators/registry.py:105-184` | MEDIUM | M |
| A3 | Absent session state handled by scattered defaults instead of a Special Case object (`AbsentSessionYaml`) | `session/service.py:106-161` | LOW | M |

Adoption baseline: Gateway, Repository, Registry/Catalog, Singleton,
Plugin, CoR, Strategy, Template Method, Rule/Policy, Value Object,
Special Case (Result), Service Layer, Query Object, Document archetype
all Adopted and mostly ADR-cross-referenced. Observer is Implicit
(resource watcher) and acceptable.

### Phase B — Domain Model Health (3 findings: 1 MEDIUM, 2 LOW)

| ID | Finding | Location | Impact | Effort |
|----|---------|----------|--------|--------|
| B1 | Tell Don't Ask regression: `task_guard.py` re-derives Plan's terminal-task invariant externally (GH-681, landed after prior audit) — add `Plan.would_violate_terminal_task_invariant()` | `hooks/task_guard.py:47-71` | MEDIUM | M |
| B2 | `GateContext` is a zero-method data bag; floors/conditions live in module functions. Likely intentional (ADR-0007 D3 functional core) — needs a documented decision as the toggle surface grows (17 toggles + 5 floors) | `domain/gate_policy.py:178-337` | LOW | L |
| B3 | `Config` document anemic (inert — single consumer) | `domain/documents/config_document.py:10-13` | LOW | S |

Model census: 20+ Rich models, 2 Anemic (one by design, one inert).
Domain layer significantly healthier than baseline.

### Phase C — Value Object Discovery (3 findings: 1 MEDIUM, 2 LOW)

| ID | Finding | Location | Impact | Effort |
|----|---------|----------|--------|--------|
| C1 | `AllowRule` VO exists but 6 permission modules bypass it with ad-hoc `Bash(...)` regexes that already disagree with each other | `skills/permission/{generalize:28, cli_catalog:27, clean_project_files:51+91-111, doctor:590, update_paths:595, merge_worktree_permissions:33-51}` | MEDIUM | M |
| C2 | `(repo, pr_number)` pair threaded through 7+ signatures; no `PullRequestRef` composing the existing `RepositoryRef` | `github/`, `skills/monitor/pr_notify.py` | LOW | L |
| C3 | Gate-policy dual-path (current + legacy) as raw Path literals — fold into GH-812/813 relocation design, no standalone action | `mcp/gate_tools.py:31-32` | LOW | S |

Prior Phase C items (#508, #543) verified shipped.

### Phase D — Archetype Stress Test (6 findings: 1 HIGH carried, 5 LOW)

| ID | Finding | Location | Impact | Effort |
|----|---------|----------|--------|--------|
| D1 | `permissions_model.Finding` mutates `classification` in place — only mutable record in an otherwise immutable Event/Record tier | `audit/permissions_model.py:93-115,447` | LOW | S |
| D2 | ~~N8 platform boundary raise~~ — **RESOLVED** (see reconciliation) | — | — | — |
| D3 | Dual permission-catalog files (N7) — carried-over | `skills/permission/update_paths.py:15`, `permission/service.py` | HIGH | M |
| D4 | No shared `Catalog[T]` Protocol across 3 catalogs — defer until a 4th instance | informational | LOW | M |
| D5 | Party/Role archetype legitimately absent — recorded as checked | — | LOW | n/a |
| D6 | `resolve_gate` follows Policy-Rule invariant but not the `PolicyRule[T]` shape — docstring note or wrap | `domain/gate_policy.py:340-397` | LOW | S |
| D7 | `validation_rule.Rule` not renamed to `MatchingRule` per ADR-0007 naming | `domain/rules/validation_rule.py` | LOW | S |

Positive: audit JSONL log is the reference Event implementation;
Document tier fully aligned.

### Phase E — Concurrency Audit (5 findings: 1 HIGH, 4 MEDIUM)

| ID | Finding | Location | Impact | Effort |
|----|---------|----------|--------|--------|
| E1 | **Global rule-confidence feedback store: unlocked, non-atomic read-modify-write** — concurrent `record_rule_feedback` calls silently lose tallies; crash truncates store. Route through `locked_json_update` | `github/rule_confidence.py:129-163` ← `mcp/github_tools.py:1348` | HIGH | S |
| E2 | Doubt-sink append uses buffered `TextIOWrapper.write` — the exact pattern `append_record`'s docstring calls unsafe; use `O_APPEND` + single `os.write` | `mcp/gate_tools.py:117-122` | MEDIUM | S |
| E3 | `ConfigYamlDocument.write` / `SessionYamlDocument.write_ephemeral` bypass `atomic_write_text` — truncated-read window on cross-worktree files; silent loss (YAMLError swallowed to `{}`) | `domain/documents/session_yaml.py:114-121,249-251` | MEDIUM | S |
| E4 | Two-pass settings migration writes precomputed content under lock without re-read — real lost-update window; ADR-0011's "I/O errors only" claim is wrong for this path | `domain/documents/settings_document.py:68-112` | MEDIUM | M |
| E5 | GH-567 timeouts inconsistently applied — 3 uv-scripts (`ci_check_status`, `find_fixup_target`, `collect_prs`) have unbounded `subprocess.run` in polling/loop contexts | `skills/monitor/ci_check_status.py:90,114,145` et al. | MEDIUM | S |

Verified compliant: file_locks timeout, session_document atomic claim,
daemon PID, audit append, session_store TOCTOU fix, roots_manager
refresh guard, all permission/* locked cycles. No async races found.

### Phase F — Behavioral Pattern Fit (4 findings: 3 MEDIUM, 1 LOW)

| ID | Finding | Location | Impact | Effort |
|----|---------|----------|--------|--------|
| F1 | gh-wrapper run→check→parse skeleton duplicated ~15× in domain layer (below the shipped `@github_tool` wire decorator); already drifting — extract `_run_and_parse` | `github/__init__.py:152-264,838-1152` | MEDIUM | M |
| F2 | `issue_edit/close/reopen` copy-paste repo-resolution + URL tail ×3 — extract `_issue_result` | `github/__init__.py:1164-1330` | LOW | S |
| F3 | `commands/permission.py` ensure-* Click skeleton ×5 (#541 verbatim) — extract `_run_fix` helper | `commands/permission.py:180-303` | MEDIUM | M |
| F4 | `gate_policy._apply_conditions`: 4 identical condition branches — replace with predicate dict before ADR-0016 presets add more | `domain/gate_policy.py:284-311` | MEDIUM | S |

Checked healthy: validator CoR, Slack Observer consolidation,
Command-for-git (reflog is the undo), platform/runner Strategy dicts.

### Phase G — JTBD Coverage Matrix (5 findings: 2 HIGH, 3 MEDIUM)

| ID | Finding | Location | Impact | Effort |
|----|---------|----------|--------|--------|
| G1 | `ddd` skill (GH-771, newest delivery): zero test/eval surface for 4 modes + 7-layer flow + gates | `skills/ddd/` | MEDIUM | M |
| G2 | `session_rules.py` gate-precedence logic (new vs legacy config) has no direct unit test | `domain/session_rules.py` | MEDIUM | S |
| G3 | 26 of 55 decision-gated skills have no `evals/evals.json` (47% of gated skills; 31/82 overall eval coverage) | 26 skill dirs | HIGH (pair below) / MEDIUM rest | L aggregate |
| G4 | Per-package coverage floor still absent (N12/PKG-M10 carried) — global 75% masks thin packages | `pyproject.toml` | MEDIUM | S |
| G5 | `gh-pr-monitor` + `gh-pr-request-review`: eval-blind while #794/#811 hardened exactly this surface in the last 48h | `skills/gh-pr-monitor/`, `skills/gh-pr-request-review/` | HIGH | M |

Theme: "Python with tests" is enforced; "skill orchestration with
evals" is skipped — the gap tracks the newest deliveries.

### Phase H — Cross-Cutting Consistency (5 findings: 1 HIGH, 2 MEDIUM, 2 LOW)

| ID | Finding | Location | Impact | Effort |
|----|---------|----------|--------|--------|
| H1 | **ADR-0015 (Accepted 2026-06-29) never implemented** — `config_io.py` doesn't exist; 19 raw `yaml.safe_load` sites with divergent fallbacks; `rule_engine.py:33` and `platform/registry.py:167` still raise unguarded into the PreToolUse hook path | 19 sites | HIGH | L |
| H2 | ~30 hand-built `~/.claude/...` path literals despite `ClaudeDir`/`Dev10xConfigDir` (GH-575); GH-812/813 relocation will trip over them | permission/, doctor/, hooks/, mcp/, domain/documents/ | MEDIUM | M |
| H3 | Data-retrieval naming: `load_*` (19) / `read_*` (14) / `get_*` (26) interchangeable; CLAUDE.md rule blesses only `get_*`/`fetch_*` — document the exceptions (rename sweep not recommended); 4 duplicate `load_config` definitions | multiple | LOW | S |
| H4 | GH-462 MCP parameter drift — carried-over by explicit choice, tracked | `mcp/github_tools.py:85,105,168` | MEDIUM | tracked |
| H5 | `os.path.*` mixed with pathlib in 8 sites (2 in hot-path validators) — fold into next touch | validators/, skills/ | LOW | S |

Verified resolved: N8 (see reconciliation), GH-538 timestamps clean,
no bare except/sys.exit in domain.

### Phase I — Cross-Context Queries (4 findings: 1 HIGH, 2 MEDIUM, 1 LOW)

| ID | Finding | Location | Impact | Effort |
|----|---------|----------|--------|--------|
| I1 | Repo-wide unresolved-threads sweep: 2 subprocesses × 200 PRs; self-documented as timing out at scale; GH-710 fixed only the single-PR path — batch via chunked GraphQL aliasing | `skills/gh-pr-doctor/scripts/gh-unresolved-threads.py:177-199` | HIGH | M |
| I2 | `resolve_gate_for_toplevel`: ~100-line MCP handler assembling session+config+git+audit inline — extract `GateResolutionQuery` service | `mcp/gate_tools.py:127-227` | MEDIUM | M |
| I3 | `pr_notify` status/prepare: 3 independent gh fetches run serially + mixed github/JTBD/Slack concerns — parallelize + `PRStatusSnapshot` dataclass | `skills/monitor/pr_notify.py:312-365` | MEDIUM | S/M |
| I4 | `_bulk_execute` N+1 (accepted tradeoff) — GraphQL batch only if large batches start timing out | `github/__init__.py:1578-1745` | LOW | L |

No type leakage or facade reach-through found anywhere.

---

## Priority Matrix

**HIGH** (do first, sorted by effort):
E1 (S) → G5 (M) → I1 (M) → D3/N7 (M) → H1 (L) → G3 sweep (L, after G5).

**MEDIUM quick wins (S effort)**: E2, E3, E5, F4, G2, G4.

**MEDIUM standard (M effort)**: A2, B1, C1, E4, F1, F3, G1, H2, I2, I3.

**LOW**: batch opportunistically (A1, B3, C3, D1, D6, D7, F2, H3, H5)
or defer explicitly (A3, B2, C2, D4, I4).

## Proposed Milestones

1. **Concurrency & write-safety** (safety; Phase E) —
   E1 (HIGH), E2, E3, E5 are one afternoon combined; E4 needs a small
   design decision (re-read under lock vs ADR prose fix).
   Plus prevention: reviewer-checklist items "new shared-state file →
   `file_locks`", "new subprocess → `timeout=`".
2. **Standards execution: config-io + paths** (consistency; Phase H) —
   H1 implement ADR-0015 + migrate 19 sites (unguarded 2 first),
   H2 path-literal sweep + CI grep-gates for both standards, H3 naming
   doc fix. Pairs with GH-812/813.
3. **Eval coverage for gated skills** (coverage; Phase G) —
   G5 (HIGH pair first), G1 (ddd), G2, G4, then G3 backlog sweep,
   ordered by last-modified; wire eval-gap detection into skill-audit
   as a standing check.
4. **GitHub gateway refactor** (Phases F/I) —
   I1 (HIGH sweep batching), F1 (`_run_and_parse` extraction),
   F2, I3; same package, natural bundle.
5. **Permission-catalog unification** (Phase D) —
   D3/N7 alone (HIGH, cross-cutting risk deserves its own ticket),
   plus C1 (`AllowRule` adoption) as the adjacent VO cleanup and
   F3 (#541 boilerplate) in the same subsystem.
6. **Domain & pattern polish** (Phases A/B/D) —
   B1 (Plan invariant), A1, A2, D1, D6, D7, F4, B3 — all S/M
   mechanical items, bundleable.

Deferred without tickets: A3, B2 (needs a one-paragraph design note,
not code), C2, C3 (→GH-812/813), D4, D5, I4, H5.

## ADR Impact

No new ADRs required. Two existing ADRs need correction:
- **ADR-0015**: status misrepresents reality — either implement (memo
  milestone 2) or mark superseded/deferred.
- **ADR-0011**: "residual risk = I/O errors only" claim for the
  two-pass migration is incorrect (E4) — correct the prose or fix the
  code to match the claim.
- Optional one-paragraph addendum near ADR-0007: document the
  functional-core exception for `gate_policy.py` (B2/D6).

## Method

Phase 1 context detection (inline + Explore agent), Phase 2 all-phases
selection, Phase 3 nine parallel sonnet Explore agents each primed with
the 2026-06-10 memo to suppress re-reporting of remediated findings,
Phase 4 orchestrator merge with one cross-agent conflict (N8)
resolved by direct source verification.

---

## Addendum: post-merge re-verification (same day)

While the audit ran, a parallel session merged 9 commits to develop
past the audited baseline `b4af62da`: the PERM-M5 PAP/Policy refactor
(GH-797..GH-802) and the session-state relocation (GH-812/GH-813,
new ADR-0018).
A targeted re-verification of every affected finding against
`origin/develop` produced these adjustments:

| Finding | Verdict | Notes |
|---------|---------|-------|
| D3/N7 dual permission catalog (HIGH) | **RESOLVED** | All subcommands resolve via one `resolve_config` chain (`Dev10xConfigDir.projects_yaml()` first); GH-799 added the unifying Policy loader. The two files persist only as an ordered lazy-migration fallback. Divergence may already have been stale at scan time (GH-577). |
| E3 session_yaml non-atomic writes (MEDIUM) | **mostly RESOLVED** → LOW residual | `write_ephemeral` deleted (GH-812); new writers (`friction.yaml` O_EXCL create-only, `write_state` atomic) are clean. Residual: legacy `ConfigYamlDocument.write` (bare `write_text`, `session_yaml.py:251`) appears unreferenced — delete or atomicize. |
| C1 AllowRule regex bypass | STILL VALID | All six regexes remain (doctor.py moved to ~:600). GH-799 added a **seventh** minor instance: `policy_catalog_migration.py:138-140`. |
| F3, D1, C3, G2, A3, I2, E1, B2/F4 | STILL VALID | Unchanged by the 9 commits. |
| H2 path literals | STILL VALID | ~31 literals; `session_yaml.py` literals relocated to `:204`/`:268` as legacy read fallbacks, not removed. |
| H1 config-io absent | STILL VALID, not worsened | New policy modules introduce no new raw `yaml.safe_load` sites. |

New surface (all clean, no anti-pattern repeats): ADR-0018,
`FrictionYamlDocument`, `read_plan_identity`/`write_state` (atomic),
`policy_resolution.py`, `workspace.py`, `policy_catalog_migration.py`,
`policy_authoring.py`, `policy_renderer.py`, `policy_report.py`,
`Policy` lifecycle/scope/assessment fields,
`git_registered_worktrees`.

Net effect on milestones: Milestone 5 loses its HIGH anchor (D3
resolved) and shrinks to the C1 AllowRule-adoption cleanup (now 7
call sites) plus F3 — mergeable into Milestone 6. Milestone 1 drops
E3 to a LOW dead-code cleanup. HIGH findings after adjustment:
E1, G5 (+G3 sweep), I1, H1.
