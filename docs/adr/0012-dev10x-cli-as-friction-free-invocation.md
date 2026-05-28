# 12. Prefer `dev10x` CLI binary over `uvx dev10x` for plugin maintenance commands

Date: 2026-05-28

## Status

Accepted

## Context

`Dev10x:plugin-maintenance` shipped with two coexisting invocation
styles for its 13 maintenance steps:

| Style | Example | Allow-rule shape |
|---|---|---|
| MCP tool call | `mcp__plugin_Dev10x_cli__update_paths(ensure_base=True, dry_run=True)` | `mcp__plugin_Dev10x_cli__update_paths` |
| Version-pinned cache script | `~/.claude/plugins/cache/Dev10x-Guru/Dev10x/0.74.0/skills/upgrade-cleanup/scripts/update-paths.py --dry-run` | `Bash(~/.claude/plugins/cache/Dev10x-Guru/Dev10x/0.74.0/...)` |

GH-269 retired the version-pinned cache scripts in favour of a
third style: `uvx dev10x permission <subcommand>`. The `uvx` form
is version-stable (a single `Bash(uvx dev10x permission ...:*)`
allow rule survives every `claude plugin update`) and it became
the documented form for Steps 1, 6, 9, 11, 12, and 13.

GH-306 then routed the remaining MCP-using steps (3, 4, 5, 7, 8)
through the same `uvx dev10x permission <subcommand>` form so the
workflow reads consistently end-to-end. The MCP tool entry for
`update_paths` was dropped from `allowed-tools` because no step
called it anymore.

Two questions then arose:

1. Is the `uvx` form fast enough to be the day-to-day default, or
   does it pay a meaningful cold-start tax over the in-process MCP
   call?
2. Is there a third option that avoids both the cold-start tax
   *and* the version-pinned-path rot — for example, installing
   `dev10x` once via `uv tool install` so the binary is on
   `PATH`?

### Benchmark

A controlled run (5 iterations per case, medians; warm system,
identical settings tree) compared three invocation paths:

- `uvx dev10x …` — resolves the cached uvx env each call
- `dev10x …` — installed via `uv tool install --editable .`,
  direct binary exec, no resolver
- `mcp` — in-process call to `dev10x.permission.update_paths()`,
  the same function the warm MCP server dispatches to (stand-in
  for "warm MCP roundtrip")

#### Pure startup (`--version`, no work)

| Path | Median |
|---|---:|
| `uvx dev10x --version` | 51 ms |
| `dev10x --version` | 31 ms |

#### Permission subcommands (`--dry-run --quiet`)

| Subcommand | uvx | dev10x | mcp | uvx Δ vs mcp | dev10x Δ vs mcp |
|---|---:|---:|---:|---:|---:|
| `update-paths` | 1838 ms | 1825 ms | 1834 ms | +4 ms | −9 ms |
| `ensure-base` | 1841 ms | 1821 ms | 1819 ms | +22 ms | +2 ms |
| `ensure-workspace` | 1874 ms | 1832 ms | 1826 ms | +47 ms | +6 ms |
| `ensure-scripts` | 1883 ms | 1868 ms | 1869 ms | +14 ms | −2 ms |
| `ensure-reads` | 1869 ms | 1845 ms | 1853 ms | +16 ms | −8 ms |
| `generalize` | 1911 ms | 1870 ms | 1853 ms | +57 ms | +17 ms |

Negative deltas (`dev10x` faster than `mcp`) sit inside the
±20 ms variance of the workload itself and are noise, not signal.

### Interpretation

1. The bulk of every command (~1.8 s) is the actual permission
   work — scanning settings files across project roots, parsing
   JSON, computing diffs, validating allow rules. Neither
   invocation path can move that floor.
2. `uvx dev10x` adds **4–57 ms per call** vs the in-process MCP
   stand-in. The variance correlates with the subcommand's import
   surface (heavier subcommands like `generalize` pay more).
3. `dev10x` (uv-tool-installed binary) is **effectively
   indistinguishable from the in-process MCP call** — within ±10 ms
   across every case. Once `uv tool install` has been run, the
   binary is on `PATH`, there is no resolver step, and the Python
   interpreter starts directly.
4. Across a full 13-step `plugin-maintenance` run, the cumulative
   delta is roughly **260 ms** in favour of `dev10x` vs `uvx`.

### Friction-friendly properties

Both `uvx dev10x` and `dev10x` produce stable allow-rule shapes
that survive `claude plugin update`:

| Form | Allow rule |
|---|---|
| `uvx dev10x permission update-paths …` | `Bash(uvx dev10x permission update-paths:*)` |
| `dev10x permission update-paths …` | `Bash(dev10x permission update-paths:*)` |

