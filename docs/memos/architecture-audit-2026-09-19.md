# Architecture Audit — 2026-09-19

Full-project audit of the Dev10x plugin: design patterns, software
archetypes, domain-model health, concurrency safety, test coverage,
cross-cutting consistency, and industry best practices.

Run via `Dev10x:project-audit` with all phases selected, twelve
read-only agents dispatched in parallel.

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

<!-- Phases B, C, E, G, H, I, K, L pending — appended as agents report. -->
