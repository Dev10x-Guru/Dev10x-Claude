# Queue building & convergence files

Depth behind Phase 0.1 (build the queue) and Phase 0.2 (queue & model
gate) in [`instructions.md`](../instructions.md). The rules those
phases enforce stay inline there; the reasoning is here.

## Disjoint scope is not disjoint files

`Dev10x:fanout` is reached for "only for provably disjoint file sets",
and the trap is in the word *provably*. Two tickets can be unrelated in
every way a reader checks — different milestones, different labels,
different feature areas — and still both edit the file that every
change in the repo edits.

Every codebase has a handful of these **convergence files**:

- settings / config modules
- url or route tables
- the DI container or service registry
- a generated schema (`schema.graphql`, an OpenAPI document, migration
  heads)
- the top-level `__init__` or barrel export of a package under active
  growth

They are the last few lines of otherwise-unrelated diffs, which is
exactly what makes them invisible when you chunk by ticket.

## What it cost (GH-1214 finding 5)

Four api-lane workers ran in parallel on chunks judged disjoint. They
were, feature-wise. All four touched `website/settings/production.py`,
`website/urls.py`, `website/container.py`, and the generated
`schema.graphql`.

The bill did not arrive during the work — it arrived at the tail, one
conflict per merge: **each of the last five merges left the next open
PR `CONFLICTING`.** Three of those rebases were finished by the
watchdog by hand, at the point in the night when it had least slack and
the least context:

- one tree fully resolved and left sitting at "run `git rebase --continue`"
- one one-line schema regeneration left uncommitted
- one body line over 72 characters that failed `git-history-linting`

None of those is hard. All of them are hard *at 04:00, for someone who
did not write the change*, while other workers are waiting.

## The rule, and why it is cheap

Name the repo's convergence files at Phase 0.4 — the supervisor is
present, and it is one question. Record them in the manifest. Then any
two chunks that share one go **sequential and adjacent** in the queue,
with the second rebased onto the first.

The conflict does not disappear; it moves. Resolved by the second
worker, it is resolved once, by an agent holding the context of both
changes, during the working part of the night. Left to the tail, it is
resolved N times by the watchdog, which holds neither.

Chunks sharing nothing on the list may still run in parallel — this is
a serialization rule for a named, short list, not a retreat from
parallelism.

## Interaction with the model gate

A serialized pair is one chunk's worth of wall-clock, not two, so it
changes the queue-length estimate the Phase 0.2 gate presents. Say so
when presenting the plan: a supervisor who thinks four chunks run in
parallel and is shown a four-chunk night will read a serialized queue
as the run falling behind.
