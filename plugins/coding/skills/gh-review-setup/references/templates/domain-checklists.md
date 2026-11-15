# Domain Checklists

Per-domain checklist bodies for the `reviewer.md.tmpl` template. When the
roster derivation (see `scaffold.md`) emits a reviewer for a domain, fill
`{{DOMAIN_CHECKLIST}}` with that domain's block below. Only domains present
in the repo get a reviewer — these are a catalog, not a fixed roster.

These checklists are intentionally stack-agnostic where possible. Tighten
or drop items that do not apply to the discovered project.

## generic (any code)

- Functions/methods use clear names; behavior matches the name.
- Error paths are handled, not swallowed; failures surface with context.
- No dead code, no commented-out blocks, no debug prints left behind.
- Public interfaces have types/contracts where the language supports them.
- Edge cases (empty, null, boundary) are considered.

## security

- No hardcoded secrets, tokens, or credentials.
- Untrusted input is validated/escaped before use (injection, traversal).
- No `eval`/dynamic execution of untrusted data.
- Authn/authz checks are present on protected operations.
- Shell calls quote variables; no unsafe interpolation.

## silent-failures

- No bare `except`/`catch` that swallows the error.
- Caught exceptions are logged with context or re-raised.
- No control flow that hides a failure as a success return.
- Empty handlers have an explicit, justified reason.

## infra (shell / CI / build)

- Shell scripts set safe options (`set -euo pipefail` or equivalent).
- Workflow files pin actions appropriately and scope permissions minimally.
- No secret echoed to logs; no broad `permissions: write-all`.
- Idempotent, re-runnable steps; no hidden host assumptions.

## docs (markdown / docs)

- Links resolve; code fences specify a language.
- Structure is scannable (headings, lists); no contradictory guidance.
- Examples are runnable/accurate; no stale references.

## frontend

- Components handle loading/empty/error states.
- Accessibility basics (labels, roles, keyboard) on interactive elements.
- No unkeyed list rendering; no obvious render-loop hazards.
- SSR-safety: no direct DOM/window access during server render.

## migration (DB)

- No destructive change without a safe, reversible path.
- Backward-compatible with the currently-deployed code (expand/contract).
- Indexes/locks considered for large tables; no long table locks.
- Tenant/scope columns respected where the schema is multi-tenant.

## graphql / api

- Schema changes are backward compatible (no field removal without
  deprecation).
- Authorization enforced at the resolver/field level.
- Input validation present; errors are typed, not leaked internals.

## signals / handlers

- Handlers are idempotent and exception-safe (one failure does not break
  the dispatch chain).
- No heavy/blocking work in a synchronous signal; offload to a task.
- Lookup semantics correct (get vs filter; handle missing rows).

## celery / background tasks

- Tasks are named and registered/discoverable.
- Idempotent and retry-safe; no reliance on in-process state.
- Periodic registration correct; data-migration tasks are safe to re-run.

## tests

- Tests assert behavior, not implementation detail.
- No flakiness risk: no real time/randomness/order dependence; fixtures
  isolated.
- New code paths are covered; parametrize instead of branching in a test.

## claude-config (skills / rules / agents)

- Skill frontmatter complete (`name`, `invocation-name`, `allowed-tools`).
- Decision gates use the structured ask tool, not plain text.
- Files stay within their size budgets; no project-identifying strings.
