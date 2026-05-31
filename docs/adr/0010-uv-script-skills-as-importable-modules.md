# 10. uv-script skills delegate to importable `dev10x` modules

Date: 2026-05-31

## Status

Accepted

This ADR ratifies a pattern that is already partially adopted in the
codebase and sets the conventions that the remaining migration work
(GH-246 / audit milestone M7) completes.

## Context

### Current State

Several skills ship executable logic as standalone uv-scripts with a
PEP 723 inline-metadata header declaring `dependencies = ["pyyaml"]`
(or `[]`). Historically these scripts could not `import` from the
`dev10x` package, because the uv-script runs in an isolated
environment that only sees its declared dependencies — not the
editable `src/` tree.

That constraint has since been worked around with a **thin-shim**
entry point. The script inserts `src/` onto `sys.path` and delegates
to an importable module:

```python
#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["pyyaml"]
# ///
"""Thin shim — delegates to dev10x.skills.monitor.ci_check_status."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from dev10x.skills.monitor.ci_check_status import *  # noqa: F401, F403
from dev10x.skills.monitor.ci_check_status import main

if __name__ == "__main__":
    main()
```

The business logic now lives in importable modules:

| Skill script (entry point) | Importable module |
|----------------------------|-------------------|
| `skills/release-notes/scripts/collect-prs.py` | `src/dev10x/skills/release/collect_prs.py` |
| `skills/gh-pr-monitor/scripts/pr-notify.py` | `src/dev10x/skills/monitor/pr_notify.py` |
| `skills/gh-pr-monitor/scripts/ci-check-status.py` | `src/dev10x/skills/monitor/ci_check_status.py` |

This is the same structural seam the MCP server already relies on:
`mcp/server_cli.py` imports `dev10x.skills.*` functions directly. The
shim and the MCP boundary are now two front-ends over one module.

### Problems

The shim made code-sharing *possible* but the migration is
incomplete, so the duplication the original audit flagged persists:

1. `extract_jtbd` is defined three times with divergent behaviour
   (regex search vs. line-scan) across `collect_prs.py`,
   `pr_notify.py`, and `slack_review_request.py`.
2. `md_to_slack_bold` is copy-pasted in `pr_notify.py` and
   `slack_review_request.py`.
3. `find_config` / `load_config` are copy-pasted across three
   permission skills (`update_paths.py`, `clean_project_files.py`,
   `merge_worktree_permissions.py`).
4. `github/queries.py::batch_find_prs` (a batched GraphQL query that
   would kill the per-ticket N+1 in `collect_prs`) shipped with tests
   but **zero production callers** — it is dead because the consumers
   were never wired to it.
5. There is no documented convention for *where* logic belongs
   (shim vs. module) or *how* each layer reports errors and emits
   output. New skills have no rule to follow, so duplication recurs.

### Prerequisites

- [ADR-0009 — Result[T] contract at MCP boundary](0009-result-contract-at-mcp-boundary.md)
  defines the in-process error contract this ADR's domain layer adopts.
- `references/code-sharing-patterns.md` documents the shim mechanics
  at the implementation level.

## Decision

We will treat **importable `dev10x.skills.*` modules as the single
home for skill business logic**, with uv-script entry points reduced
to thin shims. Concretely:

1. **Logic lives in `src/dev10x/skills/<area>/<name>.py`** as
   importable functions. Anything reused by more than one script —
   or by the MCP boundary — MUST live in such a module, never be
   copy-pasted into a script.
2. **uv-script entry points are thin shims** (the pattern above):
   PEP 723 header → `sys.path.insert` → import module → call
   `main()`. A shim contains no business logic of its own.
3. **Shared cross-skill helpers** live in a common module
   (`src/dev10x/skills/common/`) and are imported by every consumer.
   A helper duplicated across ≥ 2 skills is a defect.
4. **Output/logging convention (resolves H3):** entry-point scripts
   write user-facing output to stdout and diagnostics to stderr via
   `print()`; in-process `dev10x.*` domain functions use structured
   `logging` and never `print()`. The script's `main()` is the only
   place that translates a domain result into printed output.
5. **Error convention (resolves H7):** in-process domain functions
   return `Result[T]` (per ADR-0009) — they do not call `sys.exit`.
   Entry-point scripts own process exit: they map a domain failure to
   `sys.exit(N)` with a stderr message. A script whose stdout is
   parsed by an MCP/JSON consumer emits its error as a JSON object on
   **stdout** (not stderr) so the consumer parses one channel.

### New Components

| Component | Location | Responsibility |
|-----------|----------|----------------|
| `extract_jtbd`, `md_to_slack_bold` | `src/dev10x/skills/common/jtbd.py` | Single source for JTBD extraction + Slack bold formatting |
| `classify_group` + gitmoji/JTBD tables | `src/dev10x/skills/release/classifier.py` | Importable, unit-tested PR classifier extracted from `collect_prs.py` |
| shared `find_config`/`load_config` | `src/dev10x/skills/permission/` (one module) | Single config-resolution helper for permission skills |

### Dependencies (Reused Components)

