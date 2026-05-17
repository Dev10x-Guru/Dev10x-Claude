# 6. Keep internal GitHub MCP server over adopting github/github-mcp-server

Date: 2026-05-17

## Status

Accepted

## Context

The Dev10x plugin ships an internal MCP server (`servers/cli_server.py`,
registered as `mcp__plugin_Dev10x_cli__*`) that exposes 41 tools wrapping
`gh` CLI, local git, and Dev10x-specific workflow primitives. GitHub
publishes an official MCP server at
[github/github-mcp-server](https://github.com/github/github-mcp-server)
exposing ~80 tools covering the public REST + GraphQL surface.

The question raised this session: should Dev10x adopt the official
server and drop the internal one (or layer over it)?

### Current State

- 41 tools in `src/dev10x/mcp/server_cli.py`, registered via
  `@server.tool()` and consumed by skills through `allowed-tools:`
  declarations.
- Tool contracts are Dev10x-shaped: composite calls bundle local git
  state, GitHub API calls, file I/O, plan-sync state, JTBD generation,
  and audit logging in one invocation.
- Skills branch on documented return shapes (e.g. `push_safe` returning
  `{}` is success per `.claude/rules/mcp-tools.md`, GH-152).
- Auth is delegated to the host `gh` CLI — no separate PAT/App secret.

### Problems

1. The 41 tools include several that *look* like thin GitHub API
   wrappers (`issue_get`, `issue_create`, `pr_comments`,
   `request_review`, `update_pr`, `create_pr`). Surface duplication
   with the official server suggests potential redundancy.
2. New GitHub capabilities (Actions, Dependabot, code scanning,
   discussions, notifications) are not exposed by the internal server
   today. The official server covers all of them.
3. Maintenance cost of in-house wrappers vs. consuming a
   first-party server.

### Prerequisites

- `.claude/rules/mcp-tools.md` — naming and return-shape contracts
- `references/permission-architecture.md` — allow-rule shapes for
  `mcp__plugin_Dev10x_cli__*`
- The friction-reduction objective of the internal MCP layer

## Decision

We will **keep the internal `Dev10x:cli` MCP server as the sole
GitHub surface** and **not adopt** `github/github-mcp-server` —
neither as a replacement nor as an adapter layer underneath our
tools.

When new GitHub capabilities are needed (Actions, code scanning,
notifications, etc.), we will add them as **Dev10x-shaped composite
tools** to the internal server, cribbing GraphQL queries and endpoint
choices from the official server's source as a reference.

### Rationale

The internal MCP exists to **collapse a workflow into one call** with
a contract aligned to Dev10x skills. The official server exposes the
REST/GraphQL primitives flat, requiring agents to chain 2–5 calls
where one Dev10x call suffices. Loading ~80 official tools into every
session's tool registry to reclaim ~10 overlaps inverts the very
metric the internal MCP optimizes for (context weight + friction).

## Overlap Map

Coverage of Dev10x tools against the official server.

### Direct overlap (≈10 tools)

| Dev10x tool | Official equivalent | Notes |
|---|---|---|
| `issue_get` | `issue_read` | Direct |
| `issue_create` | `issue_write` | We add milestone-title → ID lookup |
| `issue_comments` | `issue_read` (comments) | Direct |
| `pr_comments` (list/get) | `pull_request_read` | Partial |
| `pr_comment_reply` | `add_reply_to_pull_request_comment` | Direct |
| `request_review` | `pull_request_review_write` | Direct |
| `create_pr` | `create_pull_request` | We also push + post summary + JTBD body |
| `update_pr` | `update_pull_request` | Direct |
| `collect_prs` | `search_pull_requests` + `list_pull_requests` | Partial |

### Gaps in the official server (≈8 tools)

Capabilities the official server does not expose, blocking any
straight replacement.

| Dev10x tool | Why not covered |
|---|---|
| `minimize_comments` | GraphQL `minimizeComment` not exposed |
| `resolve_review_thread` | GraphQL `resolveReviewThread` not exposed |
| `unresolved_threads` | Needs GraphQL `reviewThreads { isResolved }` walk |
| `pr_comments` (resolve action, `unresolved_only`) | Same — review-thread state |
| `verify_pr_state` | Composite: working-copy + branch sync + remote |
| `pre_pr_checks` | Composite local + remote checks |
| `ci_check_status` | Partially covered by `actions_*`; we bundle into one call |
| `milestone_close` | Not in official toolset |

### Out of scope for any GitHub MCP (≈18 tools)

Local-only or cross-system tools that the official server cannot
replace by design.

| Category | Tools |
|---|---|
| Local git | `push_safe`, `rebase_groom`, `create_worktree`, `next_worktree_name`, `start_split_rebase`, `mass_rewrite`, `setup_aliases`, `generate_commit_list`, `update_paths` |
| Tracker abstraction (GH/Linear/JIRA) | `detect_tracker`, `pr_detect`, `detect_base_branch` |
| Composite GH+local | `post_summary_comment`, `pr_notify` |
| Dev10x plumbing | `plan_sync_set_context`, `plan_sync_json_summary`, `plan_sync_archive`, `mktmp`, `audit_extract_session`, `audit_analyze_actions`, `audit_analyze_permissions`, `audit_hook_log_path`, `audit_hook_recent`, `generate_skill_index`, `check_top_level_comments` |

### Capability the official server has and we don't (≈8 areas)

Net-new functionality not currently in `Dev10x:cli`.

| Capability | Official tools |
|---|---|
| GitHub Actions | `actions_get`, `actions_list`, `actions_run_trigger`, `get_job_logs` |
| Code scanning | `get_code_scanning_alert`, `list_code_scanning_alerts` |
| Dependabot | `get_dependabot_alert`, `list_dependabot_alerts` |
| Secret scanning | `get_secret_scanning_alert`, `list_secret_scanning_alerts` |
| Discussions | `list_discussions`, `get_discussion`, `discussion_comment_write`, … |
| Notifications | `list_notifications`, `dismiss_notification`, … |
| Copilot agent | `assign_copilot_to_issue`, `request_copilot_review`, … |
| Security advisories | `list_global_security_advisories`, … |

## Alternatives Considered

### Alternative 1: Full replacement

Drop `Dev10x:cli` GitHub tools, depend on
`github/github-mcp-server` for the GitHub surface.

**Pros:**
- Eliminates ~10 wrappers from our maintenance load
- Net-new capability (Actions, Dependabot, etc.) immediately
- First-party server may track API changes faster

**Cons:**
- ~80 tools loaded into every session's tool registry — inverts the
  friction-reduction goal
- Loses every Dev10x-shaped composite call; agents must chain
  primitives
- GraphQL gaps (`resolveReviewThread`, `minimizeComment`,
  `reviewThreads`) block `gh-pr-respond` flow entirely
- Auth becomes a separate PAT/App secret to provision
- Return-shape contracts (`push_safe == {}` = success, GH-152) and
  ~10 allow-rules across skills would need rewriting

**Verdict:** Rejected — costs land on the metric we optimize for
(context weight, composite contracts) without removing the long
tail of local-only and tracker-abstraction tools.

### Alternative 2: Layer the official server underneath our wrappers

Keep Dev10x tool surface; rewrite implementations to call the
official server's tools instead of `gh` / REST directly.

**Pros:**
- Preserves Dev10x skill contracts
- Stops maintaining auth/transport for GitHub

**Cons:**
- Still pays the ~80-tool registry weight per session
- Adds an adapter layer for every wrapper — doubles maintenance
- Inherits the official server's contract drift on every release
- GraphQL gaps still force us to keep `gh api graphql` shell-outs
  for review-thread tools
- `gh` shell-out already inherits enterprise/proxy config for free

**Verdict:** Rejected — strictly worse than the status quo. Pays
the registry cost and the adapter cost without removing either the
GraphQL fallback or the local-git tools.

### Alternative 3: Hybrid — both servers loaded, used selectively

Load official server for net-new capability (Actions, security
alerts, notifications); keep internal for everything else.

**Pros:**
- Immediate access to net-new GitHub features
- No migration of existing skills
- Could be enabled per-skill via `allowed-tools:` scoping

**Cons:**
- Permanent +80 tools in session context
- Two GitHub auth paths to provision and document
- Skills authors now have to choose between two servers for any
  new feature — friction multiplier on the team
- Encourages flat-primitive chaining when net-new capability gets
  used, drifting away from the Dev10x composite-call pattern

**Verdict:** Rejected — the only win is "immediate access" to
features we are not currently blocked on. The context-weight and
two-auth-paths costs are paid every session.

### Alternative 4: Stay internal, add capabilities as Dev10x-shaped tools

Keep `Dev10x:cli` as the sole GitHub surface. When a new GitHub
capability is needed, add a composite tool to the internal server
shaped to the workflow (not the REST endpoint).

**Pros:**
- Zero migration cost
- Net-new capabilities land as one-call workflows, not 3-step chains
  (e.g. `ci_failures(pr=…)` → failing job + log excerpt + suggested
  fix-up branch, instead of `actions_list` → `actions_get` →
  `get_job_logs`)
- No additional auth provisioning
- Tool registry grows only with what skills actually use
- We can crib GraphQL queries and endpoint choices from the official
  server's source without taking it as a runtime dependency

**Cons:**
- We do the implementation work for net-new capabilities ourselves
- Need a convention for when a new tool is worth adding (see
  Implementation Plan)

**Verdict:** Selected.

## Consequences

### What Becomes Easier

1. Adding net-new GitHub capabilities follows the existing pattern —
   one composite tool per workflow, documented in
   `.claude/rules/mcp-tools.md`.
2. Skill authors have a single GitHub surface to learn and grep.
3. Auth, return-shape contracts, and allow-rule shapes stay stable.

### What Becomes More Difficult

1. Capabilities the official server gets first (e.g. new
   Copilot-agent tools) require manual porting before Dev10x skills
   can use them.
2. We are responsible for tracking GitHub API changes for the
   endpoints we wrap.

### Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Internal server grows past ~60 tools and loading every one becomes the friction problem we said it wasn't | Medium | Medium | Steal the official server's *dynamic toolset gating* idea — gate tool registration by skill context if registry weight becomes measurable |
| GitHub API change breaks a wrapper we maintain | Low | Medium | Existing test coverage in `tests/`; `gh` CLI absorbs many breaking changes for us |
| Team unaware net-new capability already exists upstream | Low | Low | Reference the official server in `.claude/rules/mcp-tools.md` as the canonical "what's possible on GitHub" catalog |

## Implementation Plan

### Phase 1: Document the decision (this ADR)

1. Land ADR 0006 in `docs/adr/`.
2. Add a short note in `.claude/rules/mcp-tools.md` pointing readers
   here when they ask about the official server.

### Phase 2: Capability-add convention

When a Dev10x skill needs a GitHub capability not currently in the
internal server:

1. Check `github/github-mcp-server` for the relevant tool(s) — use
   it as an API reference.
2. Design a **composite** Dev10x tool shaped to the workflow, not
   one tool per endpoint.
3. Register it in `src/dev10x/mcp/server_cli.py` following the
   pattern in `.claude/rules/mcp-tools.md`.
4. Update the tool-availability table in `.claude/rules/mcp-tools.md`.

### Phase 3 (conditional): Toolset gating

Trigger: internal server passes ~60 registered tools, or session
context measurements show MCP-tool registration as a top-3
contributor.

1. Adopt a per-skill toolset filter (model the API after the
   official server's dynamic discovery).
2. Move plumbing tools (`audit_*`, `plan_sync_*`, `mktmp`,
   `generate_skill_index`) behind a gate so they don't appear in
   sessions that don't use them.

## References

### External Documentation

- [github/github-mcp-server](https://github.com/github/github-mcp-server)
- [MCP specification](https://modelcontextprotocol.io/)

### Internal References

- [.claude/rules/mcp-tools.md](../../.claude/rules/mcp-tools.md) —
  naming convention, return-shape contracts, tool availability table
- [.claude/rules/permission-architecture.md](../../references/permission-architecture.md) —
  allow-rule shapes for MCP tools
- [ADR 0003 — Allow rules as hook enablers](0003-allow-rules-as-hook-enablers.md)
- [src/dev10x/mcp/server_cli.py](../../src/dev10x/mcp/server_cli.py) —
  current tool registrations
