# Phase 3 — Strategy Decisions

Each decision surfaces pros/cons and a recommended default before asking.
Batch related decisions into a single `AskUserQuestion` call (1–4
questions per call). Each option's `description` carries its trade-offs so
the user chooses with the pros/cons in view.

Under `friction_level: adaptive`, auto-select the recommended option for
each decision but still emit the gate so the user retains override.

## 1. Review depth

| Option | Pros | Cons | Recommend when |
|--------|------|------|----------------|
| **Domain-routed multi-agent** | Precise, scoped checklists; lower per-domain noise; reviewers evolve independently | Needs `.claude/agents/reviewer-*.md` + a routing table (more scaffolding) | ≥2 distinct domains discovered (default) |
| **Single-pass** | Zero agent scaffolding; fastest to adopt | Noisier, less tailored; one prompt must cover every domain | 0–1 domains, or "just get something running" |

Resolve to `strategies.depth = routed | single`.

## 2. Model tiering

Two tier roles: **classify** (cheap, read-only review/classification) and
**capable** (stronger, multi-turn agentic git ops — ADR/lessons PRs that
commit and push).

| Option | Pros | Cons | Recommend |
|--------|------|------|-----------|
| **Split tiers** (classify review + capable agentic) | Cheap where reads dominate; reliable where commits/pushes happen | Two model names to track | default |
| **Single capable tier everywhere** | Simplest; most reliable | Higher cost on high-frequency read-only review | budget not a concern |
| **Single classify tier everywhere** | Cheapest | ⚠️ cheap tiers tend to exit silently mid-task on commit/push steps — ADR/lessons jobs become unreliable | only if ADR/lessons are off |

Resolve to `strategies.model_classify` and `strategies.model_capable`
(concrete model names). Put the silent-exit warning in the prompt of any
agentic workflow so the risk is visible at the call site.

## 3. Action pinning

`claude-code-action` reference in every workflow.

| Option | Pros | Cons | Recommend when |
|--------|------|------|----------------|
| **Pin to a SHA** | Reproducible; no silent model-tier or behavior drift | Needs periodic manual bumps | shared/stable repos (default) |
| **Float on a major tag** (`@v1`) | Auto-receives action improvements | Drift; a release can change behavior unannounced | fast-moving solo repos |

Resolve to `strategies.action_ref` — either `anthropics/claude-code-action@<sha>`
(ask the user for / look up a current SHA) or `anthropics/claude-code-action@v1`.

## 4. API-key strategy

| Option | Pros | Cons | Recommend when |
|--------|------|------|----------------|
| **Single key** | One secret to manage | High-frequency hygiene shares the rate-limit budget | most repos (default) |
| **Dedicated hygiene key** | Rate-limit isolation for the noisiest job | A second secret to provision | hygiene on AND `second_key_present` |

Resolve to `strategies.hygiene_key_secret` (defaults to the primary review
secret; set to the second key only when chosen).

## 5. Lessons-learned destination

Only ask when the Lessons-Learned module is selected.

| Option | Pros | Cons | Recommend |
|--------|------|------|-----------|
| **Auto-apply to scope-locked draft PR** | Mechanical fixes land with review gate; provenance in git blame | Needs all guardrails (scope-lock, sanitization, size budgets, single-PR lock) | default |
| **Report-only as an issue** | Zero auto-write risk | Improvements require manual transcription | conservative repos |

Resolve to `strategies.lessons_dest = draft_pr | issue`. When `draft_pr`,
the guardrails in `sanitization.md` are mandatory and non-negotiable.

## 6. Notifications

| Option | Pros | Cons | Recommend when |
|--------|------|------|----------------|
| **Slack webhook on** | ADR/lessons output reaches the team channel | Needs a webhook secret | `slack_webhook_present` |
| **Off** | No extra secret | Output only on GitHub | default |

Resolve to `strategies.notify_slack = true | false` and, when true, the
webhook secret name.

## Batching example

Decisions 1–4 (and 6) are independent of module-specific gates, so batch
them:

```
AskUserQuestion(questions=[
  {question: "Review depth?", header: "Depth", options: [<routed (recommended)>, <single-pass>]},
  {question: "Model tiering?", header: "Models", options: [<split (recommended)>, <single capable>, <single classify>]},
  {question: "Pin the action to a SHA or float on @v1?", header: "Pinning", options: [<pin (recommended)>, <float>]},
  {question: "API-key strategy for hygiene?", header: "API keys", options: [<single (recommended)>, <dedicated hygiene key>]}
])
```

Ask decision 5 (lessons destination) and 6 (notifications) only when their
modules/conditions apply — fold them into the batch if room remains (max 4
questions per call; spill into a second call otherwise).