| Component | Location | How We Use It |
|-----------|----------|---------------|
| `batch_find_prs` | `src/dev10x/github/queries.py` | Wire as the batched PR-status fetch for `pr_notify` (keyed by PR number); retire the per-item fan-out |
| `Result[T]` | `src/dev10x/domain/common/result.py` | Domain-layer return contract per ADR-0009 |

## Alternatives Considered

### Alternative 1: Keep standalone uv-scripts, accept duplication

Leave each script self-contained with `dependencies = []` and copy
shared helpers into each.

**Pros:**
- Scripts are runnable in total isolation; no `src/` path assumption.
- Zero import coupling to the `dev10x` package layout.

**Cons:**
- Guarantees the duplication the audit flagged (5 copy-paste sites).
- `batch_find_prs` and other tested infrastructure stays unreachable
  and rots.
- Divergent copies drift behaviourally (the three `extract_jtbd`
  variants already disagree).

**Verdict:** Rejected — duplication is the root problem we are solving.

### Alternative 2: Share code via PEP 723 inlining / generated headers

Keep scripts isolated but inline shared snippets at build time, or
vendor a shared file into each script's environment.

**Pros:**
- Preserves full script isolation.
- One logical source of truth in the generator.

**Cons:**
- Adds a build/codegen step and a new failure mode.
- The MCP boundary still needs an importable module, so we would
  maintain two sharing mechanisms for the same logic.

**Verdict:** Rejected — more machinery than the shim, and it does not
serve the MCP consumer.

### Alternative 3: Thin shim → importable module (Selected)

Logic in `dev10x.skills.*`; scripts are shims; MCP imports the same
modules.

**Pros:**
- One home for logic, consumed by both the shim and the MCP boundary.
- Shared helpers deduplicate by import, not by copy.
- uv-scripts keep their friction-free invocation shape (no plugin
  install required to run a skill script).

**Cons:**
- Shims assume a fixed relative path to `src/` (`parents[3]`).
- A script is no longer a single self-contained file to read.

**Verdict:** Selected — already de-facto adopted; this ADR ratifies it
and the conventions above complete the migration.

## Consequences

### What Becomes Easier

1. Shared helpers have one source of truth; fixing a JTBD-parsing bug
   fixes every consumer.
2. Tested infrastructure (`batch_find_prs`) becomes reachable,
   removing the per-ticket N+1 in `collect_prs`/`pr_notify`.
3. New skills have an unambiguous rule for where logic goes and how
   each layer handles output and errors.

### What Becomes More Difficult

1. Shims depend on the `parents[3] / "src"` relative path; moving a
   script's directory depth breaks the import and must be kept in sync.
2. Reading a skill now means reading two files (shim + module) instead
   of one.

### Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Shim path (`parents[3]`) drifts when a script moves | Low | Medium | Keep shims at a uniform `skills/<name>/scripts/` depth; a smoke test runs each shim's `--help` |
| `extract_jtbd` reconciliation changes behaviour for one caller | Medium | Medium | Unit-test the reconciled helper against all three prior behaviours before swapping call sites |
| `batch_find_prs` keys on PR number but `collect_prs` searches by ticket | Medium | Low | Wire `batch_find_prs` where the key matches (`pr_notify`); adapt or leave `collect_prs`'s ticket search, documented in the implementing PR |

## Implementation Plan

Tracked by GH-246 (milestone M7). One atomic commit per finding.

### Phase 1: Deduplicate shared helpers

1. Create `src/dev10x/skills/common/jtbd.py` with `md_to_slack_bold`
   and one reconciled `extract_jtbd`; import from `collect_prs.py`,
   `pr_notify.py`, `slack_review_request.py` (F5).
2. Extract the classifier from `collect_prs.py` into
   `src/dev10x/skills/release/classifier.py` with unit tests (G2).
3. Consolidate `find_config`/`load_config` into one shared permission
   module; import from the three permission skills (H12).

### Phase 2: Wire infrastructure and remove dead code

4. Wire `batch_find_prs` into `pr_notify` (and adapt `collect_prs`
   where keys allow); remove the now-dead fan-out / API (G4+I3+I4).

### Phase 3: Document conventions

5. `ci_check_status` emits its error as JSON on stdout; reconcile the
   silent `UNKNOWN` fallback (H7).
6. Document the output/logging and error conventions (§Decision 4–5)
   in `.claude/rules/` and reference them from the rules INDEX
   (H3 + H7 convention text).

## References

### Internal References

- [ADR-0009 — Result[T] contract at MCP boundary](0009-result-contract-at-mcp-boundary.md)
- [ADR-0006 — Keep internal GitHub MCP over official server](0006-keep-internal-github-mcp-over-official-server.md)
- `references/code-sharing-patterns.md` — shim mechanics (PEP 723, `sys.path`)
- `docs/memos/005-2026-05-18-architecture-audit.md` — milestone M7 source
- GH-246 — Wire `batch_find_prs` + promote uv-script skills to importable modules
- GH-146 — `collect_prs` N+1 reduction (closed by Phase 2)
