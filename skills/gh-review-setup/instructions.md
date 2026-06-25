# Dev10x:gh-review-setup — Instructions

Provision Claude code-review GitHub Actions on any repo. Five phases:
Discover → Pick modules → Strategy decisions → Scaffold → Verify & hand off.

The defining constraint: **nothing about the stack is hardcoded.** Path
globs, the domain-routing table, and the reviewer roster are all derived
from Phase 1 discovery. Templates in [`references/templates/`](references/templates/)
carry `{{PLACEHOLDER}}` tokens that later phases fill — you never copy a
source project's workflow and scrub it by hand.

---

## Phase 1 — Discover

Detect, don't assume. Build a `discovery` record consumed by every later
phase. See [`references/discovery.md`](references/discovery.md) for the
exact detection commands and the record schema.

Collect:

1. **Languages / file types present** — drives path globs and which
   `reviewer-*` specs to scaffold. Detect via `git ls-files` extension
   tally (read-only); never assume Python.
2. **Existing `.claude/` structure** — is there `.claude/agents/`,
   `.claude/rules/INDEX.md`, `references/rules/`, `CLAUDE.md`,
   `docs/adr/`? Existing structure means *augment*, not overwrite.
3. **Issue tracker** — GitHub Issues / Linear / JIRA via
   `mcp__plugin_Dev10x_cli__detect_tracker`. Determines whether PR
   hygiene's `Fixes:` rule applies and which URL shape it uses. No
   tracker → hygiene defaults **off**.
4. **Review API-key secret** — does the chosen review secret exist
   (`gh secret list`)? Note an optional second key for rate-limit
   isolation. Read-only: list names, never values.
5. **Default branch** — `gh repo view --json defaultBranchRef` (fallback
   `git symbolic-ref refs/remotes/origin/HEAD`). Feeds workflow base-branch
   targets and the lessons-learned auto-PR base.

Present a compact discovery summary (counts, detected tracker, default
branch, key presence) before Phase 2 — informational, not a gate.

**Mark Phase 1 task completed; auto-advance to Phase 2.**

---

## Phase 2 — Pick review modules

Each module = one independent workflow file with its own trigger and model
tier. Present the menu and let the user toggle each. Discovery sets the
default checkbox state per the table in
[`references/modules.md`](references/modules.md).

| Module | Trigger | Default rule |
|--------|---------|--------------|
| **Code Review** | PR open/sync | on (core — always offered) |
| **PR Hygiene** | PR open | on if a tracker exists; off for solo/no-tracker repos |
| **ADR Distillation** | PR merged | on if `docs/adr/` exists or architectural surface detected; else off |
| **Lessons-Learned** | PR closed | recommend on when `.claude/` rules exist to improve |
| **Second-opinion (multi-vendor)** | PR open/sync | off unless a second API key/vendor is configured |

**REQUIRED: Call `AskUserQuestion`** (multiSelect=true) — see
[`references/modules.md`](references/modules.md) for the full call spec.
Every module is independently skippable; skipping ADR or hygiene is
first-class. Under `adaptive`, pre-select the discovery defaults and emit
the call so the user can still toggle.

Store the selected module set in `discovery.modules`.

**Mark Phase 2 task completed; auto-advance to Phase 3.**

---

## Phase 3 — Strategy decisions

For each decision, surface pros/cons and a recommended default, then ask.
Batch related decisions into one `AskUserQuestion` call (1–4 questions).
Full per-option pros/cons live in
[`references/strategies.md`](references/strategies.md).

1. **Review depth** — single-pass vs domain-routed multi-agent.
   - Routed (recommended when ≥2 distinct domains discovered): precise,
     scoped checklists, lower per-domain noise; needs
     `.claude/agents/reviewer-*.md` + a routing table.
   - Single-pass: zero scaffolding, faster to adopt; noisier.
2. **Model tiering** — cheap classify tier for read-only review;
   capable tier for multi-turn agentic git ops (ADR/lessons PRs).
   - Recommended default: classify-tier review + capable-tier agentic.
   - Note in the prompt: cheap tiers tend to exit silently mid-task on
     commit/push steps — capable tier is REQUIRED for ADR/lessons jobs.
3. **Action pinning** — pin `claude-code-action` to a SHA vs float on a
   major tag.
   - Pin (recommended for shared/stable repos): reproducible, no silent
     model-tier drift; needs periodic bumps.
   - Float (`@v1`): auto-receives improvements; risk of drift.
4. **API-key strategy** — single key vs a dedicated key for the
   high-frequency hygiene job (rate-limit isolation).
   - Recommend a dedicated hygiene key only when hygiene is on AND a
     second key was discovered.
5. **Lessons-learned destination** (only if Lessons-Learned selected) —
   auto-apply mechanical fixes to a scope-locked draft PR (`.claude/` +
   `CLAUDE.md`, dedicated maintenance label) vs report-only as an issue.
   - Recommended: auto-apply to draft PR with all guardrails.
