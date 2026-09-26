# ADR-0028: Deprecations carry a removal version

- **Status:** Accepted (supervisor decision, 2026-09-26: Option A,
  the enforced register)
- **Date:** 2026-09-26
- **Supersedes:** none
- **Amends:** ADR-0018, ADR-0022 and ADR-0026: every "for one
  release" promise they made is now a register row with a removal
  version
- **Related:** GH-1440, GH-1161, GH-1164, GH-1009, ADR-0026

## Context

The codebase makes the same promise in about twenty places: a
deprecated name or legacy read path is "retained for one release".
Nothing checks it. `rg` finds no `DeprecationWarning`, no
`warnings.deprecated`, no `removed_in` and no shared marker anywhere
in `src/`, `tests/` or `bin/`. Each deprecation is hand-coded at its
call site with a GH reference and prose. Removal depends on someone
remembering to grep for that GH number later.

### Current State

The live deprecations fall into three audiences, and each audience
has a different cost of removal:

| Audience | Example | Where | Deprecated | Callers today |
|---|---|---|---|---|
| **In-process Python name** | `Rule = MatchingRule` | `domain/rules/validation_rule.py:401-405` | GH-846, 2026-07-11 | `domain/__init__.py:16` and 3 test modules |
| | `seed_strict_baseline_if_absent` | `domain/documents/friction_yaml.py:458-460` | GH-1164, 2026-09-03 | none outside two `__all__` lists (`friction_yaml.py:624`, `session_yaml.py:387`). GH-1431 found the one test that patched it never exercised the path |
| | `read_human_review` | `domain/documents/session_yaml.py:239-250` | GH-1161 | its own tests only (`tests/domain/documents/test_session_yaml.py:378-443`) |
| **MCP tool name** | `human_review_status` | `mcp/gate_tools.py:245-250` | GH-1161, v0.97.0 | agents, skill docs, user memory, all outside the repo |
| **On-disk user config** | `human_review:` boolean in `friction.yaml` | `session_yaml.py:270-271` | GH-1161 | every user file written before v0.97.0 |
| | `match:` alias on repo-addressed files | `domain/project_match.py:7`, ADR-0026:150-151 | GH-1375 | user playbooks, `gitmoji.yaml` |
| | retired `.claude/Dev10x/session.yaml` read | `session/task_index.py:43`, `mcp/task_index_tools.py:23`, `domain/dev10x_paths.py:170` | GH-1009, v0.94.0 | checkouts that parked before v0.94.0 |

### Problems

1. **"One release" is not a unit of time here.** The tags show seven
   releases in three days: `v0.99.0` on 2026-09-15 through `v0.105.0`
   on 2026-09-17. Taken literally, the promise would expire in hours.
   Nobody removes on that schedule, so in practice it never expires.
   `human_review_status` has been deprecated since v0.97.0, and
   `pyproject.toml` now reads `0.106.0.dev0`, nine minor versions
   later.
2. **ADRs keep adding to the pile and say so.** ADR-0026 introduced a
   "one release" alias. Its own consequences list states that
   "nothing enforces its removal but a note" (ADR-0026:262-265).
3. **The three audiences are treated alike, but they are not alike.**
   `seed_strict_baseline_if_absent` has no caller, so its window
   protects nobody. A user's `friction.yaml` `human_review:` key is
   read on every session start on machines this repo cannot see.
   Removing that alias silently flips a review posture. One rule for
   both is wrong for at least one of them.
4. **Release timing is where any enforcement would bite.** Releases
   bump `X.Y.0.dev0 → X.Y.0` and then immediately
   `X.Y.0 → X.(Y+1).0.dev0` (for example `25baf1ef` and `0a8e9348` on
   2026-09-17). A version-gated test therefore turns red at the
   **start** of a development cycle, on the `.dev0` bump. That is the
   friendly place for it: it gives the whole cycle to remove the
   shim. But it does make develop red on a schedule. GH-1440 names
   this trade-off explicitly as one to agree rather than assume.

## Decision

On 2026-09-26 the supervisor chose **Option A, the enforced
register**, and accepted explicitly that develop goes red on a
`.dev0` bump when a shim reaches its removal version.

