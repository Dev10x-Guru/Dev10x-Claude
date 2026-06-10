# Architecture & Per-Package Audit — 2026-06-10

Full-project audit via `Dev10x:project-audit` (all phases A–I) extended
with per-package specialized review agents: dead-code detection (vulture
+ manual verification), code-review rule violations, and direct issue
filing by the agents themselves.

**Initiative prefix:** `PKG` (registered in `references/milestone-naming.md`)
**Label:** `audit-2026-06-10`
**Issues filed:** 77 (#494–#570) across 11 milestones
**Agents:** 10 package reviewers (opus) + 9 audit-phase agents A–I (sonnet)

## Backlog by milestone

| Milestone | Issues | HIGH |
|-----------|-------:|-----:|
| PKG-M1: skills package | #532 #537 #540 #546 | 1 |
| PKG-M2: mcp package | #498 #501 #502 | 0 |
| PKG-M3: validators package | #494 #495 #497 | 1 |
| PKG-M4: domain package | #504 #505 #509 #511 #520 | 0 |
| PKG-M5: commands & CLI | #519 #525 #528 | 0 |
| PKG-M6: github package | #496 #499 #500 #503 | 1 |
| PKG-M7: runtime & infra | #512 #517 | 0 |
| PKG-M8: workflow packages | #507 | 0 |
| PKG-M9: plugin assets | #545 #554 | 0 |
| PKG-M10: test suite | #564 #565 #567 #568 #569 #570 | 1 |
| PKG-M11: cross-cutting (A–I) | 44 issues #506–#566 | 18 |
| **Total** | **77** | **22** |

## HIGH-impact findings (start here)

**Safety / correctness:**
- #494 ValidatorChain fails open silently when a safety validator raises
- #496 Six unguarded `json.loads` on `gh` stdout (github package)
- #532 `resolve_config` can `sys.exit` the long-lived MCP server in-process
- #544 Non-atomic version-stamp write; #548 broken atomic-append on
  metrics JSONL; #555 `file_lock` has no timeout — crashed holder hangs
  the daemon (Phase E)
- #564 `except Exception: pass` in CWD-handler test is the root cause of
  the historical repo-root MagicMock junk

**Performance (hook hot paths & N+1):**
- #559 SpecDriftValidator runs 3 git subprocesses on EVERY Edit/Write
- #550 N+1 `gh pr list` per ticket in release collect_prs
- #561 sequential awaits in review-comment multi-fetch

**Architecture / consistency:**
- #529 Extract SessionService (Service Layer for session hooks)
- #533 Result[T] adoption stops at the most-called domain helpers
- #536 19 ad-hoc config-load sites bypass the canonical cached loader
- #541 permission.py repeats 8× command boilerplate; #543 tool-name
  dispatch duplicated across 4 modules
- #508 `mcp__` tool-name identity parsed by 3 incompatible regexes + 5
  ad-hoc checks (Value Object candidate)
- #513 #515 ADR-0007 D3 violations — `PolicyRule.apply()` doing file I/O

**Test coverage (Phase G — all HIGH):**
- #547 PR-lifecycle skills, #553 fanout/worktree, #556 MCP
  audit/plan tools, #560 work-on pipeline, #563 daemon lifecycle.
  Together ≈46% of the last 200 merged PRs ship into these areas
  with thin-or-no coverage.

## Dead code: verified results

Vulture reported 186 candidates at ≥60% confidence; after repo-wide
verification agents confirmed the overwhelming majority are FALSE
POSITIVES (click decorators, FastMCP `@server.tool` surface, validator
string-registry, hook orchestrator imports). Genuinely dead and filed:

- #500 github `_clear_cache` (test-only)
- #504 domain: 11 dead members + borderline field
- #512 runtime: 2 items incl. dual-impl drift `task_plan_sync.read_plan`
- #519 commands: `STARTER_GITMOJI_YAML`, `parse_json_output`
- #540 skills: ~9 fully-tested modules with ZERO production callers
  ("wire or remove" — same class as ADR-0010's `batch_find_prs`)
- #545 assets: `bin/skill-audit-counts.py`, unwired
  `session-start-reload.py` shim
- #569 tests: dead faker fixtures
- #501 mcp: daemon/session_store stack is unwired forward-compat infra
  (roadmap #338 never landed)

## Clean bills of health

- MCP boundary: every `@server.tool` unwraps `Result[T]` via
  `.to_dict()` (ADR-0009) — zero violations found
- CWD discipline (GH-979): no bare `subprocess.run`/`os.getcwd`/
  module-scope `GitContext()` in long-lived paths
- hooks.json wiring: all 8 entries audit-wrapped, direct-shebang,
  no `uv run --project` anti-pattern
- LazyGroup CLI startup discipline intact; validator registry
  DX001–DX015 consistent with docs; ADR-0011 GH-240 fixes all present
- Test suite collects cleanly: 3896 tests, no orphaned files
- Dependency directions clean: no domain→commands, no FastMCP wire
  types outside mcp/

## Suggested execution order

1. **Safety first:** #494, #532, #555, #548, #544, #496 (fail-open,
   crash, and data-loss classes)
2. **Hot-path performance:** #559 (every Edit/Write pays it), #550, #561
3. **Dead-code removals:** low-risk, shrink the surface before refactors
   (#500 #504 #512 #519 #540 #545)
4. **Consistency refactors:** #536, #533, #543, #541, #508 (each reduces
   the cost of everything after it)
5. **Coverage debt:** #556 (S effort, highest ROI per Phase G), then
   #547, #553, #560, #563
6. **Naming/vocabulary:** pattern-naming issues (#516 #522 #526) and
   remaining MEDIUM/LOW bundles

## Process notes

- The Phase 2 selection gate and Phase 4 synthesis gate were skipped:
  the user explicitly pre-selected the full scope (all phases +
  dead code + per-package milestones + agent-filed issues) in the
  invocation, and agents filed issues directly per that instruction.
- Each agent capped issue count (5–10) and bundled LOW findings to
  keep the backlog actionable; per-finding evidence lives in the
  issue bodies under a Verification section.
- Findings are static-analysis based; agents flagged their own
  uncertainty in issue bodies — confirm "no production caller" claims
  before deleting (especially #540, #505, #528).