6. **Notifications** — Slack webhook on/off for ADR/lessons output.
   - Default off unless a Slack webhook secret was discovered.

Resolve every decision into `discovery.strategies`. Under `adaptive`,
auto-select recommended defaults but still emit each gate.

**Mark Phase 3 task completed; auto-advance to Phase 4.**

---

## Phase 4 — Scaffold (opinionated organization)

Render the selected modules from templates, filling placeholders from
`discovery`. See [`references/scaffold.md`](references/scaffold.md) for the
placeholder map, render order, the routing-table generator, and the
reviewer-roster derivation. See [`references/sanitization.md`](references/sanitization.md)
for the lessons-learned guardrails and the project-name sanitization pass.

Organization the skill produces:

- **Reviews** — shared `references/rules/review-*.md` (guidelines,
  false-positive prevention, checklist format) + per-domain
  `.claude/agents/reviewer-*.md` + a routing table in
  `.claude/rules/INDEX.md` + the per-PR checklist block between sentinel
  markers in the PR body.
- **Lessons-Learned** — ephemeral analysis report posted as a PR comment →
  mechanical, low-risk improvements auto-applied to `.claude/` + `CLAUDE.md`
  ONLY, via a single open draft PR (lock prevents conflicting parallel
  PRs), with domain-name sanitization (prose AND code examples) and
  per-file size budgets. Provenance stays in git blame, not in rule text.

Render steps:

1. Create directories as needed (`.github/workflows/`, `.claude/agents/`,
   `.claude/rules/`, `references/rules/`) — only those the selected
   modules require, and only if absent.
2. For each selected module, render its workflow template into
   `.github/workflows/claude-<module>.yml` with placeholders resolved.
3. If review depth = routed: generate the reviewer roster (one
   `reviewer-*.md` per discovered domain, adapted from the domain template)
   and the `.claude/rules/INDEX.md` routing table from the discovered
   globs. Generate shared `references/rules/review-guidelines.md` and
   `review-checks-common.md`.
4. Run the **sanitization pass** over every rendered file (see
   `references/sanitization.md`). Replace any project-identifying string
   with `${{ github.repository }}` (for repo slugs in workflows) or a
   generic placeholder (`<project>`, `<service>`, `<gateway>`) in prose
   and code examples.
5. Do NOT create or overwrite a file that already exists without
   surfacing it first — augment existing `.claude/` structure rather than
   clobbering it.

**Mark Phase 4 task completed; auto-advance to Phase 5.**

---

## Phase 5 — Verify & hand off

1. **Secrets** — print exactly which secrets to add and where (repo
   Settings → Secrets and variables → Actions). List each required secret
   name from the rendered workflows and whether it is already present
   (from Phase 1). Never create secrets.
2. **Sanitization gate (REQUIRED).** Grep every rendered file for known
   project-identifying strings (source org names, repo slugs, vendor/domain
   nouns gathered in `references/sanitization.md`). Zero hits is the pass
   condition. Report the exact command run and its (empty) output. A
   non-empty result blocks completion — fix and re-grep.
3. **Summary** — list installed workflow files, their triggers and model
   tiers, and the chosen strategies. Note which modules were skipped.
4. **Setup record** — write a structured record (chosen modules,
   strategies, any friction) to
   `.claude/Dev10x/gh-review-setup/setup-<default-branch>.json` and emit a
   skill-audit hook so the scaffolder's defaults can be tuned over time.
5. **Landing reminder** — remind the user to open a PR to land the
   workflows; link the tracking issue if one was provided.

**Task list invariant (GH-149):** leave a terminal `Verify AC` task open
when this skill runs standalone; do not mark it completed without explicit
supervisor sign-off.

---

## Flexibility Across Project Types

Nothing about a stack is hardcoded — examples of how discovery shapes
output:

- **Web app** with DB migrations + typed frontend → migration / API-schema
  / signals / background-task / frontend reviewers; full module set.
- **Dotfiles / skills / config repo** (shell + markdown + workflow-YAML) →
  shell + markdown + workflow-YAML reviewers; hygiene likely **off** (no
  tracker), ADR **off**, lessons-learned **on** (there *are* `.claude/`
  rules worth improving).

The non-Python config-repo path is the v1 dogfooding target — verify the
discovery-driven roster and skip-able modules hold up there.

---

## Anti-Patterns

- ❌ Reading a source project's `claude-code-review.yml` and editing it in
  place. Render from templates instead.
- ❌ Hardcoding `**/*.py` globs or a Django reviewer roster. Derive from
  discovery.
- ❌ Shipping lessons-learned without the scope-lock / sanitization /
  size-budget / single-PR-lock guardrails.
- ❌ Declaring done without running the Phase 5 sanitization grep gate.
- ❌ Merging concerns into one mega-workflow. Each module is a separate
  file with its own trigger and tier.
