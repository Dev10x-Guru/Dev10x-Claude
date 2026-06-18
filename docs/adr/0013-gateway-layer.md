# 13. Name the Gateway layer on `dev10x.github` and `subprocess_utils`

Date: 2026-06-18

## Status

Accepted

## Context

The 2026-06-10 architecture audit (finding behind GH-516) observed
that two modules implement the Gateway pattern (Fowler, *Patterns of
Enterprise Application Architecture*) without ever naming it:

| Module | External system | Uniform surface |
|---|---|---|
| `dev10x.github` | `gh` CLI + GitHub REST/GraphQL | `_gh_api_raw`, `async_run`, `async_run_script` |
| `dev10x.subprocess_utils` | OS subprocess boundary | `run`, `async_run`, `async_run_script` |

Both encapsulate access to an external system behind a single call
surface, inject cross-cutting concerns (GitHub auth via `as_bot`,
effective-CWD routing via `_effective_cwd` / `use_cwd`), and shield
callers from the raw interface. The pattern was fully present, but
neither module, nor any doc, named it. ADR-0006 records the *decision*
to keep an internal GitHub Gateway rather than adopt the official
GitHub MCP server, but it does not name the structural pattern — so a
contributor adding the next external integration (Slack, Linear) had
no template for how the boundary layer should be shaped.

## Decision

Name both modules as **Gateways** in their module docstrings, and
record the layer here so the vocabulary is discoverable:

- A Gateway wraps exactly one external system behind a uniform,
  in-process call surface.
- Cross-cutting concerns for that system (authentication, working
  directory, timeout, output parsing) live *inside* the Gateway, not
  at the call sites.
- Callers MUST go through the Gateway — they never invoke `gh` or
  `subprocess.run` directly. This is already enforced for subprocess
  CWD routing by `.claude/rules/cwd-discipline.md` (GH-979).

New external integrations should follow the same shape: one module,
one external system, a uniform surface, concerns injected internally.

## Consequences

- Reviewers and contributors share a name for the boundary layer, and
  a documented template for future integrations.
- No behavioural change — this ADR and the docstrings are descriptive;
  the code already implemented the pattern.
- Extracting an explicit `GitGateway` class from the free functions in
  `dev10x.git` (floated in the audit) is **deferred**: the free
  functions already present a uniform surface, and a class wrapper
  would be churn without a caller that needs polymorphism. Revisit if
  a second git backend or a test-double seam is ever required.
