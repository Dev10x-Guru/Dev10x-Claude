# ADR-0027: The GitHub Gateway splits by capability behind one seam

- **Status:** Accepted
- **Date:** 2026-09-26
- **Supersedes:** none
- **Amends:** none (refines how [ADR-0013](0013-gateway-layer.md)'s
  GitHub Gateway is laid out on disk)
- **Related:** GH-1439, ARCH-M5 (GH-1431, GH-1454), ADR-0006, ADR-0009

## Context

`src/dev10x/github/__init__.py` is **3,077 lines** on
`origin/develop` today. The 2026-09-19 architecture audit
(`docs/memos/architecture-audit-2026-09-19.md` § D1) measured 2,918,
so the file grew by 159 lines in one week. Those lines came from
GH-1424 (`cac896d0`) and GH-1451 (`895bbd5d`), and both commits added
to the file rather than to a sibling.

It holds 73 top-level functions spanning every GitHub capability
the plugin uses. CLAUDE.md § 3 states that "`__init__.py` is for
re-exports only". Nine sibling modules in the same package
(`app_api.py`, `app_auth.py`, `candidate_rules.py`, `learn_loop.py`,
`pattern_validation.py`, `review_patterns.py`, `rule_authoring.py`,
`rule_confidence.py`) already follow that rule. This one does not.

### Current State

The file already has capability-shaped seams. They are contiguous
regions, not interleaved code (line numbers are `def` lines in
`github/__init__.py`):

| Capability | Functions | Lines |
|---|---|---|
| Gateway core | `_detect_repo`, `_gh_api_raw`, `_gh_api`, `_bot_env`, `_resolve_repo`, `_parse_gh_api_result`, `_run_and_parse`, `_GH_RETRY_POLICY` | 52–255 |
| Detection / pre-flight | `detect_tracker`, `pr_detect`, `detect_base_branch`, `verify_pr_state`, `pre_pr_checks` | 256–271, 1203–1258 |
| Review threads & comments | `_pr_comment_*`, `is_bot_login`, `_list_unresolved_threads`, `minimize_comments`, `resolve_review_thread`, `pr_comments`, `pr_comment_reply`, `pr_comment_edit`, `pr_review_edit`, `pr_issue_comment`, `request_review`, `check_top_level_comments`, `unresolved_threads` | 348–850, 1109–1202, 3011–3077 |
| Labels | `pr_labels`, `issue_labels` + helpers | 851–1108 |
| Pull requests | `pr_get`, `_set_pr_milestone`, `create_pr`, `update_pr`, `_normalized_for_comparison`, `_unapplied_pr_fields`, `pr_ready`, `pr_close`, `pr_list` | 272–293, 1290–1574, 1809–1996 |
| Merge | `_resolve_merge_bot`, `_merge_as_bot`, `merge_pr` | 1575–1808 |
| Milestones | `_resolve_milestone_number`, `milestone_close/create/reopen/edit/list` | 1259–1289, 1997–2229 |
| Issues | `issue_get`, `issue_comments`, `issue_create`, `_issue_result`, `issue_edit/close/reopen`, `issue_comment*`, `issue_list`, `triage_roster` | 294–347, 2230–2725 |
| Bulk | `_bulk_execute`, `milestones_bulk_create`, `issues_bulk_create`, `issues_bulk_edit` | 2726–2893 |
| Summary & notify | `generate_commit_list`, `post_summary_comment`, `pr_notify` | 2894–3010 |

Production callers are already insulated from the layout.
`mcp/github_tools.py:11` imports the package as `gh`, and 46 lines in
that file call `gh.<name>(...)` by attribute at call time. Package
re-exports therefore keep every production call site working
unchanged. The other importers are `mcp/gate_query.py:142` (`pr_detect`,
`pr_labels`) and `skills/notifications/_gh.py:61` (`_gh_api_raw`), and
both resolve through re-exports too.

### Problems

1. **The rule violation is the smallest problem.** Locating
   `pr_ready` takes a grep. Every import of `dev10x.github` loads all
   3,077 lines. Every GitHub change, including a milestone fix, lands
   in the same file.
2. **The tests are the real blast radius, and they fail silently.**
   342 patch sites across 11 test files replace a dependency *that
   the module calls internally*, by name on the package namespace.
   Examples are `patch("dev10x.github._gh_api_raw")`,
   `patch("dev10x.github.async_run")`, `patch("dev10x.github.pr_get")`
   and `patch.object(gh, "_detect_repo")`. `tests/github/test_github.py`
   alone has 200 of them.

   Once `create_pr` lives in `github/pulls.py` and calls `pr_get` or
   `_gh_api_raw` through its *own* module globals, patching the
   package attribute still succeeds. The patch simply stops
   intercepting anything. The test then drives the real `gh` binary,
   or asserts against a mock nobody called. Nothing fails loudly.
