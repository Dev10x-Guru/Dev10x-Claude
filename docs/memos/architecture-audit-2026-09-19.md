# Architecture Audit — 2026-09-19

Full-project audit of the Dev10x plugin: design patterns, software
archetypes, domain-model health, concurrency safety, test coverage,
cross-cutting consistency, and industry best practices.

Run via `Dev10x:project-audit` with all phases selected, twelve
read-only agents dispatched in parallel.

## What this audit did not cover

Stated plainly so a reader does not mistake silence for a clean bill.

| Phase | Status |
|---|---|
| A, B, D, E, F, J, K, L | Complete, agent-reported, spot-verified |
| C | **Conducted by the orchestrator** after its agent stopped responding |
| G | **Partial** — the JTBD coverage matrix was never produced (carried as ARCH-M6 / #1437) |
| H | **Not received** — reassigned, no findings returned |
| I | **Not received** — reassigned, no findings returned |

Four of twelve dispatched agents stopped reporting. Two phases (C, and
the completed part of G) were re-run directly; two (H, I) were
reassigned to idle agents and did not return findings before this memo
was written.

**Concretely missing as a result:**

- The **module-level import-coupling map** and any dependency cycles
  between top-level modules (Phase I). Nothing here establishes whether
  `src/dev10x/` has import cycles.
- **Duplicated cross-context knowledge** beyond the two instances found
  directly (`McpToolName` bypasses; `repo_stem` verified clean).
- The **error-handling shape map** for `skills/`, `commands/`,
  `github/` and `hooks/` (Phase H). ADR-0009 compliance is verified at
  the MCP boundary and in `domain/` — the layer between them is
  unmeasured.
- The **`friction.yaml` reader inventory** — which readers go through
  `config_io`/`policy_resolution`/`FrictionYamlDocument` and which
  hand-roll `yaml.safe_load`. Given E1, the *writer* side proved to be
  where the defect was, but the reader side remains unchecked.
- A **confirmed count** of remaining bare `subprocess.run`/`os.getcwd`
  in package code. A direct grep found ~16 in-package files
  (`ci_check_status.py` ×5, `pr_notify.py` ×3) but each was not
  individually assessed against the uv-script exemption.

None of these gaps affects the findings that *are* recorded — every
finding above was verified against the source, most of them twice. They
affect only what else might exist.

## Proposed milestones

Prefix `ARCH` (registered in `references/milestone-naming.md`; `AUD` is
closed/archived from the 2026-05-18 series).

**ARCH-M1 — Stop losing data.** E1, E2, E5, J2. The two HIGH findings
plus the corrupt-YAML destroyer that would erase E1's evidence. Every
item is a concurrency defect on shared state, each has a correct
sibling implementation to copy, and none needs a design decision.
Ships first and alone. **Blocks nothing; nothing blocks it.**

**ARCH-M2 — Close the guard gaps.** E3, J1, J3, J5, J6, L5. Six
independent one-hour fixes, all of the form "a rule exists, one place
escaped it". Includes two CI-safety items and the six uv-script
timeouts. Candidate for a single bundle PR. The E3 sweep should land
`bin/check-subprocess-timeouts.py` alongside it, mirroring
`check-dependency-pins.py`, so the class cannot regress.

**ARCH-M3 — Survive a bad night.** L1, L2, L3, L4. Resilience at the
external-call boundary: transient-failure tolerance in the CI poll, a
dead-letter log for notifications, a bounded retry helper, a bulkhead
semaphore, and write-verification on the two wrappers the rules doc
names. Scoped by the unattended `foreman` case, which is where every one
of these costs the most. **Should follow M1** — M1 fixes the daemon
hang that M3's semaphore would otherwise mask.

**ARCH-M4 — Converge on the mechanisms that already exist.** A1, A2,
A3, C1, F1, the `pr_get` alias, plus the low-severity naming bundle.
Pure consistency work: migrate onto `SingletonHolder`, generalize the
`mcp_tool` decorator, route the three `McpToolName` bypasses, extract
`backed_up_write`, and decide `SessionStore`'s fate. **Do A2 before
ARCH-M5's refactors** so new code lands on the generalized decorator.

**ARCH-M5 — Split what has outgrown its file.** B1, B2, D2, D4. The
`session_yaml.py` three-document split, the `update_paths.py` catalog
split, the `GateResolutionQuery.run()` extraction, and the duplicate
plan parser. Deliberately sequenced **before** M7: the team gets
practice on 1,041 and 2,308 lines before attempting 2,918.

**ARCH-M6 — Make the quality gates real.** G1, G2, G3, J8. Evals for
thirteen gated skills, the soft-marker sweep, the coverage matrix this
audit did not produce, and the `fail_under = 75` versus stated-100%
question. J8's doc-budget items ride along.

**ARCH-M7 — The work that needs an ADR first.** D1, F2, J7. Splitting
`github/__init__.py` (XL), the `ChatProvider` extraction (only worth
doing when a third provider or a third cross-ported bug appears), and
designing a deprecation mechanism. **Blocked by ARCH-M5.**

Blocking chain: `M1 → M3`, `M4(A2) → M5`, `M5 → M7`. M2 and M6 are
independent and can run in parallel with anything.

## Verdict

This is a mature, unusually self-documenting codebase. Module docstrings
name their patterns and cite the ADR that established them; three areas
(ADR-0007's rule/policy split, `validators/registry.py`, the `git/`
three-tier split) are reference-quality. The audit found **no security
defect, no unsafe deserialization, no hardcoded secret, and no ADR
violation in the domain layer** across 68 files.

The defects it did find share one shape, and naming it is the most
useful single output of this audit:

> **Almost every finding is a path left outside a mechanism the
> codebase already built correctly.**

| Mechanism that exists and works | The path outside it |
|---|---|
| `file_lock` on `friction.yaml` — 6 writers | `migrate_config.py:130` — **HIGH** |
| `GitContext.run(timeout=…)`, hazard documented | `toplevel`/`branch` — 15 callers, **HIGH** |
| `create_pr` re-reads to verify its own write | ~15 other write wrappers |
| `SingletonHolder` (built to stop this) | 5 hand-rolled singleton trios |
| `@github_tool` decorator | 5 MCP modules hand-copying it |
| `ValidatorSpec` registry | `update_paths.py`'s unformalized ops |
| `McpToolName` (built to stop this) | 3 hand-rolled parse sites |
| Fork guard on 3 Claude workflows | `claude-memory-review.yml` |
| `_SUBPROCESS_TIMEOUT_SECONDS` in 2 uv-scripts | 6 others |
| `pr_number` on 12 PR tools | `pr_get`'s `number` |
| `evals.json` on 54 skills | 13 gated skills without one |

Three findings do **not** fit that shape and need a design decision
rather than a repair: the `github/__init__.py` split (XL, needs an ADR),
the absent resilience primitives (retry / backoff / circuit breaker /
bulkhead — a consistent structural choice, not an oversight), and the
deprecation mechanism, which does not exist in any form.

The practical consequence: most of this backlog needs no design work.
Each fix has a working reference implementation a few lines away, which
is why the milestones below are sequenced **by mechanism** rather than
by module.

## Priority matrix

| # | Finding | Impact | Effort | Milestone |
|---|---|---|---|---|
| E1 | Unlocked global `friction.yaml` writer | HIGH | S | ARCH-M1 |
| E2 | Unbounded `GitContext` blocks the daemon | HIGH | M | ARCH-M1 |
| E5 | `locked_yaml_update` destroys malformed YAML | MEDIUM | S | ARCH-M1 |
| J2 | Same as E1, best-practices view | HIGH | S | ARCH-M1 |
| E3 | 6 uv-scripts with no subprocess timeout | MEDIUM | S | ARCH-M2 |
| J1 | Missing fork guard on a Claude workflow | MEDIUM | S | ARCH-M2 |
| J3 | Version-drift guard skips `pyproject.toml` | MEDIUM | S | ARCH-M2 |
| J5 | No `permissions:` block on a workflow | LOW | S | ARCH-M2 |
| J6 | Silent exception in permission diagnostics | LOW | S | ARCH-M2 |
| L5 | `assert` guards hook-tier classification | LOW | S | ARCH-M2 |
| L2 | One transient `gh` failure kills the CI wait | MEDIUM | S | ARCH-M3 |
| L4 | Notification failures have no dead letter | MEDIUM | S | ARCH-M3 |
| L3 | No retry / backoff / bulkhead | MEDIUM | S+M | ARCH-M3 |
| L1 | Write wrappers do not verify their writes | MEDIUM | M | ARCH-M3 |
| A1 | 5 hand-rolled singletons | MEDIUM | M | ARCH-M4 |
| A2 | MCP boundary decorator not generalized | MEDIUM | L | ARCH-M4 |
| A3 | `SessionStore` — wire it or delete it | MEDIUM | M | ARCH-M4 |
| C1 | `McpToolName` bypassed at 3 sites | MEDIUM | S | ARCH-M4 |
| F1 | Backup+lock idiom copy-pasted 13× | MEDIUM | M | ARCH-M4 |
| H-census | `pr_get` parameter outlier | MEDIUM | S | ARCH-M4 |
| B1 | Two divergent plan-document parsers | MEDIUM | S | ARCH-M5 |
| B2 | 140-line `GateResolutionQuery.run()` | MEDIUM | M | ARCH-M5 |
| D4 | `session_yaml.py` holds three documents | MEDIUM | M | ARCH-M5 |
| D2 | `update_paths.py` catalog god-module | MEDIUM | L | ARCH-M5 |
| G1 | 13 gated skills ship no evals | MEDIUM | M | ARCH-M6 |
| G2 | Soft gate markers the rule replaced | MEDIUM | M | ARCH-M6 |
| G3 | JTBD coverage matrix unproduced | MEDIUM | M | ARCH-M6 |
| J8 | Doc budgets breached without override | LOW | S/M | ARCH-M6 |
| D1 | Split `github/__init__.py` | MEDIUM | XL | ARCH-M7 |
| J7 | No deprecation mechanism | LOW | M | ARCH-M7 |
| F2 | Slack/GChat sibling duplication | MEDIUM | L | ARCH-M7 |

Low-severity naming and hygiene items (A4, A5, A6, B3, B4, D3, D5, D6,
E4, F3, K1) bundle into a single cleanup PR alongside ARCH-M4.

## Scope and method

| Dimension | Value |
|---|---|
| Source | 62,190 LOC across 306 Python files in `src/dev10x/` |
| Tests | 96,915 LOC, 7,246 test functions |
| Skills | 91 skill definitions under `skills/` |
| ADRs | 26 (`docs/adr/0001`–`0026`) |
| Coverage gate | `fail_under = 75` in `pyproject.toml` |
| JTBD record | ~200 merged PRs, `<gitmoji> GH-NNNN <outcome>` titles |
| Tracker | GitHub Issues, `Dev10x-Guru/Dev10x-Claude` |

Twelve phases ran concurrently:

| Phase | Subject |
|---|---|
| A | Pattern catalog (PoEAA / GoF / archetypes) |
| B | Domain model health, ADR-0008/0009 boundary compliance |
| C | Value object discovery |
| D | Archetype stress test |
| E | Concurrency and write safety |
| F | Behavioral pattern fit |
| G | JTBD coverage matrix |
| H | Cross-cutting consistency |
| I | Cross-context coupling |
| J | Industry best practices (SOLID, security, CI/CD, packaging) |
| K | Full archetype catalog sweep |
| L | EIP, concurrency patterns, Python idiom |

## Positive controls

Recording what the audit found to be *correct* matters as much as the
defects: three areas are the codebase's own reference implementations,
and the remediation work below should copy them rather than invent new
shapes.

1. **ADR-0007 rule/policy unification is genuinely implemented.**
   `domain/rules/policy_rule.py`, `validation_rule.py` and
   `rule_engine.py` cleanly separate rule *definition* (`MatchingRule`,
   a frozen dataclass of predicates with no `apply()`) from *evaluation*
   (`RuleEngine`, a pure side-effect-free evaluator) from *effect*
   (`Validator`/`Corrector` protocols in `validators/base.py`). This is
   the strongest-aligned archetype in the repository.

2. **`validators/registry.py` is a real Chain of Responsibility plus
   Strategy**, explicitly named in its own docstrings at lines 61 and
   217. `ValidatorFilter` implementations (`ProfileFilter`,
   `DisableListFilter`, `ExperimentalFilter`) are genuinely swappable;
   `ValidatorChain.run()` accumulates every opinion while
   `ValidatorChain.correct()` short-circuits on the first `HookRetry`.
   Both variants are data-driven over `registry.active()`.

3. **The git three-tier split is exemplary.**
   `domain/git_context.py` (76 lines) is a pure Place/Location primitive
   resolved through the domain CWD seam; `git/__init__.py` (275 lines)
   is the ADR-0013 Gateway; `mcp/git_tools.py` (254 lines) is the MCP
   boundary routing through `to_wire()`. This is the same shape
   `github/` has, at a tenth of the size — which is the argument for
   the `github/__init__.py` split below.

## Phase A — Pattern Catalog

### A1. Hand-rolled singletons regrowing beside the helper built to retire them

`domain/common/singleton_holder.py` exists specifically to stop modules
reimplementing the `global _x` + `get_x()` + `set_x()` trio (its
docstring cites GH-522), and `mcp/session_store.py:368` uses it
correctly. Five further modules hand-roll the identical trio anyway:
`mcp/sampling_manager.py:170,173-175,229-230`,
`domain/cwd_resolver.py:33,36-47`, `hooks/audit_emit.py:29,93-108`,
`skills/notifications/gchat_notify.py:41,57-61`, and
`slack_notify.py:43-44,60-77`.

Tests and callers must know each module's private global name and reach
for `global` mutation rather than a uniform `.reset()`/`.set()` API.

**Fix:** migrate all five onto `SingletonHolder[T]` behind their existing
`get_*`/`set_*` signatures, mirroring `session_store.py`.
**Impact: MEDIUM · Effort: M**

### A2. The MCP boundary decorator was generalized in one module only

`mcp/github_tools.py:20-52` defines a `github_tool` decorator that
factors "enter `use_cwd`, call the domain function, route through
`to_wire()`" into one wrapper applied to ~27 handlers. Five sibling tool
modules hand-write the same boilerplate per handler instead:
`git_tools.py:49-52,74-83,123-126,179-186,218-221,239-242` (with
`use_cwd` re-imported *inside* each function body, five times), plus
`gate_tools.py` (11×), `audit_tools.py` (6×), `task_index_tools.py` (3×)
and `plan_tools.py` (3×).

A future change to the boundary contract needs 20+ edits instead of one.

**Fix:** promote `github_tool` to a general `mcp_tool(fn)` decorator in
`mcp/_app.py`; migrate the five modules; drop the inline imports.
**Impact: MEDIUM · Effort: L**

### A3. `mcp/session_store.py` is fully-built dead scaffolding

`SessionStore` is a complete, thread-safe, TTL-evicting keyed store with
the codebase's best singleton wiring (`SingletonHolder` at line 368) —
and nothing calls it. No `@server.tool()` handler calls `get_store()`,
and `daemon.py` never calls the `bind_to_lifecycle()` its own docstring
documents. A `FIXME(GH-501)` at lines 54-58 marks it as forward-compat
scaffolding for an incomplete "Increment 3".

**Fix:** wire it (call `bind_to_lifecycle` at daemon startup, thread
`session_id` through one real handler) or delete it per the FIXME's own
stated alternative. It is currently pure carrying cost.
**Impact: MEDIUM · Effort: M**

### A4. `create_backup` inline-imported ten times in one file

`skills/permission/update_paths.py` imports
`from dev10x.skills.permission.backup import create_backup` inside ten
separate function bodies (lines 227, 294, 347, 399, 673, and five more)
despite having a module-level import block at lines 33-48.
`backup.py` is a stdlib-only leaf module, so no circular dependency
justifies it — this contradicts CLAUDE.md § 3 with no cycle to excuse it.

**Fix:** hoist to module scope, delete the ten duplicates.
**Impact: LOW · Effort: S**

### A5. `backup.py` implements an unnamed Memento

`skills/permission/backup.py:18-57` provides timestamped `.bak.<ts>`
snapshot plus restore-latest — Memento applied to files. Because it is
unnamed and unstructured, nothing enforces that every mutating path
calls `create_backup` before writing; a new mutator can simply forget.

**Fix:** name the pattern in the docstring and expose a
`with backed_up(path): ...` context manager so the ordering is
structural. (This converges with finding F2 below — do them together.)
**Impact: LOW · Effort: S**

### A6. `RepositoryRef` collides with the Repository pattern vocabulary

`domain/common/repository_ref.py:6-27` is a frozen `(owner, name)` value
object with no `add`/`find`/persistence — one token away from
`PlatformRepository` (`platform/registry.py:154`), a genuine Fowler
Repository in the same codebase, and carrying no disambiguating
docstring.

**Fix:** rename to `RepoRef`/`GitHubRepoRef`, or add a clarifying
docstring line.
**Impact: LOW · Effort: S**

### A7. `stop_verdict.decide()` — watch, do not refactor

`hooks/stop_verdict.py:176-215,903` branches sequentially on five
`StopSignal` outcomes. `.claude/rules/hook-patterns.md` documents *why*
this stays a pure function (testability, GH-1257 evidence gathering).
No action now; revisit as a dispatch table only if it passes ~8-10
branches or gains per-signal side effects.
**Impact: LOW · Effort: S (if ever)**

### Patterns absent

Factory Method, Abstract Factory, Builder, Visitor and Observer have no
instances anywhere in `src/dev10x`. Unit of Work, Data Mapper and
Identity Map are correctly N/A — there is no ORM, only file/YAML-backed
config.

## Phase D — Archetype Stress Test

### D1. `github/__init__.py` is the repository's largest self-rule violation

2,918 lines, ~75 top-level `async def` functions spanning issues, PRs,
milestones, comment threads, labels, bulk operations, triage,
notifications and bot-identity merge resolution — all in one namespace
with no internal module boundaries.

CLAUDE.md § 3 states plainly: "`__init__.py` is for re-exports only — no
logic, classes, or constants." This is the single largest violation of
that rule in the repository, by a wide margin. The module's docstring
correctly names it an ADR-0013 Gateway, but nothing about Gateway
requires one file — one external system does not mean one module.

Cost is threefold: every import of `dev10x.github` loads all 2,918 lines;
eight sibling files (`rule_confidence.py`, `review_patterns.py`,
`candidate_rules.py`, `app_auth.py`, `learn_loop.py`, …) already
received the split treatment this one never did; and locating
`pr_ready`'s implementation is a grep exercise rather than a
`github/pulls.py` guess.

**Fix:** split along the resource boundaries already implicit in the
function names — `_gateway.py` (`_gh_api_raw`, `_gh_api`,
`_run_and_parse`, `_resolve_repo`, `_detect_repo`, `_bot_env`),
`issues.py`, `pulls.py`, `merge.py`, `reviews.py`, `milestones.py`,
`bulk.py`, `notify.py` — leaving `__init__.py` as a ≤50-line re-export
shim. `mcp/github_tools.py`'s `@github_tool` wrapper already isolates
every caller from the internal shape, so the refactor is mechanical and
low-risk.
**Impact: MEDIUM · Effort: XL — needs its own ADR; do not attempt as a
drive-by.**

### D2. `skills/permission/update_paths.py` is a 2,308-line Catalog god-module

One file owns at least ten distinct catalog operations: config loading,
settings-file discovery, `ensure_base`/`ensure_workspace`/
`ensure_scripts`/`ensure_reads`, `generalize`, version-path rewriting,
backup/restore, worktree seeding and legacy-rule collapsing — 59
top-level functions, zero classes.

There is no load/merge/query/validate substructure. `catalog_merge.py`,
`baseline_coverage.py` and `doctor.py` (1,028 lines) sit alongside doing
overlapping catalog-diff work, so "where does catalog logic live" has no
single answer *inside* the package. The sprawl ADR-0025 fixed *across*
the two YAML catalogs still exists *within* this one.

**Fix:** split by sub-archetype — `catalog_load.py`, `catalog_write.py`
(the `ensure_*` fixers), `catalog_version.py`, `catalog_backup.py` —
keeping `doctor.py` as the diagnose-only layer it already is.
**Impact: MEDIUM · Effort: L**

### D3. The "four permission locations" are a correct layered split — with one naming collision

The audit brief suspected sprawl across `permission/`,
`skills/permission/`, `commands/permission.py` and
`audit/permissions_model.py`. Three of the four are a correct ADR-0008
layering: `commands/permission.py` (CLI) and `permission/__init__.py`
(MCP) are thin adapters over `permission/service.py`, which delegates to
the `skills/permission/*` catalog package.

The fourth is unrelated. `audit/permissions_model.py` parses **session
transcripts** for observed friction and never touches `settings.json` —
Transaction/Event analysis, not Catalog mutation. Its docstring already
records that it was moved out of `skills.audit.analyze_permissions` to
fix an audit→skills inversion.

The defect is vocabulary, not architecture: a grep for "permission"
returns four unrelated hit clusters.

**Fix:** rename `audit/permissions_model.py` →
`audit/friction_transcript_model.py`.
**Impact: LOW · Effort: S**

### D4. `domain/documents/session_yaml.py` holds three documents under one filename

1,041 lines containing `FrictionYamlDocument` (global
`~/.config/Dev10x/friction.yaml`, cross-repo, with `ReapReport` /
`reap_dead_projects` GC semantics), `ConfigYamlDocument` (per-repo
durable) and `SessionYamlDocument` (per-worktree ephemeral), plus free
functions `repo_stem`, `match_globs_for_repo`, `upsert_project_prefs`
and `set_playbook_modes`.

Three documents of genuinely different lifetimes and different
read/write/migrate/lock needs. `FrictionYamlDocument` — a global catalog
with reap semantics — is structurally closer to a Catalog than to a
session Document. The module docstring describes "two sibling
documents"; the third is not mentioned at all.

**Fix:** split into `friction_yaml.py`, `config_yaml.py` and a
`session_yaml.py` that actually contains only `SessionYamlDocument`.
**Impact: MEDIUM · Effort: M**

### D5. ADR-0013's Gateway rule is bypassed by `skills/notifications/_gh.py`

ADR-0013 states callers must go through the Gateway and never invoke
`gh` or `subprocess.run` directly. `_gh.py:23-33` calls
`subprocess_utils.run(["gh", *args], ...)` directly, reimplementing a
miniature JSON gateway (timeout constant, `GhCommandError` wrapping,
`json.loads`) rather than importing `dev10x.github`'s existing
`_gh_api_raw`/`_run_and_parse`. Used by both `slack_review_request.py`
and `gchat_review_request.py`.

A future gateway-wide change — bot-auth routing, a retry policy — must
be applied twice to stay correct.

**Fix:** import the existing Gateway function, or promote `gh_json` into
`dev10x.github` and have `_gh.py` import it.
**Impact: LOW · Effort: S**

### D6. `commands/permission.py::clean()` carries business logic a CLI adapter should not

Most subcommands correctly delegate via the `_run_fix`/`_require_settings`
helpers at lines 75-108. `clean()` at lines 508-621 instead inlines ~110
lines of loop and aggregation logic — iterating `settings_files`, calling
`mod.clean_file`, accumulating `total_removed`/`total_secrets`/
`total_global_dedup`, building warning strings — directly in the Click
handler, unlike `merge_worktree` and `ensure_ignored` which delegate
their own multi-file loops.

It is consequently the least testable command in the file.

**Fix:** extract `clean_project_files.run_clean(...) -> CleanRunResult`;
leave `clean()` a thin printer.
**Impact: LOW · Effort: S**

## Phase F — Behavioral Pattern Fit

### F1. The backup-plus-locked-write idiom is copy-pasted thirteen times

`skills/permission/update_paths.py:221-230,293-297,346-350,398-402,
672-676,858-862,887-891,982-986,1104-1108,1268-1272` and
`skills/permission/doctor.py:256-261,796-808,841-849` each repeat the
same five-line shape: skip when `dry_run`, import `create_backup` and
`locked_json_update`, back up, then open a locked update.

No shared abstraction enforces "always back up before a locked write",
so the safety property rests on copy-paste discipline rather than
structure. Worse, the thirteen copies are *not* equivalent: some
correctly re-run the whole transform under the lock for TOCTOU safety
(`doctor.py:801-808`), others mutate the already-loaded dict directly
(`update_paths.py:298-309`). A new mutator that omits the backup is a
silent regression no test catches structurally.

**Fix:** a `backed_up_write(path, dry_run=...)` context manager owning
`create_backup` + `locked_json_update` + the dry-run short-circuit.
Collapses ~65 duplicated lines to thirteen one-line call sites and turns
"did we forget the backup" into a type-level question. Subsumes A5.
**Impact: MEDIUM · Effort: M**

### F2. Slack and Google Chat modules are near-identical with no shared base

`skills/notifications/slack_review_request.py:32-208` and
`gchat_review_request.py:23-89` have structurally identical
`load_yaml`, `_repo_name` and `resolve_project_config` control flow —
the same three-branch shape (project entry with skip → skip; not found
with `default_action == "skip"` → skip; else → ask) — differing only in
the provider-specific fields returned (`channel`/`mentions` vs
`space`/`mentions`/`card`/`preview`). `resolve_mention` is the same
lookup-then-fallback with a different token spelling (`<@id>` vs
`<users/id>`). `cmd_prepare` runs the same gh-fetch → resolve → format →
print-JSON skeleton in both. `slack_notify.py` (580) and
`gchat_notify.py` (545) repeat the pattern at module scale.

The cost is already visible: `gchat_review_request.py:83-89` cites
GH-1307 as a fix applied there, with no evidence it was cross-checked
against the Slack sibling.

**Fix:** a `ChatProvider` protocol with `format_mention`, `token_lookup`
and `resolution_fields`, hoisting `load_yaml`/`_repo_name`/the
three-branch resolver/`cmd_prepare` into a shared
`review_request_base.py`.
**Impact: MEDIUM · Effort: L — worth doing on the next provider, or on
the next cross-ported bug fix, whichever comes first.**

### F3. `doctor.py::apply_deprecations` action dispatch

`skills/permission/doctor.py:639-720` loops over compiled deprecation
patterns then branches `remove` / `canonicalize` / `rewrite` / unknown,
each branch duplicating the same four-line outcome-append-and-dedup tail
(lines 675-719).

**Fix:** one `_apply_one(...) -> DeprecationOutcome | None` per action in
a `dict[str, Callable]`, mirroring `validators/registry.py:58-102`, with
the dedup tail factored out once.
**Impact: LOW · Effort: S**

### Deliberately not reported

`ci_check_status.is_terminal`, `stop_verdict.decide` and `gate_policy.py`
were assessed and rejected as Strategy/State candidates. They are
already well-factored guard-clause chains with named early returns and
per-branch docstrings; converting them would add indirection without
removing duplication or a bug class.

## Phase J — Industry Best Practices

No HIGH findings. No hardcoded secrets, no `shell=True`, no unsafe
`yaml.load`, no `pickle`, and GitHub App credential handling
(`commands/github_app.py`) is correct — `atomic_write_text` inherits
`mkstemp`'s 0600 default, an explicit `os.chmod(0o600)` follows, `status`
warns on a wrong mode, and no error message echoes key material.

### J1. `claude-memory-review.yml` is missing the fork guard its three siblings carry

`.github/workflows/claude-memory-review.yml:1-22` triggers on
`pull_request: types: [closed]` for any PR including forks, grants
`contents: write`, `pull-requests: write`, `issues: write`,
`id-token: write`, and runs `anthropics/claude-code-action` twice. Its
job-level `if:` excludes drafts and reverted titles only.

`.claude/rules/github-workflows.md` § "Fork PRs Cannot Mint an OIDC Token
(GH-1226)" prescribes
`!github.event.pull_request.head.repo.fork` on every job using that
action, and `claude.yml:18-20`, `claude-code-review.yml:39-41` and
`claude-pr-hygiene.yml:26-28` all carry it.

Because the trigger is `pull_request` rather than `pull_request_target`,
GitHub withholds the API key on a fork run, so this fails loud rather
than leaking. But it is a permanently-red job on every merged fork PR —
precisely the "trains reviewers to ignore red CI" failure the same rules
file warns about.

**Fix:** add the documented fork guard.
**Impact: MEDIUM · Effort: S**

### J2. `friction.yaml` is written without the lock discipline the project mandates

`skills/permission/migrate_config.py:129-130` calls
`friction.path.write_text(content)` directly.

`.claude/rules/mcp-tools.md` § "Concurrency conventions" (GH-827,
ADR-0011) requires every write to shared state under `~/.config/Dev10x/`
to route through `domain.file_locks`, and states that "a bare
`write_text` truncates on crash." `friction.yaml` is the canonical
example of such state — durable, cross-worktree, cross-session.

**Fix:** `atomic_write_text`, or `locked_yaml_update` if read-modify-write
semantics are needed against concurrent `pin_*` writers.
**Impact: MEDIUM · Effort: S**

### J3. The version-drift guard never checks `pyproject.toml`

`tests/test_manifest_versions_agree.py:56-114` asserts `plugin.json` and
`marketplace.json` agree, that `.bumpversion.toml` lists
`marketplace.json`, and that `bin/release.sh`'s `VERSION_FILES` covers
everything `.bumpversion.toml` touches.

`.bumpversion.toml:32-35` also rewrites `pyproject.toml`'s version — and
nothing compares it to `plugin.json`. The test file's own docstring
records a release (0.100.1) that failed mid-flight leaving files
partially bumped, which is exactly the failure this gap would miss for
the PyPI-vs-plugin pair.

**Fix:** add a fourth cross-check.
**Impact: MEDIUM · Effort: S**

### J4. `slack-sdk` is a mandatory base dependency the code treats as optional

`pyproject.toml:22-27` declares `slack-sdk>=3.21,<4` as a hard runtime
dependency with a GH-483 comment justifying it. The module's own
docstring (GH-917) says the opposite: `slack_sdk` is an optional fast
path, every message path falls back to `call_slack_api` over stdlib
`urllib`, and file uploads are the sole SDK-only route.
`slack_notify.py:171-182` already guards the import and logs
"slack_sdk unavailable — using the stdlib HTTP Slack transport";
line 388 gives an actionable error for the upload path alone.

The packaging comment predates GH-917 and was never revisited, so every
`uvx dev10x` and `pip install Dev10x` user pays for a dependency only
file upload needs.

**Fix:** move to a `slack` extra; update the stale comment.
**Impact: MEDIUM · Effort: S**

### J5. `github-contract-tests.yml` declares no `permissions:` block

`.github/workflows/github-contract-tests.yml:26-46` inherits the
repository default `GITHUB_TOKEN` scope while needing only
`contents: read`. Every other workflow in the repo declares explicit
minimal permissions.
**Impact: LOW · Effort: S**

### J6. `_run_permission_diagnostics` swallows every exception silently

`commands/hook.py:157-174` catches `except Exception:` and prints a
traceback only under `_DEBUG`. This function drives the PermissionDenied
diagnostic shown to the user, so a regression degrades the feature to a
no-op with no trace in the audit JSONL log the project otherwise relies
on for hook observability.

**Fix:** log with `exc_info=True` outside `_DEBUG` too, as
`mcp/resource_watcher.py` already does correctly.
**Impact: LOW · Effort: S**

### J7. Deprecation is entirely ad hoc

No `DeprecationWarning`, no `warnings.deprecated`, no shared decorator,
no removal-version field anywhere in `src/dev10x/`. Each deprecated
alias and legacy read path is hand-coded with an inline GH reference and
prose such as "still read as a fallback for one release" — which nothing
machine-checks. `human_review_status` was deprecated at GH-1161 in
v0.97.0 and is still present at v0.106.0, nine minor versions later.

**Fix:** a `@deprecated_since(version=, removed_in=, replacement=)`
marker plus a test that fails once `pyproject.toml`'s version reaches
`removed_in`, so a stale shim becomes a build failure.
**Impact: LOW · Effort: M**

### J8. Documentation budgets are breached without the required override annotation

`.claude/rules/INDEX.md` § "Budget Overrides" requires reviewers to flag
any over-budget file with `[OVERRIDE DETECTED]`, a cohesion
justification and a conditional split plan. `mcp-tools.md` does this
correctly. Two files do not:

- `CLAUDE.md` — 148 lines against its own stated 100-line cap.
- `.claude/rules/hook-patterns.md` — 458 lines against the 200-line
  rule-file budget, 2.3×, the largest unexplained breach in the tree.

Separately, `INDEX.md:39` advertises `essentials.md` as "~36 lines"; it
is 158 — a 4.4× understatement of always-loaded context cost, caused by
the Task List Invariant and GH-1055 sections growing without the index
being updated.

**Fix:** trim or annotate both files; drop hardcoded line counts from the
index in favour of a CI `wc -l` check, mirroring the manifest-drift guard
already in the repo.
**Impact: LOW · Effort: S (CLAUDE.md) / M (hook-patterns.md)**

### J9. Also verified correct

- **`mcp` as a dev-only dependency is not a defect.** `servers/cli_server.py:1-4`
  is a self-contained PEP 723 uv-script declaring its own
  `mcp>=1.0,<2`, inserting `src/` on `sys.path` and importing
  `dev10x.mcp.server_cli` from the source tree. It never relies on the
  installed wheel's dependency set. This works because plugin
  distribution ships the repo, not a wheel.
- **`ci-gate.yml` is well designed** — `if: always()` plus
  per-dependency result aggregation correctly solves the path-filtered
  required-check deadlock (ADR-0024).
- **`anthropics/claude-code-action` is SHA-pinned** with a version
  comment everywhere it is used.
- **Subprocess timeouts** — seven call sites spot-checked across
  `pr_notify.py`, `watchdog.py`, `slack_review_request.py`,
  `find_fixup_target.py` and `fixes_scope.py`; all pass explicit
  `timeout=`.

## Phase B — Domain Model Health

The domain layer is clean on the axes that matter most. Verified across
all 68 `domain/*.py` files and 90+ types:

- **ADR-0008 holds.** Zero imports of `subprocess_utils`, `dev10x.mcp`,
  `dev10x.commands`, `dev10x.skills`, `click` or `mcp` anywhere under
  `domain/` — only docstring cross-references.
- **ADR-0009 and script-domain-boundaries hold.** Zero `print()` and
  zero `sys.exit()` under `domain/`. Every `raise` site
  (`gate_policy.py`, `session_yaml.py`) is a malformed-input
  `ValueError` caught and converted to `err()` at the MCP boundary
  (`mcp/gate_query.py:357`).
- **Every `@server.tool()` handler routes through `to_wire()`**, across
  all twelve `mcp/*_tools.py` modules, including the 48
  `@github_tool`-wrapped handlers — the decorator centralizes it at
  `mcp/github_tools.py:20-49`. No bare-dict returns.

Most domain types here are deliberately anemic *functional-core* value
objects — `GateContext`, `SensitivityPattern`, `RunCandidate` are pure
inputs to pure resolvers, matching ADR-0007 D3. Anemia is not the defect
in this codebase; **converting a typed object to a dict mid-pipeline and
re-parsing it by hand downstream** is.

### B1. Two divergent parsers of the same plan-document shape

`domain/session_document.py:81` calls `Plan.load(...).to_dict()`,
discarding the typed `Plan`. `read_plan_identity` (`:84-105`) then walks
the resulting dict by hand — `summary.get("plan")` → `.get("context")`
→ `.get("tickets")` with hand-written isinstance guards — to rebuild
`{"branch":…, "tickets":[…]}`.

`PlanContext.from_dict` already exists at
`domain/documents/session_state.py:114` and parses that same shape. Two
independent parsers of one document can silently diverge, and this is an
actively-evolving area (GH-812, GH-978).

**Fix:** have `read_plan_identity` consult `PlanContext.from_dict`, or
add a `Plan.identity()` method.
**Impact: MEDIUM · Effort: S**

### B2. `GateResolutionQuery.run()` is a 140-line method mixing five safety concerns

`mcp/gate_query.py:229-370` performs unknown-field filtering, legacy-key
refusal, preset/overlay resolution, the GH-805 `allowed_overlays`
durable-mode guard, `session_adoption` staleness computation,
`supervisor_review`/`supervisor_cleared` override logic, `GateContext`
construction, and the `resolve_gate` call with exception→Result
translation — in one body.

Every step is safety-relevant (ADR-0022 D-2, GH-805, GH-978), and inline
comments are currently the only thing separating them.

**Fix:** extract `_resolve_overlays(...)` and
`_resolve_supervisor_policy(...)` as named steps; `run()` becomes their
composition. Pure refactor, verifiable against the existing gate-policy
suite.
**Impact: MEDIUM · Effort: M**

### B3. `RunCandidate` is typed, then immediately erased

`domain/watchdog.py:161` calls `.as_dict()` on every candidate before
returning, so `_wake_reason` (`:213`) and `_wake_candidates` (`:287`)
read facts back out with `candidate["run_dir"]` and re-parse the ISO
timestamp with `_parse_iso` — duplicating null/format handling for no
boundary reason, since the real `Result[dict]` boundary is only the
final `ok(...)`.

**Fix:** thread `list[RunCandidate]` through; call `.as_dict()` once at
the boundary; move `_wake_reason` onto the type.
**Impact: LOW · Effort: S**

### B4. `PolicyCatalog` has no query surface

`domain/common/policy.py:262-322` returns a plain `list[Policy]`, so
three call sites independently filter on `policy.effect is
PolicyEffect.ALLOW`/`DENY`
(`skills/permission/policy_renderer.py:48`,
`policy_catalog_migration.py:29,34`). The allow/deny partition is domain
knowledge reimplemented per caller.

**Fix:** `Policy.is_allow`/`is_deny`, or
`PolicyCatalog.partition_by_effect`.
**Impact: LOW · Effort: S**

### B5. Path registries are an accepted exception

`domain/claude_paths.py:33-157` and `dev10x_paths.py:87-261` are plain
classes with 20+ trivial Path-returning classmethods and real caching.
Not a defect — a deliberate single-source-of-truth Registry — but noted
so a "N rich domain types" rollup does not overstate behavioural
density.
**No action.**

## Phase L — Integration Patterns, Concurrency, Idiom

### L1. "A write is a request, not a receipt" is documented policy, not enforced code

`.claude/rules/mcp-tools.md` (GH-1099) instructs callers to re-read the
specific field after `update_pr`, `pr_ready`, `pr_close`, `issue_*`,
`milestone_*` and `push_safe`. In the implementation, **only `create_pr`
does this** — `github/__init__.py:1391-1411` reads the body back and
reports `fixes_trailer_verified`.

The other ~15 write wrappers check `returncode != 0` and then build the
success payload **from the arguments they were given**:
`update_pr` (`:1415-1463`), `pr_ready` (`:1700-1745`), `pr_close`
(`:1748-1797`), `milestone_close` (`:1856`), `milestone_reopen`
(`:1931`), `milestone_edit` (`:1966`), `issue_edit` (`:2116`),
`issue_close` (`:2193`), `issue_reopen` (`:2240`).

`pr_ready` is the sharpest case and was verified directly: line 1745
returns `{"draft": undo}`, where `undo` is the input parameter. The field
**cannot disagree with the request**, so it carries no information about
what GitHub did — while looking exactly like confirmation. A caller who
does not already know the rule reads a plausible receipt for a write that
may never have landed.

**Fix:** push the re-read into the wrappers the rules doc names as
needing it (`update_pr` body/title, `pr_ready` draft state), the way
`create_pr` already does; or add a test asserting that a wrapper
claiming verification performs a follow-up read, so this stops being
tribal knowledge held in prose.
**Impact: MEDIUM · Effort: M**

### L2. One transient `gh` failure discards the whole CI wait

`skills/monitor/ci_check_status.py:219-221` — `read_checks()` calls
`_abort()` → `sys.exit(1)` on any non-zero `gh pr checks` exit whose
stderr is not the recognized "no checks" shape. `poll_until_terminal`
(`:593-690`) calls it through `probe_once` on **every** iteration.

So a rate limit, a network blip or a token refresh at poll 30 of 40
kills the invocation, discarding `initial_wait` plus thirty poll
intervals, and hands the orchestrator a hard infra failure for a
transient condition. The loop is otherwise carefully budget-clamped
(GH-1288) and tolerates `empty`/`pending` indefinitely within budget —
it has zero tolerance for one failed exec.

**Fix:** treat a transient probe failure as "pending, retry next
interval" with a small consecutive-failure ceiling, mirroring
`fetch_mergeable`'s existing return-`UNKNOWN`-on-failure convention two
functions above in the same file.
**Impact: MEDIUM · Effort: S**

### L3. No retry, backoff, circuit breaker or bulkhead at the external-call layer

Timeouts are excellent and consistently applied (GH-824, and GH-1304's
process-group kill). Everything else is absent:

- **No retry/backoff.** `_gh_api_raw` and `call_slack_api`
  (`slack_notify.py:187-225`) are single-shot. A Slack 429 is caught
  generically with no `Retry-After` handling.
- **No circuit breaker.** No failure-count or open/half-open state
  anywhere.
- **No bulkhead.** `subprocess_utils.py:222-403` has no concurrency cap,
  and there is no `Semaphore` of any kind under `src/dev10x/`. Yet
  `.claude/rules/mcp-tools.md` states plainly that MCP tools "run in a
  long-lived daemon and are hit concurrently by parallel worktrees and
  agents." Several worktrees each running `fanout`/`foreman` crews can
  therefore launch dozens of simultaneous `gh api` subprocesses —
  GitHub's secondary rate limits key off concurrent burst volume, and
  the lockout would hit the whole install.

This is a consistent structural choice rather than an oversight in one
place, which is why it is one finding and not three. It matters most in
the one mode where nobody is watching.

**Fix:** a bounded shared retry helper in `subprocess_utils`, wired into
`_gh_api_raw` and `call_slack_api`; plus an `asyncio.Semaphore` (8–16
permits, env-configurable per the `DEV10X_MCP_*` convention) at the
subprocess-spawn chokepoint — `subprocess_utils` already calls itself
the Gateway to the OS boundary, so owning concurrency shaping belongs
there alongside CWD routing and timeouts. Bound it explicitly; GH-1288's
principle is that the transport ceiling, not caller patience, sets the
limit.
**Impact: MEDIUM · Effort: S (bulkhead) + M (retry)**

### L4. Notification failures have no dead-letter channel

`slack_notify.py:284-330` and `github/__init__.py:2799-2854`
(`pr_notify`) return `Result.err(...)` on failure. Nothing persists the
failed message, queues it, or writes it anywhere durable — the error
exists only in that call's return value.

In an attended session an agent surfaces it. Under `foreman`'s
unattended overnight crews, a lost "crew stalled" or "PR ready"
notification is silently gone unless the calling prompt checks the
`ErrorResult` and escalates by some other route, and no such fallback
exists in the helpers themselves. This is the one execution mode where a
human is least likely to notice.

**Fix:** an append-only failed-notification JSONL under
`~/.config/Dev10x/` via `atomic_append_line`, so a lost signal is at
least discoverable after the fact.
**Impact: MEDIUM · Effort: S**

### L5. `assert` guards a security-relevant classification

`validators/registry.py:199-207` uses `assert` to check that each
validator class's declared `rule_id`/`profile`/`experimental` match the
spec it was registered with. Under `-O`/`PYTHONOPTIMIZE` those
statements vanish, and a mismatch — which gates hook enforcement tier —
would stop being caught. Nothing in the repo currently runs optimized,
so this is theoretical today.

**Fix:** `if not ...: raise AssertionError(...)`.
**Impact: LOW · Effort: S**

### L6. The skill-redirect router keeps two sources of truth — already mitigated

`validators/skill_redirect.py:358-424` gates every command through a
hard-coded `_QUICK_TOKENS` frozenset before the data-driven `RuleEngine`
runs. A YAML rule naming none of those tokens can never fire, however
correctly written. The file's own comments cite three real incidents of
exactly this (GH-1211/1212, GH-1337).

`unreachable_patterns()`, `format_unreachable_report()` and
`test_literal_pattern_contains_a_quick_token` now guard it, which is a
genuine mitigation. No action needed — but if a fourth incident of this
shape appears, derive `_QUICK_TOKENS` from the literal YAML patterns at
load time and delete the second source of truth. Regex patterns already
opt out correctly via `_REGEX_METACHARS_RE`.
**Impact: LOW · Effort: M (only if pursued)**

### L7. Verified non-finding — CWD binding is task-local, not process-global

The audit brief hypothesized that two concurrent MCP handlers from
different worktrees could read each other's bound CWD, which would be
HIGH. **They cannot.** `subprocess_utils.py:37` declares
`_effective_cwd` as a `ContextVar`, and `use_cwd` (`:49-75`) brackets it
with proper `set`/`reset` token handling. ContextVar values are
per-asyncio-Task — each Task copies the ambient context at creation and
mutations inside one Task are invisible to others — which is the correct
primitive for per-request isolation in a long-lived asyncio server.
`safe_effective_cwd` (`:114-143`) and `resolve_script_path` (`:188-219`)
both read through the same per-task value.

The module's GH-979 docstring names this exact scenario as the reason
`ContextVar` was chosen over a module global. Recorded because a
plausible high-severity concern being *closed* is a result worth
keeping.

## Phase E — Concurrency and Write Safety

### Shared-state inventory

| Path | Locked? | Atomic? | Verdict |
|---|---|---|---|
| `~/.config/Dev10x/friction.yaml` | **mixed** | **mixed** | **UNSAFE** — six writers lock, one does not |
| `~/.config/Dev10x/projects.yaml` | `file_lock` | yes | safe |
| `.claude/settings.local.json` family | `locked_json_update` throughout | yes | safe |
| worktree settings fresh-create (`update_paths.py:1847`) | none | no | benign — guarded create, identical content |
| `~/.config/Dev10x/task-index/<repo>.yaml` | `locked_yaml_update` | yes | safe |
| `plan.yaml` | `file_lock` (both writers) | yes | safe |
| rule-confidence store | `file_lock` | yes | safe |
| `watchdog-state.json` | `file_lock` spanning read→fire→write | yes | safe, deliberately TOCTOU-proof |
| config `.msgpack` cache | none, by design | yes | safe — regenerable per `performance.md` |

### E1. `migrate_config_to_friction` writes the global config with no lock and no atomic rename

**This is the audit's most serious defect.**
`skills/permission/migrate_config.py:115-130` performs a full
read-modify-write of `~/.config/Dev10x/friction.yaml` — the **global,
cross-repo** durable config — using a bare `write_text`. It takes no
lock and does not use `atomic_write_text`.

Every other writer of that file locks correctly:
`session_yaml.py:498,556,647,701` (`seed_safe_baseline_if_absent`,
`upsert_project_prefs`, `reap_dead_projects`, `set_playbook_modes`) and
`config_migration.py:426,501`. `upsert_project_prefs` is the write path
behind `pin_gate_preset`, `pin_tracker`, `pin_ide` and
`pin_supervisor_review`.

A lock excludes nobody from a writer that never asks for it. Concrete
interleaving:

- **T0** — process A (`upgrade-cleanup migrate-config`) reads the whole
  document unlocked at line 115.
- **T1** — process B, an MCP `pin_gate_preset` from another worktree,
  takes `file_lock`, adds its `projects[]` entry X, atomic-writes,
  releases.
- **T2** — process A renders its stale T0 snapshot plus its own entry Y
  and `write_text`s it.

**X is gone.** The parity check at `migrate_config.py:132-137` verifies
only that *A's own* prefs landed, so the function reports success while
having destroyed another repo's durable pin. The loss is
indistinguishable from the pin never having been made. The non-atomic
write adds a second failure: a crash mid-write truncates the config for
every repo on the machine, not just A's.

**Fix:** wrap the read-modify-write in `with file_lock(friction.path):`
and write through `atomic_write_text`, mirroring
`session_yaml.py:upsert_project_prefs`. The `matched()` parity check
must move inside the same lock.
**Impact: HIGH · Effort: S**

### E2. `GitContext.toplevel`/`.branch` block the daemon's event loop, unbounded

`domain/git_context.py:61-76` — `GitContext.run()` takes a `timeout`
parameter and its docstring states the reason exactly: *"`timeout`
bounds the call so a wedged git (a stale index.lock, an unreachable
network remote) cannot hang a request served by the long-lived MCP
daemon… Callers on a request path MUST pass one."*

The hazard was therefore understood and fixed — on `run()`. It was
missed on the two members the async handlers actually call.
`toplevel` (`:37-47`) and `branch` (`:49-59`) accept no timeout at all
and invoke `subprocess.check_output` unbounded.

Those are called **synchronously inside `async def` handlers**:
`mcp/gate_tools.py:138` (`resolve_gate`), `:184`
(`preset_pin_status`'s callee), and `mcp/gate_query.py:168`
(`_supervisor_cleared`). `subprocess.check_output` is blocking OS I/O;
running it in a coroutine body rather than off-loop blocks the *whole*
event loop.

Concrete interleaving: worktree A calls `resolve_gate`; its
`git rev-parse` wedges on a stale `.git/index.lock` or a stalled network
mount. Every concurrent tool call from worktrees B and C sharing that
daemon — including entirely unrelated ones — is frozen for the duration,
with nothing to bound it.

A secondary defect rides along: both properties catch only
`CalledProcessError` and `FileNotFoundError`, so adding `timeout=`
without widening the `except` to include `subprocess.TimeoutExpired`
converts a hang into an unhandled exception.

**Scope is wider than three call sites, and the cause is structural.**
A follow-up sweep of all 25 non-test `GitContext(` sites found that
`toplevel` and `branch` are `@cached_property` — which **takes no
arguments**. There is therefore no parameter through which any caller
could pass a timeout even if they wanted to, and all fifteen of their
call sites are unbounded by construction:

| Location | Reached from |
|---|---|
| `mcp/gate_tools.py:138,184`, `mcp/gate_query.py:168` | MCP handlers directly |
| `session/service.py:70,128,151,175,209,323` | `mcp/misc_tools.py:35` imports `SessionService` |
| `domain/documents/plan.py:53,89` | `mcp/plan_tools.py` |
| `github/__init__.py:1317` | `create_pr` |
| `skills/permission/update_paths.py:1437,1484` | permission MCP path |
| `hooks/skill.py:57`, `hooks/session_dispatch.py:47` | hook processes |

Conversely, the three sites that DO pass a timeout —
`session/preset_pin.py:84,109` and `session/repo_address.py:58` — reach
git through `.run(..., timeout=_GIT_TIMEOUT_SECONDS)`. They are the
correct examples, not further instances of the defect.

**Fix:** repair the class, not the callers. Convert `toplevel`/`branch`
from `cached_property` to methods accepting a bounded default timeout
(or apply a class-level default inside them), widen the `except` to
include `subprocess.TimeoutExpired`, and every one of the fifteen
callers is fixed at once. Then wrap the MCP-handler calls in
`asyncio.to_thread(...)` so a bounded-but-slow git still does not stall
the loop.
**Impact: HIGH · Effort: M**

### E3. Six standalone uv-scripts shell out with no timeout and no local constant

PEP 723 scripts cannot import `dev10x.subprocess_utils`, so
`.claude/rules/mcp-tools.md` requires each to define a local
`_SUBPROCESS_TIMEOUT_SECONDS`. Two do it correctly —
`skills/tts/scripts/synthesize.py:79` and
`skills/yt-upload/scripts/upload-video.py:74`. Six do not:

- `skills/gh-pr-doctor/scripts/gh-audit-check.py:21`
- `skills/gh-pr-doctor/scripts/gh-audit-comment.py:28`
- `skills/gh-pr-doctor/scripts/gh-unresolved-threads.py:61`
- `skills/slack/slack-notify.py:139`
- `skills/qa-self/scripts/upload-screenshots.py:38`
- `skills/git-groom/scripts/mass-rewrite.py:50,187`

A hung `gh` (network stall, interactive auth prompt) or a keyring daemon
waiting on a passphrase with no TTY hangs the script indefinitely. Three
of the six are `gh-pr-doctor`, which runs inside foreman's unattended
night loop where a hang has no escalation path.

**Fix:** add the constant and pass `timeout=` in all six.
`mass-rewrite.py` may need a repo-size-scaled value. The dependency-pin
guard (`bin/check-dependency-pins.py`) is the precedent for making this
a pre-commit check rather than a convention — this class of drift is
exactly what that guard was built for.
**Impact: MEDIUM · Effort: S**

### E4. The sidecar-naming divergence is a latent footgun, not an active defect

`domain/file_locks.py:118` (`file_lock`) and `:220`
(`locked_yaml_update`) both **append** `.lock` to the full target name
via `_lock_path_for`. `locked_json_update` at `:190` instead calls
`path.with_suffix(".lock")`, which **replaces** the suffix — so
`settings.local.json` locks on `settings.local.lock`.

Two writers of one path that reach for different helpers would take
different sidecars and fail to exclude each other, silently. Phase E
swept every locked path and found **no path currently mixes them** — the
settings family uses `locked_json_update` consistently throughout.

So this is a footgun, not a live bug: the divergence is documented in
both docstrings and preserved deliberately for historical call-site
compatibility. It is recorded because the failure mode is silent and the
next writer added to an existing path is the one who pays.

**Fix (optional):** have `locked_json_update` delegate to
`_lock_path_for` behind a one-release compatibility shim that also
locks the legacy sidecar, or add a test asserting each shared-state path
is only ever reached through one helper.
**Impact: LOW · Effort: M**

### E5. `locked_yaml_update` destroys a malformed YAML file

`domain/file_locks.py:224-234` catches `yaml.YAMLError`, sets
`data = {}`, and on context exit atomic-writes that empty dict back over
the file. A `friction.yaml` or task-index store that is corrupt — or
merely half-written by the unlocked writer in E1 — is therefore
**silently replaced with an empty document** rather than surfacing the
parse failure.

The `except` exists so a caller can recover from a garbage file, but
recovery and destruction are being conflated: the caller is handed `{}`
with no signal that anything was lost, and the write-back makes the loss
permanent.

**Fix:** re-raise, or preserve the unparseable content as
`<path>.corrupt-<timestamp>` before proceeding, so the data is
recoverable and the failure is visible.
**Impact: MEDIUM · Effort: S**

## Phase K — Full Archetype Catalog Sweep

**Result: no missing archetype that this domain needs.** Ten of fifteen
catalogued structural archetypes are present and verified in code; two
are correctly N/A (Template View — there is no UI layer; Money — there
is no monetary domain); one is correctly absent (Identity Map); two are
documented variants rather than gaps.

| Archetype | Where | Verdict |
|---|---|---|
| Value Object | `domain/common/repository_ref.py`, `result.py` | textbook |
| Aggregate Root | `domain/documents/plan.py:153-178` | excellent, self-describing |
| Entity | `domain/documents/task.py` | immutable snapshot, deliberate |
| Registry | `platform/registry.py` | correctly disambiguated from `SingletonHolder` |
| Gateway | `subprocess_utils.py`, `github/__init__.py` | named, ADR-0013 cited |
| Result / Either | `domain/common/result.py` | PEP-695 generic, adopted across 15+ modules |
| Service Layer | `plan.service`, `github/` public async API | clean PoEAA shape |
| Front Controller | `mcp/*_tools.py`, `cli.py` LazyGroup | two transports, one contract |
| Specification | `domain/rules/` | present under domain vocabulary |
| Plugin | the repository itself | meta but real |
| Repository | on the aggregate + `*.service` | documented variant |
| Layer Supertype | `ValidatorBase`, `ResultProtocol` | via protocol, not hierarchy |
| Data Mapper | `from_dict`/`to_dict` convention | lightweight, consistent |
| Identity Map | absent | correct — file-backed, short-lived objects |
| Template View / Money | absent | N/A for this domain |

On the business-archetype axis (Arlow & Neustadt), only three map
directly, which is expected for developer tooling rather than a business
application: **Policy/Rule** (`domain/common/policy.py`,
`gate_policy.py`, `domain/rules/`), **Event**
(`domain/events/hook_event.py`), and **Document** — where the codebase's
own subpackage name matches the archetype exactly.

### K1. "Repository" names two unrelated things

The only symbol containing "Repository" is `RepositoryRef`, a GitHub
`owner/name` value object. The actual PoEAA Repository *role* — for
`Plan` and `Task` — has no type named for it; it lives as methods on the
aggregate plus a `plan.service` module. A reader searching for "the
Repository pattern" before adding a new persisted aggregate finds the
value object and reasonably concludes they searched wrong.

No functional defect; `Plan`'s docstring explains the split clearly to
anyone who reaches the file. **Fix:** a one-line pointer in
`domain/documents/__init__.py`.
**Impact: LOW · Effort: S** — converges with A6; do them together.

### K2. Identity Map is correctly absent

Domain documents load fresh from disk per call. The classic Identity Map
problem — several in-memory copies of one row diverging — does not arise
in short-lived, file-backed, single-writer-per-call objects guarded by
`file_locks`. Recorded so a future catalog pass does not file it as a
gap.
**No action.**

## Orchestrator finding — MCP identifier parameters have three spellings

`.claude/rules/mcp-tools.md` records that parameter naming "is not
uniform across tools, which defeats agent first-call inference (GH-462
F4 — 7 first-call validation errors in one session)", lists per-tool
"common wrong guess" values, and defers normalization to follow-up work.

A census of `mcp/github_tools.py` turns that prose into a count, and
shows two distinct defects rather than one.

| Spelling | Tools | Refers to |
|---|---|---|
| `pr_number` | 12 — `pr_comments:179`, `pr_comment_reply:223`, `pr_issue_comment:254`, `pr_labels:322`, `pr_review_edit:402`, `pr_ready:438`, `pr_close:469`, `ci_check_status:555`, `update_pr:740`, `merge_pr:784`, `post_summary_comment:1330`, `pr_notify:1368` | a PR |
| `number` | 1 — `pr_get:85` | a PR |
| `number` | 7 — `issue_get:114`, `issue_comments:130`, `issue_labels:364`, `issue_edit:859`, `issue_close:898`, `issue_reopen:930`, `issue_comment:951` | an issue |
| `number` | 3 — `milestone_close:1215`, `milestone_reopen:1241`, `milestone_edit:1267` | a milestone |
| `issue_id` | 2 — `create_pr:635`, `generate_commit_list:1349` | a **string** ticket ID |

**Defect 1 — `pr_get` is a lone outlier.** Twelve PR tools take
`pr_number`; the single most-called read on the surface takes `number`.
An agent that has just called `pr_labels(pr_number=…)` and reaches for
`pr_get` guesses wrong, which is exactly the failure GH-462 counted.

**Defect 2 — `number` is overloaded across three entity types** while
`issue_id` *looks* like a sibling of `issue_get(number=…)` but holds a
string ticket ID, not an issue number. The two names are closest
together precisely where they mean the most different things.

**Fix:** have `pr_get` accept `pr_number` as an alias — one edit that
removes the largest single source of first-call error. Longer term,
accept both spellings surface-wide rather than renaming, so existing
callers keep working; `pr_comments` already demonstrates the
action-selector shape that keeps one tool coherent across variants.
**Impact: MEDIUM · Effort: S (alias) / M (surface-wide)**

## Phase C — Value Objects (conducted by the orchestrator)

The dispatched Phase C agent did not report. The findings below were
derived directly, so the baseline matters: `domain/common/` **already
holds sixteen value objects** — `allow_rule`, `branch_name`,
`commit_subject`, `mcp_tool_name`, `mktmp_path`, `repository_ref`,
`rule_id`, `skill_name`, `ticket_id`, `tool_signature`,
`tracker_choice`, `ide_choice`, `plugin_version`, `workspace`,
`command_spellings`, `bash_tokens`. This codebase is not short of value
objects. The defect worth reporting is therefore not "primitives that
should be VOs" but **a VO that exists and is bypassed**.

### C1. `McpToolName` is bypassed at the three sites it was built to retire

`domain/common/mcp_tool_name.py:1-23` states its own purpose: MCP tool
identifiers "were understood only implicitly: detection via
`startswith("mcp__")` at five call sites, two incompatible compiled
regexes… and ad-hoc structural splits to recover the `(server, tool)`
parts (audit finding GH-508 — 2026-06-10). This object is the single
authoritative parse."

It supplies `is_mcp`, `is_command_token`, `is_wildcard`, `prefix` and a
parse. Three sites still hand-roll what it owns:

| Site | Bypass | Should be |
|---|---|---|
| `skills/permission/generalize.py:106` | `rule.startswith("mcp__")` | `is_mcp` |
| `hooks/permission_diagnostics.py:256` | `sig.tool.startswith("mcp__")` | `is_mcp` |
| `skills/permission/enumerate_mcp.py:332` | `full_name.split("__")` | the parse |

The third is the sharpest: an ad-hoc structural split to recover
`(server, tool)` is verbatim the defect GH-508 created the object to
eliminate, still present in the module the docstring names.

**Not violations:** `enumerate_mcp.py:206,373,376` build
`f"mcp__plugin_Dev10x_{server_key}__"` strings, which the same docstring
explicitly carves out — "the narrower `mcp__plugin_<x>_*` … is a
different, plugin-specific concern and is left where it lives." A grep
alone would misreport these three; they are correct as written.

**Fix:** route the three genuine sites through `McpToolName`.
**Impact: MEDIUM · Effort: S** — the risk is not the `startswith`
checks, which are harmless in isolation, but `enumerate_mcp.py:332`'s
split silently disagreeing with the canonical parse on an unusual name,
in the module that decides which tools get permission entries.

### C2. Verified negative — `repo_stem` has a single owner

`repo_stem` is defined once (`domain/documents/session_yaml.py:382`) and
imported by `session/preset_pin.py:31` and
`domain/config_migration.py:54`. This fact keys the global
`friction.yaml` `projects[]` entries and the task-index store path, so a
second implementation would be a silent cross-repo mismatch. There is
none. Recorded because it was a specific suspicion worth closing.

## Phase G — Coverage (partial, conducted by the orchestrator)

The dispatched Phase G agent did not report. Two of its checks were
completed directly; the full JTBD coverage matrix was not, and is
recorded as outstanding work below.

### G0. Method note — filename matching does not measure coverage here

A module-name-to-test-filename diff was run first and produced almost
entirely false positives. This repository names tests by **behaviour**,
not by module, so the heuristic flags covered code as uncovered:

| Flagged "untested" | Actually covered by |
|---|---|
| `github_tools` | `tests/github/test_wrapper_contracts.py`, `tests/mcp/test_github_tool_decorator.py` |
| `sampling_manager` | `tests/mcp/test_sampling.py` |
| `roots_manager` | `tests/mcp/test_roots.py`, `test_roots_tools.py` |
| `gchat_notify` | `tests/skills/gchat/test_gchat_notify_module.py` |
| `server_cli` | `tests/mcp/test_cli_server.py` |

The list was discarded rather than published. Any future coverage audit
must grep for the module name and its public symbols across `tests/`
before asserting a gap — a false coverage gap is worse than none,
because it sends someone to write tests that already exist.

### G1. Thirteen skills with decision gates ship no evals file

`.claude/rules/skill-gates.md` states the contract for a skill with a
decision gate as three items, all required: the `REQUIRED: Call
AskUserQuestion` marker, the `allowed-tools:` entry, and
`evals.json` assertions for gate enforcement. It adds: "Missing any step
causes per-invocation approval prompts on every skill run."

63 skills contain `AskUserQuestion`; 54 `evals.json` files exist. These
thirteen gated skills have **no `evals/` directory at all**:

`afk`, `git-commit-split`, `git-fixup`, `ide-normalize`, `investigate`,
`park-discover`, `playwright`, `py-test-flaky`, `py-uv`, `qa-scope`,
`slack`, `slack-review-request`, `ticket-scope`

Spot-verified: `skills/git-fixup/` contains only `SKILL.md` and
`scripts/`; `skills/qa-scope/` only `SKILL.md` and `references/`;
`skills/afk/` only `SKILL.md`. Each has a live gate — `git-fixup`
SKILL.md:97, `qa-scope` SKILL.md:244 and :325.

**Fix:** add gate-enforcement assertions per `references/eval-schema.md`.
`skill-eval-gaps.yml` already exists as a workflow — worth checking
whether it covers this case and, if so, why these thirteen pass.
**Impact: MEDIUM · Effort: M**

### G2. Gate markers use the soft phrasing the rule was written to replace

`.claude/rules/skill-gates.md` is explicit that
`**REQUIRED: Call AskUserQuestion**` "replaces soft guidance ('Use
AskUserQuestion') which allows agents to substitute plain text instead."

Two confirmed sites still use exactly that soft form:
`skills/qa-scope/SKILL.md:244` ("Use `AskUserQuestion` to get approval")
and `skills/git-fixup/SKILL.md:97` ("Otherwise, use `AskUserQuestion` to
ask"). Both are genuine execution-path gates, so both are cases the rule
names.

**Scope is not yet measured.** 119 markdown files under `skills/`
mention `AskUserQuestion`; 58 carry the hard marker. That gap is an
indicator, not a count — a file may hold one marked gate and one
unmarked, and some are `references/` docs describing gates rather than
defining them. A per-gate pass is needed before the number means
anything.

**Fix:** sweep gate sites for the soft form and convert to the mandated
marker. The check is mechanical enough to belong in
`skill-eval-gaps.yml` alongside G1.
**Impact: MEDIUM · Effort: M**

### G3. Outstanding — the JTBD coverage matrix was not produced

Still unmeasured: clustering the ~200 merged PRs into feature areas and
scoring each for unit / integration / behavioural coverage, and the
LOC-ratio check for large modules with disproportionately small test
files (`github/__init__.py` at 2,918, `update_paths.py` at 2,308,
`commands/permission.py` at 1,419, `hooks/stop_verdict.py` at 986).

Also unresolved: `pyproject.toml` sets `fail_under = 75` while CLAUDE.md
and the global standard require 100% for new code. Which modules drag
the number is not known, and the gate cannot enforce the stated
standard.

This is the one gap in the audit's own coverage. It is carried into the
backlog as a scoped ticket rather than left implicit.







