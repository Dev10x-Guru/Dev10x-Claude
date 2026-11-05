# dev10x:reflect — Reflection Guide

## Reflection prompt

Answer each question from the transcript. Skip a question only when the
session gives it no material.

**Solution**

1. What was the goal, and what was the outcome? Is the outcome verified,
   or still open?
2. What was the root cause? What evidence settled it (query, log line,
   code path)? Which hypotheses were ruled out, and how?
3. What changed (code, data, config)? Who applied it? How was it checked?

**Platform**

4. Which flow did the session trace end to end? Write it as a numbered
   map: entry point → services → models → side effects, with `path:line`.
5. Which preconditions, flags, statuses or data shapes gate that flow?
   Which of them were surprising?
6. Which gap between layers showed up? Examples: the schema allows X but
   the code assumes not-X; frontend and backend disagree; test fixtures
   drift from real data.
7. Which ticket-worthy defect was found but not fixed? Give a draft
   title and note that it was not filed.

**Access and tooling**

8. What blocked access to an environment, database, browser or log, and
   what was the workaround? Which existing note explains it?
9. Which command, query or tool call should the next session reuse as is?

**Way of working**

10. Where did a hand-off between the user and the agent cost a
    round-trip (split SQL, typo, missing URL, wrong assumption)? What
    shape avoids it?
11. Did the user correct the agent's approach? That goes to agent
    memory as feedback, not to the vault.

**Memory**

12. Which existing memories cover topics this session touched, and which
    did it prove stale?
13. What live state does the session leave behind — something disabled,
    a deadline, a manual stop-gap, a pending decision? Each gets a
    project memory with its "never do X" rule.

## Keep or drop

| Keep (durable) | Drop (trivia) |
|---|---|
| A flow map, gate or invariant of the platform | The order in which files were opened |
| A reproducible query or command | One-off tool hiccups with no pattern |
| A data shape a test entity needs | Retries that succeeded |
| An access gate and its check command | IDs only meaningful inside this transcript |
| A defect class with a count ("306 stores") | Exact phrasing of interim messages |

## Placement map

Folder kinds resolve to vault folders through the `folders:` config key
(`references/configuration.md`). A kind missing from config falls back
to `retro`.

| Lesson kind | Folder kind | Note type |
|---|---|---|
| Session retro, investigation, platform flow | `retro` | Session Retro |
| Platform reference too long for a retro (a flow map, a gate table) | `platform` | Reference |
| Team process, release, review practice | `process` | Reference |
| General pattern or technique, beyond this project | `patterns` | Pattern |
| Agent-behavior correction | agent memory, not the vault | — |

Retro filename: `YYYY-MM-DD <Subject> — <outcome or topic>.md`, dated on
the day the work finished.

## Retro template

Adjust the front matter to the vault's own conventions when
`rules_note` names them.

```markdown
---
type: Session Retro
title: <Subject — topic>
description: <one sentence: problem, fix, what the lessons cover>
tags: [retro, <area>, ...]
status: draft            # stable only when no [Verify] remains
generated: { by: <agent and model>, at: <ISO datetime with offset> }
sources:
  - id: <slug>
    resource: <repo path or query descriptor>
    title: <label>
created: <YYYY-MM-DD>
---

# <Subject — topic>

**Outcome (<date>):** <done / partially done / open — one or two lines>.

## What was wrong
<affected entities + the root cause in one paragraph, with footnotes;
link the pattern note that found it>

**Fix applied (by <role>, <how>):** <one line>

## How <flow> works
1. <entry point> → …
2. …

## Lessons — platform
- **<Rule in bold>.** <evidence, number, path>

## Lessons — access and tooling
- …

## Lessons — way of working
- …

[^slug]: <path:line> — <symbol>
```

Keep it at or under 150 lines. Longer means a flow map deserves its own
`platform` Reference note, linked from the retro.
