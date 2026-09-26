# ADR-0028: Deprecations carry a removal version

- **Status:** Proposed. This needs a supervisor decision, see
  § Decision Needed
- **Date:** 2026-09-26
- **Supersedes:** none
- **Amends:** none (would bind every "for one release" promise made
  under ADR-0018, ADR-0022 and ADR-0026)
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

## Decision Needed

The evidence settles the facts above. It does **not** settle the
policy. Whether this project accepts a build that fails on a schedule
is a question about how the supervisor wants to spend release-day
attention, and no measurement answers it. The options below are laid
out for that call. This ADR stays **Proposed** until it is made.

### Option A: Enforced register

- A `Deprecation` dataclass registry, for example
  `src/dev10x/domain/deprecations.py`, with one entry per shim:
  `name`, `audience` (`python` | `mcp` | `config`), `since`,
  `removed_in`, `replacement`, `issue`.
- A pytest test that fails once `pyproject.toml`'s version reaches an
  entry's `removed_in`. A second test would fail when a
  `deprecated`/`one release` comment in `src/` has no registry entry,
  so new shims cannot bypass the register.
- Removal windows stated in versions, not "releases". The windows
  differ by audience: `python` gets 0 (remove in the same PR as the
  rename; there is no external caller), while `mcp` and `config` get
  N minor versions, with N for the supervisor to set.

**Pros:** A stale shim becomes a failing test instead of a forever
shim. It also closes Problem 2, because an ADR's "for one release"
now needs a registry row. **Cons:** develop goes red on a `.dev0` bump
until someone removes the shim or pushes `removed_in` out. That
extension is always one line, so a determined maintainer can defer
forever. The value is that each deferral becomes visible.

### Option B: Documented register, reported not enforced

The same registry, surfaced by `dev10x config doctor` or a release
checklist item. Nothing fails.

**Pros:** It never blocks a release. The register still answers
"what is deprecated and since when" in one place. **Cons:** It depends
on someone reading the report. The evidence above shows nobody greps
for GH numbers now, and a report is one more thing to not read.

### Option C: Status quo, plus retire the prose

Accept ad-hoc handling as adequate for a single-maintainer plugin.
Stop writing "for one release", and write "until removed" or nothing.

**Pros:** Zero machinery. It stops the docs making a promise they do
not keep. **Cons:** Shims accumulate for good. The on-disk config
aliases never lose their read paths.

### Recommendation (for the supervisor to accept or reject)

**Option A, with the `python` audience at a zero window.** Two facts
drive this. The `python` rows have no caller outside the repo, so
their windows protect nobody and cost reviewers a second name. And
the `.dev0` bump puts the red build at the least disruptive point in
the cycle. Whether that red build is acceptable at all is exactly the
call this ADR defers.

## Alternatives Considered

The three options above are the alternatives. One more was rejected
outright:

- **Python `warnings.warn(DeprecationWarning)` at each shim.** None of
  the audiences would see it. MCP responses do not carry warnings to
  the calling agent, config aliases are read inside hooks whose
  stderr is not shown, and the in-process callers are our own tests.
  Rejected because it adds noise without adding a signal.

## Consequences

Consequences depend on the option chosen. Under any option, the
evidence supports two points:

1. New prose should stop saying "for one release". The phrase
   measures nothing at this release cadence (Problem 1).
2. The `python`-audience shims (`Rule`,
   `seed_strict_baseline_if_absent`, `read_human_review`) can be
   removed now, with callers updated in the same change. That cleanup
   does not wait for the policy decision, but it is left for the
   follow-up so that this PR stays decision-only.

## Implementation Plan

None until the decision is made. Once it is:

1. File the implementation through `Dev10x:ticket-create`, linking
   this ADR.
2. Update this ADR's status to `Accepted` and record the chosen
   option and window N.

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
