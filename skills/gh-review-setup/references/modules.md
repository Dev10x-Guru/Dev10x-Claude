# Phase 2 — Module Menu

Each module is one independent workflow file with its own trigger and model
tier. Users adopt and budget each separately; concerns are never merged
into a mega-workflow.

## Module catalog

| Module | Workflow file | Trigger | Model tier | Default rule |
|--------|---------------|---------|------------|--------------|
| **Code Review** | `claude-code-review.yml` | `pull_request: [opened, ready_for_review, synchronize]` | classify | on (core) |
| **PR Hygiene** | `claude-pr-hygiene.yml` | `pull_request: [opened, ready_for_review]` | classify | on iff tracker present |
| **ADR Distillation** | `claude-adr-review.yml` | `pull_request: [closed]` (merged) | classify (analyze) + capable (author) | on iff `docs/adr/` or architectural surface |
| **Lessons-Learned** | `claude-memory-review.yml` | `pull_request: [closed]` | capable | recommend on iff `.claude/` rules exist |
| **Second-opinion** | `claude-second-opinion.yml` | `pull_request: [opened, synchronize]` | classify (second vendor) | off unless 2nd key/vendor configured |
| **Interactive (@mention)** | `claude.yml` | `issue_comment`, `pull_request_review_comment` containing `@claude` | classify | off (offer as add-on) |

"classify" and "capable" are tier *roles* resolved to concrete models in
Phase 3 (model tiering). Defaults: classify → a cheap read-only tier;
capable → a stronger multi-turn tier for agentic git ops.

## Default-state derivation (from discovery)

- **Code Review** — always pre-checked. It is the core module.
- **PR Hygiene** — pre-checked when `discovery.tracker != "none"`. A repo
  with no tracker has no `Fixes:` rule to enforce, so hygiene is noise.
- **ADR Distillation** — pre-checked when `docs/adr/` exists OR the
  discovered domains include cross-layer code (e.g., `migration` + `api`).
  Docs-only or config repos: off.
- **Lessons-Learned** — pre-checked when `existing_structure` is true (there
  are `.claude/` rules worth improving). This is the self-improving loop;
  recommend it whenever there is something to improve.
- **Second-opinion** — pre-checked only when `second_key_present` is true.
- **Interactive** — off by default; useful for teams that want `@claude`
  on-demand review.

## Decision gate (REQUIRED)

**REQUIRED: Call `AskUserQuestion`** (multiSelect=true). Do NOT use plain
text. Every module is independently skippable — skipping ADR/hygiene is
first-class, not a workaround.

```
AskUserQuestion(questions=[{
  question: "Which review modules should I scaffold? (pre-checked = recommended for this repo)",
  header: "Modules",
  multiSelect: true,
  options: [
    {label: "Code Review", description: "Domain-routed PR review on open/sync. Core module — recommended on."},
    {label: "PR Hygiene", description: "Title/body/commit checks on PR open. Recommended ON when a tracker exists; noise without one."},
    {label: "ADR Distillation", description: "Distill an ADR from a merged PR. Recommended when docs/adr/ or architectural surface exists."},
    {label: "Lessons-Learned", description: "Feed closed-PR review patterns back into .claude/ rules via a scope-locked draft PR. Recommended when .claude/ rules exist."},
    {label: "Second-opinion (multi-vendor)", description: "Independent second-vendor pass on open/sync. Needs a second API key. Off unless configured."},
    {label: "Interactive (@claude)", description: "On-demand review when someone @-mentions claude in a PR/issue comment. Off by default."}
  ]
}])
```

**Adaptive friction:** pre-select the discovery defaults (the modules whose
default rule resolves to on/recommended) and emit the call so the user can
still toggle. Do not skip the tool call.

Record the resolved set in `discovery.modules`. Phase 4 renders exactly the
selected modules — no more, no less.
