# CWD Discipline (GH-979)

In-process package code must respect the caller's effective working
directory. MCP server processes are long-lived and inherit the CWD they
were spawned in, so direct CWD access silently targets the wrong root
after `EnterWorktree`.

## Rules

- **Subprocess**: never call `subprocess.run(...)` directly. Use
  `subprocess_utils.run(...)` (sync), `async_run(...)` /
  `async_run_script(...)` (async), or `GitContext()` for git. All default
  `cwd` to the bound effective CWD.
- **Working directory**: never call `os.getcwd()` bare. Use
  `subprocess_utils.effective_cwd() or os.getcwd()` so a bound worktree
  wins and the process CWD remains the fallback.
- **No module-level `GitContext()`**: a module singleton caches the
  first-call toplevel permanently. Construct a fresh `GitContext()` per
  call (or `lambda: GitContext().toplevel`). Enforced by
  `tests/test_no_module_scope_gitcontext.py`.
- **Domain code resolves CWD via the domain seam, not `subprocess_utils`**
  (GH-584, audit N21): `domain/` modules (e.g. `domain/git_context.py`)
  call `dev10x.domain.cwd_resolver.resolve_cwd()` instead of importing
  `subprocess_utils.effective_cwd` — ADR-0008 Rule #1 keeps `domain/`
  free of outward dependencies. The infra layer (`subprocess_utils`)
  wires the concrete `effective_cwd` resolver into that seam at import
  time (infra → domain is the allowed inward direction). The
  `subprocess_utils.effective_cwd() or os.getcwd()` guidance above still
  applies to **adapter/infra** code; only domain modules use the seam.

## Standalone uv-script exception

Standalone uv-scripts (PEP 723 shebang, `dependencies = [...]`) run in
fresh isolated processes that cannot import `dev10x`, so their CWD is
already correct — leave them on `os.getcwd()` / `subprocess.run`. When
such a script is *also* imported as a module (dual-use, e.g.
`skills/audit/analyze_permissions.py` imported by `audit/analyze.py`),
apply the effective-CWD fallback at the importing package seam, not
inside the script.

## Enforcement

`tests/test_cwd_enforcement.py` checks MCP handlers with a `cwd`
parameter bind it; `tests/test_no_module_scope_gitcontext.py` checks no
module-scope `GitContext()` exists.
