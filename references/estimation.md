# Estimation Method (GH-1495)

The one method every Dev10x estimate follows — `dev10x:estimate`,
`dev10x:ticket-scope` Phase 4, `dev10x:project-scope`'s complexity
column, and `dev10x:work-on` when the supervisor asks how long a plan
will take. It also replaces Claude's default estimate for any
ad-hoc "how long would it take to…?" question; the SessionStart
guidance points here for that reason.

## Why a separate method

Left to its default, Claude estimates as if one engineer types the
code at human pace, then blends coding, testing and self-review into a
single number. That is wrong in both directions at once:

- **It overshoots the mechanical work.** A 2026-09-27 session sized a
  release at "1-1.5 weeks, one engineer"; with parallel agents the
  implementation, tests and live verification landed the same day.
- **It ignores the human gates.** Review, the wait for a reviewer,
  manual QA and docs are the steps agents do not remove — and the
  default number has no slot for them.

## Rules

1. **Assume agent implementation.** Coding, agent-run tests and AI
   self-review are one line item sized at agent pace. Never size it
   as a human typing the code.
2. **Count the human gates separately.** Each gets its own line, even
   when it is zero — a zero is a claim, an omission is a gap.
3. **Report effort and elapsed separately.** Effort is hands-on
   time. Elapsed is calendar time. A review wait adds elapsed time and
   no effort, and it is often the dominant term.
4. **Keep the ceiling: 13 points means split.** An estimate that
   needs 13 is a signal to decompose, not a number to plan on.
5. **Name the assumptions.** Reviewer availability, CI duration and
   whether a live system is reachable change the answer; state which
   ones the number rests on.

## Line Items

| Line item | Covers | Effort owner |
|-----------|--------|--------------|
| **Agent implementation** | Code, agent-run tests, AI self-review, fixup rounds | Agent (supervisor attention only) |
| **Human review** | Reading the diff, writing feedback, iterating on replies | Reviewer |
| **Review wait** | Queue time until a reviewer picks the PR up | Nobody — elapsed only |
| **Testing** | CI runs, manual/QA verification, live or end-to-end checks | CI (elapsed), QA or supervisor (effort) |
| **Documentation** | User docs, release notes, internal process docs | Agent drafts, human approves |

**Review wait follows repo shape.** Resolve it from the project's
posture rather than guessing: `supervisor_review_status()` returning
`none` in a solo repo means the wait is effectively zero; a team repo
waits for the team's usual pickup time. When nobody has said, state
the wait you assumed.

## Size Scale (Fibonacci)

Points measure complexity and risk. The columns are a **starting
calibration** — replace them with a project's own observed numbers
once it has some.

| Points | Complexity | Agent implementation | Human effort (review + QA + docs) | Typical elapsed |
|--------|------------|----------------------|-----------------------------------|-----------------|
| 1 | Trivial | < 30 min | ~15 min | Same day |
| 2 | Small | 30-90 min | 30-60 min | Same day to 1 day |
| 3 | Medium | 2-4 h | 1-2 h | 1-2 days |
| 5 | Large | Half a day to a day | 2-4 h | 2-4 days |
| 8 | Complex | 1-2 days, several sessions | Half a day or more | About a week |
| 13 | Epic-sized | — | — | Split it |

The elapsed column assumes an ordinary review wait. It shrinks toward
the implementation time in a solo repo and grows with the queue in a
busy team one.

## What Moves the Number

**Raises agent implementation:**
- A new pattern with nothing in the codebase to copy
- Database migrations or data backfills
- External APIs, credentials or sandboxes the agent must wait on
- A live system the agent cannot reach — the human runs that step
- Flaky or slow CI that forces re-runs

**Raises human effort:**
- Risky domains (payments, auth, migrations) that warrant a deeper
  review
- UI changes that need manual QA on real devices or browsers
- User-facing behaviour that needs docs or release notes
- Cross-team changes that need more than one reviewer

## Output Format

### Ticket-level

```markdown
## Estimate — <TICKET-ID>: <title>

**Size:** <N> points (<complexity>)

| Line item | Effort | Elapsed | Notes |
|-----------|--------|---------|-------|
| Agent implementation | <e.g. 2-3 h> | <same> | <main driver> |
| Human review | <e.g. 45 min> | — | <reviewer> |
| Review wait | — | <e.g. 0-1 day> | <solo / team pickup> |
| Testing | <e.g. 30 min QA> | <e.g. 20 min CI> | <CI, manual, live> |
| Documentation | <e.g. 15 min> | — | <what docs> |
| **Total** | **<effort sum>** | **<calendar range>** | |

**Assumptions:** <reviewer availability, CI time, live access>
```

### Project-level

Estimate every ticket as above, then roll up. **Effort sums; elapsed
does not.**

- **Agent implementation runs in parallel.** Independent tickets
  (for example under `dev10x:fanout`) collapse to the longest chain on
  the blocking path, not the sum.
- **Review serializes on reviewers.** Elapsed review time follows the
  critical path of the blocking chain, bounded by how many PRs each
  reviewer can take per day.
- **Report per milestone** — effort, elapsed and critical path — plus a
  project total, and name the human gate that dominates elapsed time.

In `dev10x:project-scope`'s "estimated complexity" column, write the
points plus the elapsed range (for example `3 pts · 1-2 days`) and
keep the full table in the scope document.

## Anti-Patterns

| Anti-pattern | Why it's wrong | Instead |
|--------------|----------------|---------|
| "1-1.5 weeks, one engineer" | Human-pace default, one blended number | Agent line + human gates, effort vs elapsed |
| Coding, testing and review in one figure | Hides which part is the bottleneck | One row per line item |
| Omitting review wait | Usually the largest elapsed term | Resolve it from repo posture, or state it |
| Summing elapsed across parallel tickets | Parallel agents do not add up | Roll up along the critical path |
| Planning on 13 points | The scale says split | Decompose, then estimate the parts |
| Hours with no stated assumptions | The reader cannot see what would change it | List reviewer, CI and live-access assumptions |

## Subagents

SessionStart context does not reach a dispatched subagent. A skill
that asks a subagent for an estimate must inline this method, or tell
the subagent to Read this file — do not assume it already knows it.
