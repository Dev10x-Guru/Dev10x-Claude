# Phase 1 — Discovery

Build a `discovery` record consumed by Phases 2–5. Every command here is
read-only. Never assume a stack; detect it.

## Detection commands

All commands run from the repo root (the session CWD). Dump output to a
temp file (`mcp__plugin_Dev10x_cli__mktmp`) when a command's output feeds a
later parse step, per the no-pipe-chains convention.

### 1. Languages / file types

```bash
git ls-files
```

Tally extensions to find the dominant file types. Map extensions to
review domains:

| Extension / path | Domain | Reviewer template |
|------------------|--------|-------------------|
| `*.py` | python | `reviewer-generic`, `reviewer-security`, `reviewer-silent-failures` |
| `*.sh`, `bin/**`, `Makefile` | shell/infra | `reviewer-infra` |
| `.github/workflows/*.yml` | workflow-yaml | `reviewer-infra` |
| `*.md`, `docs/**`, `README.md` | docs | `reviewer-docs` |
| `*.svelte`, `*.astro`, `*.tsx`, `*.jsx`, `*.ts` | frontend | `reviewer-frontend` |
| `**/migrations/*.py` | migration | `reviewer-migration` |
| `**/api/queries.py`, `**/api/mutations.py`, `**/schema.py` | graphql | `reviewer-graphql` |
| `**/signals.py`, `**/handlers.py` | signals | `reviewer-signals` |
| `**/tasks.py`, `**/celery.py` | celery | `reviewer-celery` |
| `**/tests/**/*.py`, `**/e2e/**` | tests | `reviewer-tests` |
| `skills/**`, `.claude/agents/**`, `.claude/rules/**` | claude-config | `reviewer-claude-config` |

A domain is **present** when ≥1 tracked file matches its pattern. Only
present domains get a reviewer spec and a routing row — this is the core
discovery-driven decision. Always include `reviewer-generic` when any code
domain is present.

### 2. Existing `.claude/` structure

Use the Read tool (a not-found Read is the answer — avoids `test -f`
chaining):

- `.claude/rules/INDEX.md` — existing routing table → augment, don't replace
- `.claude/agents/` listing (`git ls-files .claude/agents`) — existing reviewers
- `references/rules/` listing — existing review references
- `CLAUDE.md` — exists? (lessons-learned target)
- `docs/adr/` — exists? (ADR module signal)

Record `existing_structure: true|false` and the specific paths found.

### 3. Issue tracker

```
mcp__plugin_Dev10x_cli__detect_tracker
```

Parse `tracker` (github | linear | jira | none). Determines:
- whether PR hygiene's `Fixes:` rule applies, and
- the issue-URL shape used in the hygiene prompt
  (`https://github.com/${{ github.repository }}/issues/N`,
  `https://linear.app/<workspace>/issue/`, or JIRA browse URL —
  the `<workspace>` segment is a placeholder, never a real value).

No tracker → hygiene defaults **off**.

### 4. Review API-key secret

```bash
gh secret list
```

Read-only — names only, never values. Record:
- `review_key_present`: is the chosen review secret name in the list?
- `second_key_present`: is a second key available for rate-limit isolation?
- `slack_webhook_present`: is a Slack webhook secret present (notifications)?

If `gh secret list` is denied (no admin scope), record
`secrets_unknown: true` and proceed — Phase 5 prints the required names
regardless.

### 5. Default branch

```
mcp__plugin_Dev10x_cli__detect_base_branch
```

Returns the repo's base/default branch (prefers `develop`/`development`,
falls back to `main`/`master`/`trunk`). Fallback when the MCP tool is
unavailable: `git symbolic-ref refs/remotes/origin/HEAD`. Record
`default_branch`. Feeds workflow base-branch targets and the
lessons-learned auto-PR base.

## Discovery record schema

```json
{
  "domains": ["python", "shell", "docs", "workflow-yaml"],
  "existing_structure": true,
  "existing_paths": [".claude/rules/INDEX.md", "CLAUDE.md"],
  "tracker": "github",
  "default_branch": "main",
  "review_key_present": true,
  "second_key_present": false,
  "slack_webhook_present": false,
  "secrets_unknown": false,
  "modules": [],
  "strategies": {}
}
```

`modules` and `strategies` are filled by Phases 2 and 3.

## Summary block

Present before Phase 2 (informational, not a gate):

```
Discovery summary
  Domains:        python, shell, docs, workflow-yaml  (4)
  Existing .claude/: yes (INDEX.md, CLAUDE.md)
  Tracker:        github
  Default branch: main
  Review secret:  ANTHROPIC_API_KEY present
  Second key:     none
  Slack webhook:  none
```
