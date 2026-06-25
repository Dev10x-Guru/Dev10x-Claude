# Phase 4 — Scaffold

Render the selected modules from [`templates/`](templates/), filling
placeholders from the `discovery` record. Never copy a source project's
workflow and scrub it — render from templates so the output starts clean.

## Placeholder map

Every template token resolves from `discovery`:

| Token | Resolves to | Source |
|-------|-------------|--------|
| `{{REPO}}` | `${{ github.repository }}` (kept literal in the rendered YAML — GitHub fills it at run time) | constant |
| `{{DEFAULT_BRANCH}}` | e.g. `main`, `develop` | `discovery.default_branch` |
| `{{PATH_GLOBS}}` | newline `- "<glob>"` list for the workflow `paths:` filter | derived from `discovery.domains` |
| `{{ACTION_REF}}` | `anthropics/claude-code-action@<sha>` or `@v1` | `strategies.action_ref` |
| `{{MODEL_CLASSIFY}}` | cheap read-only tier model name | `strategies.model_classify` |
| `{{MODEL_CAPABLE}}` | capable agentic tier model name | `strategies.model_capable` |
| `{{REVIEW_KEY}}` | review API-key secret name | constant or user input |
| `{{HYGIENE_KEY}}` | hygiene API-key secret name | `strategies.hygiene_key_secret` |
| `{{SLACK_WEBHOOK_SECRET}}` | Slack webhook secret name | `strategies.notify_slack` |
| `{{SLACK_NOTIFY_BLOCK}}` | a final notify step posting output to Slack, or empty string when notifications are off | `strategies.notify_slack` |
| `{{TRACKER_FIXES_RULE}}` | tracker-specific `Fixes:` guidance + URL shape (placeholder workspace, never a real value) | `discovery.tracker` |
| `{{ROUTING_TABLE}}` | the generated INDEX.md routing rows | roster derivation below |
| `{{REVIEWER_ROSTER}}` | comma list of generated reviewer agent names | roster derivation below |
| `{{LESSONS_ALLOWLIST}}` | `CLAUDE.md`, `.claude/rules/*.md`, `.claude/agents/*.md`, `references/*.md` | constant (see sanitization.md) |
| `{{SIZE_BUDGETS}}` | per-file line caps | constant (see sanitization.md) |

`{{REPO}}` MUST render as the literal GitHub Actions expression
`${{ github.repository }}`, not a resolved slug — that is how the workflow
stays project-agnostic at run time and how repo slugs never get baked in.

## Render order

1. **Directories** — create only what the selected modules need and only if
   absent: `.github/workflows/`, and (for routed depth) `.claude/agents/`,
   `.claude/rules/`, `references/rules/`.
2. **Workflows** — for each selected module, render
   `templates/<module>.yml.tmpl` → `.github/workflows/claude-<module>.yml`.
3. **Routing + roster** (routed depth only) — generate the reviewer roster
   and `.claude/rules/INDEX.md` (below).
4. **Shared review references** — render
   `templates/review-guidelines.md.tmpl` and
   `templates/review-checks-common.md.tmpl` into `references/rules/`.
5. **Sanitization pass** — run `sanitization.md` over every rendered file.

## Reviewer-roster derivation (routed depth)

The roster is **discovery-driven** — one reviewer spec per present domain,
never a fixed list:

1. For each domain in `discovery.domains`, map to its reviewer name(s)
   via the table in `discovery.md` § "Languages / file types".
2. De-duplicate (a domain may map to a reviewer already added).
3. Always include `reviewer-generic` when any code domain is present.
4. For each resolved reviewer, render `templates/reviewer.md.tmpl` →
   `.claude/agents/reviewer-<domain>.md`, filling `{{DOMAIN}}` and pulling
   `{{DOMAIN_CHECKLIST}}` from the matching block in
   `templates/domain-checklists.md`. Skip if the file already exists —
   augment, never clobber. Tighten or drop checklist items that do not
   apply to the discovered stack.
5. Build the routing table: one row per domain mapping its glob(s) to its
   reviewer(s) and the shared `review-checks-common.md` reference. Render
   `{{ROUTING_TABLE}}` into `.claude/rules/INDEX.md` via
   `templates/INDEX.md.tmpl`.

Example: a repo whose domains are `{shell, docs, workflow-yaml,
claude-config}` produces reviewers `{reviewer-infra, reviewer-docs,
reviewer-claude-config}` (shell + workflow-yaml both map to infra) and a
3–4 row routing table — no Python reviewer, no migration/graphql rows. A
web-app repo with `{python, migration, graphql, frontend, tests}` produces
the corresponding larger roster. Neither is hardcoded.

## Existing-structure handling

When `discovery.existing_structure` is true:

- **Routing table** — merge new rows into the existing `INDEX.md` rather
  than overwriting; surface any conflicting row to the user before writing.
- **Reviewer specs / references** — skip files that already exist; report
  them as "kept existing" in the Phase 5 summary.
- **Workflows** — if a `claude-*.yml` already exists for a selected module,
  surface it and ask before overwriting (it may carry local tuning).

## Per-PR checklist block

The Code Review workflow maintains an idempotent checklist block in the PR
body between sentinel markers (`<!-- claude-review:start -->` …
`<!-- claude-review:end -->`) so re-runs replace the block rather than
appending. The template carries the markers; no per-repo customization
needed.