- `src/dev10x/domain/deprecations.py` holds `REGISTER`, one
  `Deprecation` per shim: `name`, `audience` (`python` | `mcp` |
  `config`), `since`, `removed_in`, `replacement`, `issue`, and the
  `locations` that carry the shim.
- `tests/domain/test_deprecations.py` fails once `pyproject.toml`'s
  release (the `.devN` suffix is ignored) reaches an entry's
  `removed_in`. The red build lands on the `.dev0` bump that opens a
  cycle, which leaves that whole cycle for the removal.
- The same suite fails when a file under `src/` carries a shim marker
  (`deprecated alias`, `deprecated legacy`, `.. deprecated::`) but no
  entry lists it, and when a listed location no longer names its
  shim. A new shim cannot ship unregistered, and a removed one cannot
  leave a stale row. The phrase "for one release" is banned from
  `src/` outright.
- Windows are stated in minor versions, per audience:

  | Audience | Window | Why |
  |---|---|---|
  | `python` | 0 | nothing outside the repo imports it; remove in the rename's own change |
  | `mcp` | 3 | agents, skill docs and user memory call tools by name from outside the repo |
  | `config` | 6 | a user's hand-edited key is read on machines this repo cannot see |

  A new shim counts its window from `since`. The shims that predate
  the register count from `0.106.0`, the version it landed in, because
  their earlier "one release" promises were never stated in versions.
  A `python` shim with a zero window gets `removed_in` one minor
  version out, so develop is green when the register merges and turns
  red on the next `.dev0` bump.
- Extending `removed_in` stays a one-line change. The test does not
  forbid a deferral; it makes each one visible in a diff.

### Rejected alternatives

- **Option B: a register that is reported, not enforced**, surfaced by
  `dev10x config doctor` or a release checklist. Rejected because it
  depends on someone reading the report, and the evidence above shows
  nobody greps for GH numbers now.
- **Option C: status quo, with the prose retired**. Rejected because
  shims would accumulate for good, and the on-disk config aliases
  would never lose their read paths.
- **Python `warnings.warn(DeprecationWarning)` at each shim.** None of
  the audiences would see it. MCP responses do not carry warnings to
  the calling agent, config aliases are read inside hooks whose
  stderr is not shown, and the in-process callers are our own tests.
  Rejected because it adds noise without adding a signal.

## Consequences

1. New prose stops saying "for one release" and points at the
   register instead. The phrase measures nothing at this release
   cadence (Problem 1).
2. The `python`-audience shims (`Rule`, `match_globs_for`,
   `seed_strict_baseline_if_absent`, `read_human_review`) have
   `removed_in: 0.107.0`. The `0.107.0.dev0` bump turns develop red
   until they are removed with their callers, or deferred in a
   visible diff.
3. The `mcp` rows (`human_review_status`, the `human_review` payload
   key) come due at `0.109.0`. The `config` rows (the `human_review`
   key, the `match:` alias, the `.claude/Dev10x/session.yaml` and
   `memory/Dev10x/dod-acceptance-criteria.yaml` legacy reads) come
   due at `0.112.0`.
4. A red build on a `.dev0` bump is expected behaviour, not a
   regression.

## Implementation Plan

Shipped with GH-1440: the register, its tests, the removal versions
above, and the source and rule docs repointed from "one release" to
the register.

## References

- `src/dev10x/domain/rules/validation_rule.py:401-405`,
  `src/dev10x/domain/documents/friction_yaml.py:458-460`,
  `src/dev10x/domain/documents/session_yaml.py:239-271`,
  `src/dev10x/mcp/gate_tools.py:245-250`,
  `src/dev10x/domain/project_match.py:7`,
  `src/dev10x/session/task_index.py:43`: the live shims
- [ADR-0026](0026-projects-match-names-its-addressing-scheme.md)
  :150-151, :262-265: a "one release" alias and its unenforced
  removal
- `.claude/rules/mcp-tools.md`: documents `human_review_status` as
  "deprecated alias … for one release" since v0.97.0
- [GH-1440](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1440):
  the issue this frames
