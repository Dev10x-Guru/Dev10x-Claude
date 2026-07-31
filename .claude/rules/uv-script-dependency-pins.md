# uv-Script Dependency Pins (GH-916)

Every PEP 723 uv-script dependency and every `pyproject.toml` dependency
array entry MUST declare an upper bound. Companion to
`cwd-discipline.md` (CWD/subprocess routing) and
`script-domain-boundaries.md` (print/exit conventions) — those two
cover *how* uv-scripts run; this one covers *what they can install*.

## Why

`uv run --script` re-resolves a PEP 723 script's inline dependency
block on every invocation. An unbounded requirement (`pyyaml`,
`click>=8.0` with no `<`) installs whatever is newest at run time, so
the script's behaviour can change without any commit touching it.

GH-914 hit this concretely: `mcp` 2.0 removed `mcp.server.fastmcp`,
and because both MCP server entry points are uv-scripts with an
unbounded `mcp` requirement, every session silently lost all Dev10x
tools the day 2.0 published — no error, no diff, just missing tools.
The same exposure existed in ~30 other uv-scripts (hooks, skill
scripts, `pyproject.toml` itself) before GH-916 backfilled bounds
across all of them.

## Rule

- Every dependency string in a `# dependencies = [...]` PEP 723 header
  needs a `<` (upper bound) or `==` (exact pin) somewhere in its
  specifier — e.g. `pyyaml>=6.0,<7`, not bare `pyyaml` or `pyyaml>=6.0`.
- Every entry in `pyproject.toml`'s `[project.dependencies]` and
  `[project.optional-dependencies.*]` arrays follows the same rule.
- **Exception**: `# requires-python = ">=3.11"` (or `>=3.12`) is
  intentionally NOT bounded. Python doesn't churn breaking major
  versions the way PyPI packages do, and capping it would block a
  script from running on a newer interpreter it only needs a floor
  version to support.
- Pick the upper bound at the next major version boundary for a
  stable (1.0+) package (`click>=8.0,<9`), and at the next minor for a
  pre-1.0 package where minors carry breaking changes
  (`pytest-asyncio>=0.24,<0.25`).

## Enforcement

- **Detector**: `dev10x.dependency_pins` (`src/dev10x/dependency_pins.py`)
  — a single shared module so the pytest suite and the pre-commit hook
  can never drift on what counts as "bounded."
- **Tests**: `tests/test_dependency_pins.py` — full-repo scan plus unit
  coverage of the detector's edge cases (indented docstring examples
  that merely describe the syntax must NOT trip a false positive).
- **Pre-commit**: `bin/check-dependency-pins.py`, wired into
  `.pre-commit-config.yaml` as a local hook — runs in the canonical
  lint suite (`pre-commit run --all-files`), not only under `pytest`.

## Reviewer checklist

When a PR adds a new PEP 723 uv-script or edits `pyproject.toml`
dependency arrays:

1. Every new dependency string has an upper bound or exact pin.
2. `requires-python` is left lower-bound-only (not flagged).
3. `pre-commit run --files <changed files>` passes — the
   `dependency-pins` local hook exercises this automatically.
4. A newly-added package name reads as intentional (not a typo of an
   existing pinned dependency elsewhere in the same script).
