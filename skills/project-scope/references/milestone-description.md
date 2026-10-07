# Milestone Descriptions

Every milestone `dev10x:project-scope` creates carries a description
that states where it sits in the project. Milestones that wait on a
spike or investigation have no tickets yet, so for them the
description is the whole hand-off to a later refinement session.

## Why ordering lives here, not in the name

An ordinal prefix (`M0`, `Phase 2`, `1.`) encodes a sequence into
every milestone title. Splitting one milestone in two, or merging two,
then forces a rename of everything after it — and a renamed milestone
breaks every filter and link that used the old title. A dependency
line survives a split or merge: only the milestones that actually
depend on the changed one need editing.

So the title names the outcome, and the description names what it
waits on.

## Every milestone

```markdown
<one or two sentences: what is true once this milestone is done>

Depends on: <milestone name>, <milestone name>
```

- Omit the `Depends on:` line only when the milestone can start now.
- Name milestones by their exact titles so a reader can search for
  them.
- Ticket-level ordering still goes on the tickets themselves, as
  `blocks` / `blockedBy` (or a cross-reference comment on GitHub).

## A milestone with no tickets yet

When a milestone sits behind a spike, a go/no-go decision, or an
investigation whose result can change its shape, create it with this
description and no tickets:

```markdown
<summary: the outcome and why it matters>

Depends on: <the spike or decision milestone>

## Status

Provisional — no tickets yet. <Spike/decision name> decides whether
this milestone is kept, reshaped, or dropped.

## Code references

- `path/to/module.py` — <what lives here and why it is affected>
- `path/to/other/` — <...>

## Open questions

- <what the spike must answer before this can be ticketed>
- <...>

## How to scope this milestone

1. Read the outcome of <spike/decision> and confirm it kept this
   milestone. If it reshaped or dropped it, edit or close the
   milestone first.
2. <the concrete starting point: which code path to trace, which
   decision record to read>
3. Break the work into tickets with `dev10x:ticket-scope`, set
   their blocking chain, and replace the Status section with the
   ticket list.

Indicative size: <range> (provisional — not part of the project
estimate).
```

The "How to scope" steps should be specific enough that someone who
did not attend the scoping session can start from them. Generic text
("investigate and create tickets") gives the refinement session
nothing to work with.
