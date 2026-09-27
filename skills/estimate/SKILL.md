---
name: dev10x:estimate
description: >
  Estimate how long a ticket or project will take when AI agents do
  the implementation and humans still gate review, testing and
  release — so a lead plans on numbers that match how the work
  actually ships, instead of one engineer's human-pace guess.
  TRIGGER when: sizing a ticket or project, filling an "estimated
  complexity" column, or answering "how long would it take to…?",
  "what would it take to…?", "when could this ship?" — inside or
  outside a scoping skill.
  DO NOT TRIGGER when: tracking time already spent (use a time
  tracker), or reporting what shipped (use dev10x:release-notes).
user-invocable: true
invocation-name: dev10x:estimate
allowed-tools:
  - Read
  - Grep
  - Glob
  - mcp__plugin_dev10x_cli__pr_list
  - mcp__plugin_dev10x_cli__pr_get
---

# dev10x:estimate — Agent-Built Work Estimation

**Announce:** "Using dev10x:estimate to size [ticket/project]."

This is the single source of truth for estimation in Dev10x.
`dev10x:project-scope`, `dev10x:ticket-scope` and `dev10x:work-on`
delegate here, and the SessionStart guidance points every other
estimate here too (GH-1495).

## Why this exists

Claude's default estimate assumes one engineer at human pace and
blends coding, testing and self-review into one number. It has no
review wait, no CI time, and no docs.
On agent-built work, that one number is wrong twice.
It overshoots the mechanical work agents finish in hours.
It also ignores the human gates, which dominate the calendar.
Evidence: release R1 of a Codex port was estimated at "1-1.5 weeks,
one engineer". Implementation, tests and live verification landed
the same day, and the review and merge were never counted.

## Method

### 1. Size the change in points

Points measure complexity and risk, not time.

| Points | Complexity | Typical shape |
|--------|------------|---------------|
| 1 | Trivial | One file, existing pattern, no new tests |
| 2 | Small | A few files, existing pattern |
| 3 | Medium | New tests, one module boundary crossed |
| 5 | Large | New pattern, or several modules |
| 8 | Complex | Cross-layer, migration, or external dependency |
| 13 | Epic-sized | **Split it** — do not estimate as one unit |

Raise one step for any of these: a new pattern rather than an
existing one, a database migration, an external dependency, or an
unfamiliar codebase area.

### 2. Break out the five line items

Every estimate reports all five.
A line that does not apply is stated as `0` with the reason, never
omitted.

| Line item | What it covers | Effort (hands-on) | Elapsed (calendar) |
|-----------|----------------|-------------------|--------------------|
| **Agent implementation** | Agent coding, agent-run tests, agent self-review | Supervisor briefing + steering | Agent wall-clock |
| **Human review** | Reading the diff, writing feedback, re-reading fixes | Reviewer hours | Same as effort |
| **Review wait** | Queue time until a reviewer picks it up, per cycle | `0` — nobody works | Often the dominant term |
| **Testing** | CI runs, manual/QA passes, live or end-to-end checks | QA and verification hours | CI wall-clock × cycles + QA |
| **Documentation** | User docs, release notes, internal process docs | Writer hours | Same as effort |

### 3. Apply the default ranges, then calibrate

Use these defaults only when the project has no history.
Prefer calibration.
List the last 15-20 merged PRs with `mcp__plugin_dev10x_cli__pr_list`,
and call `pr_get` only on the few you need review timestamps from.
Measure created-to-merged, review-requested-to-first-review and CI
duration, then replace the defaults and say which you used.

| Points | Agent elapsed | Supervisor effort | Review effort / cycle | Review cycles |
|--------|---------------|-------------------|-----------------------|---------------|
| 1 | < 30 min | 10 min | 10-15 min | 1 |
| 2 | ~1 h | 15-30 min | 15-30 min | 1 |
| 3 | 2-4 h | 30-60 min | 30-60 min | 1-2 |
| 5 | 0.5-1 day | 1-2 h | 1-2 h | 2 |
| 8 | 1-2 days | 2-4 h | 2-4 h | 2-3 |

Default review wait: 0.5-1 business day per cycle on a team repo.
On a solo-maintainer repo it is the supervisor's availability, often
same-day.
Default testing: the repo's CI duration × (review cycles + 1), plus
0-2 h of manual QA when the change is user-facing.
Default documentation: 0 h internal-only, 0.5-2 h user-facing.

### 4. Aggregate effort and elapsed separately

- **Effort** is the sum of hands-on hours across all five lines.
- **Elapsed** follows the critical path. Agent work on independent
  tickets runs in parallel. Review, review wait and QA run in
  sequence per ticket, and a single reviewer serialises every ticket
  they own.
- Never add review wait to effort. It adds calendar time and costs
  no one any work.

### 5. Project-level estimates

Estimate each ticket with steps 1-4, then roll up:

1. Group tickets by milestone and by blocking chain.
2. Agent implementation of unblocked tickets overlaps. Take the
   longest chain, not the sum.
3. Human review does not overlap for one reviewer. Sum review effort
   per reviewer, and add one review wait per cycle along the chain.
4. Report per milestone and for the whole project.

`dev10x:project-scope`'s "estimated complexity" column carries the
points from step 1 plus the ticket's elapsed range.

## Output format

```
Estimate — <ticket or project>          Points: <n> (<why>)
| Line item            | Effort   | Elapsed  |
|----------------------|----------|----------|
| Agent implementation | <h>      | <h/d>    |
| Human review         | <h>      | <h>      |
| Review wait          | 0        | <d>      |
| Testing              | <h>      | <h/d>    |
| Documentation        | <h>      | <h>      |
| **Total**            | **<h>**  | **<d>**  |
Basis: <calibrated from … | defaults>. Assumptions: <reviewer, CI time, QA need>.
```

## Anti-patterns

| Anti-pattern | Why it misleads | Instead |
|--------------|-----------------|---------|
| One number, "one engineer, 1-1.5 weeks" | Blends agent work with human gates and hides both | Five lines, effort and elapsed |
| Agent coding at human pace | Overshoots mechanical work by days | Agent-elapsed column above |
| Omitting review wait | Understates calendar time, usually the biggest term | State it, even as an assumption |
| Summing parallel agent work | Overstates elapsed on multi-ticket plans | Critical path, step 4 |
| Estimating a 13 | Too uncertain to plan on | Split, then estimate the parts |
