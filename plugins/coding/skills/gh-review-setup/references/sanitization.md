# Sanitization & Lessons-Learned Guardrails

Two jobs live here: the **global sanitization pass** that runs over every
rendered file in Phase 4/5, and the **lessons-learned guardrails** that the
`claude-memory-review.yml` workflow must embed when that module is selected.

## Global sanitization pass

Goal (AC): generated workflows contain **zero** project-identifying strings
from any source project.

Because the skill renders from placeholder templates (never copies a source
file), the output starts clean. The pass is the safety net that catches any
string that slipped through a template or a free-text answer.

### What to replace

| Class | Replace with |
|-------|--------------|
| Source-org / repo slug in a workflow (`<org>/<repo>`) | the literal `${{ github.repository }}` expression |
| Repo/org name in prose or a code example | `<project>` / `<org>` placeholder |
| Vendor/payment nouns (e.g. a specific gateway) in examples | `<gateway>` / generic noun |
| Domain jargon naming the source product (entity/role names) | generic `<entity>` / `<role>` |
| Incident IDs (`ABC-123` referencing a source project's history) | `<incident-id>` or drop |
| Sibling-service repo names | `<service>` placeholder |

### Pass procedure

1. Assemble a denylist from: the source projects this skill was modelled on
   (do NOT enumerate them in generated output — keep the denylist in the
   skill's run context only), plus any project-specific token the user
   typed during discovery that is not the *target* repo.
2. Grep every rendered file for each denylist token (case-insensitive).
3. Replace hits per the table above.
4. Re-grep to confirm zero hits. This is the Phase 5 gate — report the
   command and its empty output.

The target repo's own name is allowed only as `${{ github.repository }}`
(workflows) — never written as a literal slug.

## Lessons-Learned guardrails (mandatory when module selected)

The `claude-memory-review.yml` workflow's auto-implement step MUST embed all
four guardrails. They are non-negotiable when `strategies.lessons_dest =
draft_pr`.

### 1. Scope-lock (allowlist)

Auto-applied changes may touch ONLY:

```
CLAUDE.md
.claude/rules/*.md
.claude/agents/*.md
references/*.md            (and references/rules/*.md)
```

NEVER `skills/`, `.github/workflows/` (prevents an infinite review loop),
`bin/`, `hooks/`, `commands/`, or application source. The workflow prompt
states the allowlist explicitly and instructs the agent to abort the PR if
a proposed change falls outside it.

### 2. Domain-name sanitization

Before committing any rule text, the agent runs the same sanitization pass
above over BOTH prose and code examples. Provenance (which PR a lesson came
from) stays in git blame — never written into the rule text as `PR #N
showed…`. Distil the trade-off, not the anecdote.

### 3. Per-file size budgets

| File | Max lines |
|------|-----------|
| `CLAUDE.md` | 100 |
| `.claude/agents/*.md` | 50 |
| `.claude/rules/*.md` | 200 |
| `references/**/*.md` | 200 |

A change that would push a file past its budget is skipped (or the agent
must split/condense first). Budgets render into the workflow via
`{{SIZE_BUDGETS}}`.

### 4. Single open draft-PR lock

Only one lessons-learned draft PR may be open at a time. The workflow:

- uses a fixed branch name `claude/lessons-learned` (NOT per-PR), so a new
  run force-updates the existing branch instead of opening a parallel PR;
- checks for an existing open PR from that branch before creating one and
  updates it in place if found;
- opens the PR as **draft**, targeting `{{DEFAULT_BRANCH}}`, labeled with a
  dedicated maintenance label (e.g. `rules-maintenance`);
- never auto-merges — a human approves.

### Value filters (quality gate)

Before applying, each candidate improvement passes four filters; drop the
candidate if any fails:

1. **Deduplication** — the target file already covers the concept → skip.
2. **Recurrence** — the pattern appears in ≥2 PRs (not a one-off) → skip if
   insufficient evidence.
3. **Actionability** — a concrete check, not vague advice → skip if vague.
4. **Budget** — would exceed the file's size budget → skip.

Minimum-viable threshold: ≥2 candidates survive, or the run opens no PR.

## Report-only variant

When `strategies.lessons_dest = issue`, the workflow posts the analysis as a
GitHub issue (or PR comment) and applies nothing. The sanitization pass
still runs on the report text. The scope-lock and single-PR lock are moot;
size budgets and value filters still shape what is worth reporting.