Both are matchable by a single rule per subcommand. Neither
embeds a plugin version. The MCP path is also stable
(`mcp__plugin_Dev10x_cli__update_paths`) — the upgrade-rot
problem is solved equally well by all three.

## Decision

- **Document `dev10x` (uv-tool-installed binary) as the preferred
  invocation form** in `Dev10x:plugin-maintenance` and other
  maintenance skills, with `uvx dev10x` as the zero-install
  fallback.
- **Recommend `uv tool install` in `Dev10x:onboarding`** so new
  users land on the faster path automatically; offer the same
  recommendation in `Dev10x:plugin-doctor` when it detects only
  `uvx dev10x` allow rules.
- **Keep the MCP tool layer in place** for skills that already
  bind to it (e.g., `update_paths` is still consumed by callers
  outside `plugin-maintenance`); do not deprecate `mcp__plugin_
  Dev10x_cli__update_paths`.
- **Ship `Bash(dev10x:*)` in `projects.yaml` base_permissions**
  so the binary is silent-permit out of the box once `uv tool
  install` has been run. The narrower per-subcommand rules
  (`Bash(dev10x permission ensure-base:*)`, etc.) remain
  available for users who want to lock the surface down further.

## Consequences

### Positive

- New invocations of `Dev10x:plugin-maintenance` save ~260 ms per
  full run (~20 ms × 13 steps) once the user has run
  `uv tool install`. Small, but visible on cold sessions where
  the maintenance run is the first thing the user does.
- Direct `dev10x` invocation parses subcommand help and errors
  faster than `uvx` — the perceived responsiveness gap is larger
  than the 20 ms median suggests because `uvx` blocks for the
  full resolve before printing anything.
- The new allow-rule shape (`Bash(dev10x:*)` or per-subcommand)
  is the shortest and most readable form. It does not include
  `uvx` as a prefix that future Claude Code UI option-2
  acceptance could broaden to `Bash(uvx *)` — the GH-310
  catch-all footgun is one prefix narrower.

### Negative

- Two documented invocation styles (`dev10x` and `uvx dev10x`)
  means SKILL.md docs must show both or pick one and footnote the
  other. We choose: lead with `dev10x`, footnote the `uvx`
  fallback at the top of the workflow section. Users who skipped
  `uv tool install` still get a working command.
- `uv tool install` adds a one-time onboarding step. Mitigated by
  `Dev10x:onboarding` running it automatically and
  `Dev10x:plugin-doctor` detecting the missing binary.
- An editable install (`uv tool install --editable .`) pins the
  binary to a specific worktree. For everyday users we recommend
  a non-editable install from the cache; the editable form is for
  plugin contributors hacking on `dev10x` itself.

### Neutral

- The `~1.8 s` floor remains. It is dominated by file I/O across
  settings trees and is the same regardless of invocation path.
  See the *Follow-ups* section for the MCP daemon idea that
  could move that floor.

## Follow-ups

1. **`Bash(dev10x:*)` base permission** — add to
   `skills/upgrade-cleanup/projects.yaml` so users who install
   the binary do not have to approve it manually.
2. **`Dev10x:onboarding`** — install `dev10x` via
   `uv tool install` (non-editable, from the cached plugin path)
   as part of bootstrap. Document the editable variant for
   contributors.
3. **`Dev10x:plugin-doctor`** — detect when the binary is missing
   from `PATH` and suggest the install command.
4. **`Dev10x:plugin-maintenance` SKILL.md** — lead with
   `dev10x permission <subcommand>`; footnote `uvx dev10x …` as
   the zero-install fallback.
5. **MCP daemon / pre-warmed CLI** *(separate ticket)* — the 1.8 s
   floor is real file I/O. A pre-warmed worker that keeps the
   settings tree parsed in memory and answers commands over a
   socket would push this to sub-100 ms. Out of scope for this
   ADR — file as a research ticket.

## References

- GH-269 — Retire version-pinned `update-paths.py` cache shim;
  introduce `uvx dev10x permission` CLI.
- GH-306 — Route remaining MCP-using steps through `uvx dev10x
  permission <subcommand>` for consistency.
- GH-310 — `Bash(<verb> *)` catch-all UI footgun (option-2 accept
  hazard); narrower allow rules reduce the blast radius.
- Benchmark script: `/tmp/Dev10x/bench-uvx-vs-mcp.py` (one-off,
  not committed). 5 iterations per case, medians reported.
- `Dev10x:plugin-maintenance` `skills/plugin-maintenance/SKILL.md`.