3. **ARCH-M5 already hit this, on a split one-fortieth the size.**
   GH-1431's split of `session_yaml.py` (`e83941a0`) had to retarget
   five tests that patched `Dev10xConfigDir` through the facade. It
   also found a sixth, `test_seed_failure_still_nudges`, that
   "patched the deprecated seed alias the service never called, so it
   never exercised the failure path". That test was a false green
   before anyone moved a line. Moving code makes this class of silent
   false green more likely. With 342 sites here, it would be a
   certainty.
4. **Intra-package calls cross the proposed boundaries.** `create_pr`
   (line 1444), `update_pr` (1523), `_merge_as_bot` (1631) and
   `pr_ready` (1862) call `pr_get` for GH-1424 read-back verification.
   `issues_bulk_create` (2844) calls `issue_create`. A split that
   imports those names directly gives each caller a private copy of
   the patch target.

### Prerequisites

ARCH-M5 (PR #1474, #1477) is merged. It split `session_yaml.py` from
1,041 to 390 lines and split `update_paths.py`. It kept the facade
re-exports and pinned them with `test_session_yaml_split.py`, which
gives this split current practice to follow.

## Decision

We will split `github/__init__.py` into capability modules, and every
cross-module call will go through **one module-attribute seam** so each
dependency has exactly one patch target.

### D1: Module map

| Module | Owns |
|---|---|
| `github/_gateway.py` | The Gateway core row above, plus re-imports of `async_run` / `async_run_script` from `subprocess_utils` and `AppConfig` / `get_bot_token` from `app_auth` |
| `github/detection.py` | Detection / pre-flight |
| `github/reviews.py` | Review threads & comments |
| `github/labels.py` | Labels |
| `github/pulls.py` | Pull requests |
| `github/merge.py` | Merge, including `_merge_as_bot` and `_resolve_merge_bot` |
| `github/milestones.py` | Milestones, including `_resolve_milestone_number` |
| `github/issues.py` | Issues, including `triage_roster` |
| `github/bulk.py` | Bulk |
| `github/notify.py` | Summary & notify |

This revises GH-1439's proposal by adding `detection.py` and
`labels.py`. Those two rows had no home in the issue's list. It also
places `triage_roster` explicitly.

### D2: One seam per dependency

A capability module never binds an external dependency or a sibling's
function by name. Instead it imports the module and calls through the
attribute:

```python
# github/pulls.py
from dev10x.github import _gateway

async def pr_close(...):
    return await _gateway.async_run(args=[...])
```

A cross-capability call is written the same way:
`from dev10x.github import pulls` followed by `await pulls.pr_get(...)`.

The test patch target for a dependency is then
`dev10x.github._gateway.<name>` or `dev10x.github.<module>.<name>`.
That target is unique, and it intercepts every caller. This is the
property the single-file layout gave by accident, restated as a rule.

### D3: `__init__.py` holds re-exports only

`__init__.py` holds the module docstring (Gateway pattern, ADR-0006 and
ADR-0013 pointers), `from .<module> import ...` lines, and `__all__`.
There is no line-count target. GH-1439 suggested ≤ 50 lines, but the
facade must re-export 47 public functions plus the constants and
private names existing importers reach for (`_gh_api_raw` via
`skills/notifications/_gh.py:61`). A line cap on that is a formatting
contest rather than a constraint. The rule is **no definitions**.

### D4: Guards land with the first move

Two tests land in Phase 1, before any capability moves:

1. A split-shape test in the style of `test_session_yaml_split.py`. It
   asserts every name in the old `__all__` still resolves on
   `dev10x.github`, that `__init__.py` defines nothing, and that no
   capability module imports the package facade back.
2. A **patch-target guard.** It scans `tests/**` for
   `patch("dev10x.github.<name>")` / `patch.object(gh, "<name>")` /
   `monkeypatch.setattr(gh, "<name>")` and fails when `<name>` is a
   re-export instead of a definition. That turns problem 2 from silent
   into loud. It is also why the guard must land before the moves and
   not after them.

### D5: Phased, smallest capability first

Each phase moves one capability, retargets its tests and passes the
guard. One commit per phase keeps review tractable and bisect useful.
Order:

1. `_gateway.py` + the D4 guards. Everything depends on this module,
   and the guard then enumerates every patch site the later phases
   must retarget.
2. `notify.py`, `bulk.py`, `milestones.py`, `detection.py`: small, with
   few intra-package callers.
3. `labels.py`, `issues.py`.
4. `reviews.py`.
5. `pulls.py` then `merge.py` last. They are the largest pair, and they
   carry the GH-1424 read-back cross-calls.

The work is tracked as follow-up GH-1478. This ADR does not perform the
split.

## Alternatives Considered

### Alternative 1: Leave the file whole

**Pros:**
- Zero churn. `@github_tool` already hides the layout from callers.

**Cons:**
- The file grows every week. It gained 159 lines since the audit.
- It is the largest violation of CLAUDE.md § 3 in the repository.

**Verdict:** Rejected. The cost rises with every GitHub change.

### Alternative 2: Split with direct name imports, and retarget tests as they break

The mechanical reading of GH-1439's proposal: move code, then
`from dev10x.github._gateway import _gh_api_raw` in each module.

**Pros:**
- Idiomatic Python, and the smallest diff per phase.

**Cons:**
- Tests do not break. They go quiet (problem 2). "Retarget as they
  break" never finds the sites that matter.
- Each dependency gains one patch target per importing module, so a
  test for `create_pr` must know which module's copy of `pr_get` to
  replace.

**Verdict:** Rejected. It trades a visible structural problem for an
invisible testing one.

### Alternative 3: Inject the Gateway as an object

Pass a `GitHubGateway` instance into each capability function and fake
it in tests.

**Pros:**
- The cleanest seam, with no patching at all.

**Cons:**
- It changes the signature of all 73 functions and every
  `@github_tool` wrapper.
- It rewrites all 342 patch sites at once rather than one phase at a
  time.
- It is a redesign, not a split, so it deserves its own decision.

**Verdict:** Rejected for this work. D2's seam keeps the option open,
because a later ADR can swap `_gateway` for an injected object without
touching the module map.

### Alternative 4 (Selected): Capability modules + attribute seam + guard first

**Pros:**
- One patch target per dependency, enforced by a test.
- The public import surface is unchanged, so production callers need
  no edits.
- It follows ARCH-M5's facade-plus-split-test practice.

**Cons:**
- `_gateway.async_run(...)` is slightly noisier than a bare
  `async_run(...)`.
- The phases still touch hundreds of test lines in total.

**Verdict:** Selected.

## Consequences

### What Becomes Easier

1. A capability change touches one module of 100–650 lines, not a
   3,077-line file.
2. A test's patch target names the module that owns the dependency,
   and the guard rejects a target that intercepts nothing.
3. The next GitHub capability gets a file of its own by default.

### What Becomes More Difficult

1. Contributors must write `_gateway.<dep>(...)` and `<module>.<fn>(...)`
   rather than bare names. A reviewer who does not know D2 will "tidy"
   it back into a direct import. The guard catches that tidy-up only
   indirectly, through the tests it disarms, so the module docstrings
   must state the rule.
2. `reviews.py` starts at about 660 lines, the largest module. If it
   grows, split it next into `threads.py` and `comments.py`.

### Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| A patch silently stops intercepting after a move | High without D4 | High (false-green tests) | The D4 patch-target guard lands in Phase 1, before any move |
| A circular import between capability modules | Medium | Low | Modules import each other as modules, not names; `__init__` imports `_gateway` first |
| A sibling session edits `github/__init__.py` mid-split | Medium | Medium | One capability per PR; rebase before each phase |
| The re-export list drifts from `__all__` | Low | Low | The split-shape test compares the two |

## Implementation Plan

### Phase 0: This ADR

1. `docs/adr/0027-github-gateway-splits-by-capability-behind-one-seam.md`.

### Phases 1–5: Deferred to GH-1478

These run as D5 orders them, one capability per commit. Each phase
passes the full suite and the D4 guards.

## References

### Internal References

- [ADR-0013](0013-gateway-layer.md): names this module a Gateway
- [ADR-0006](0006-keep-internal-github-mcp-over-official-server.md):
  why the Gateway is internal
- [ADR-0009](0009-result-contract-at-mcp-boundary.md): the `Result`
  contract every capability module keeps
- `src/dev10x/github/__init__.py`: every line range in § Current State
- `src/dev10x/mcp/github_tools.py:11`: attribute-access import
- `tests/domain/documents/test_session_yaml_split.py`: the ARCH-M5
  split-shape test this ADR mirrors
- `e83941a0` (GH-1431): the retargeted and previously inert patches
- [GH-1439](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1439):
  the issue this decides
- [GH-1478](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1478):
  implementation follow-up
