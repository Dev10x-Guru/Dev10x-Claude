# HTML Artifact Reporting (optional)

When a skill produces a **report, decision summary, or set of
alternatives for a human to read**, rendering it as an HTML artifact
is sometimes friendlier than a wall of markdown. This is an
**option**, never a requirement.

Companion to [`display-conventions.md`](display-conventions.md),
which covers how to render output *within* the terminal transcript.
This file covers the case where the output is long enough that the
transcript is the wrong container for it.

## Default stays markdown

Markdown in the transcript, and markdown committed to the repo,
remain the default for every skill. Nothing in this file adds a
step to any workflow, and **no completion gate may depend on an
artifact existing**. A skill's quality checklist passes on its
markdown deliverables alone.

## When it is worth reaching for

Consider an HTML artifact when two or more of these hold:

- The report is long — roughly a screen and a half or more of
  prose the supervisor is expected to actually read, not skim.
- It is **comparison-shaped** — options side by side, a decision
  matrix, a delivered/cut table across many rows. These are the
  cases where markdown tables wrap badly and lose their alignment.
- It will be **re-read later** or shared with someone who was not
  in the session.
- It carries structure that benefits from visual hierarchy —
  nested findings, per-item status, grouped alternatives.

## When markdown is the better answer

- Short summaries, single decisions, one-paragraph outcomes.
- Anything the supervisor needs to act on *immediately* in the
  session — an artifact is a detour.
- Anything that belongs in git as the durable record (see below).
- Anything a downstream tool parses.

## Durability: the artifact is a rendering, not the record

An artifact is a **view**. The record stays where it always was:
committed markdown, tracker comments, decision logs. Never move
content *out* of a git-tracked deliverable and into an artifact —
render alongside it, or render from it.

Concretely: a DDD workshop record still lands in
`workshops/NNN-topic.md`, and decisions still land in
`decisions.md`, whether or not an artifact is also published.

## Availability

Not every environment exposes an artifact-publishing tool, and the
plugin does not require one. Check whether the session actually has
such a tool before offering this; if it does not, produce markdown
and say nothing about artifacts. Skills pointing here do **not**
declare an artifact tool in their `allowed-tools:` — the capability
is environmental, not a skill dependency.

If the environment does expose one, follow that tool's own
guidance (self-contained page, theme-aware, responsive) rather than
anything restated here.

## Anti-patterns

- ❌ Making an artifact mandatory for a workflow step, or gating
  completion on one.
- ❌ Building tooling or scripts in this repo to auto-generate HTML
  reports. This is guidance about an existing capability, not a
  feature request.
- ❌ Publishing an artifact *instead of* writing the markdown
  deliverable — the artifact is not the durable record.
- ❌ Asking the supervisor whether they want an artifact for a
  three-line summary. Use judgment; the ask is itself friction.
