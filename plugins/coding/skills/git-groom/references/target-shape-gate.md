# Target-Shape Gate (Strategy B: Full Restructure)

Full Restructure is destructive — `git reset --soft <base>` throws
away the current commit boundaries before a single replacement
commit exists. Once history is unstaged there is no automatic way
back to "what the reviewer originally saw" except the backup tag
(see `references/tree-reconstruction.md`).

Because the rebuild has no undo short of that tag, the agent MUST
agree the target shape with the supervisor **before** running the
soft reset, not after. Silently picking a shape and asking forgiveness
later risks a wasted rebuild pass and a confusing backup-tag rollback.

## The Five Axes

Present all five axes together as one gate — they interact (e.g.
axis (b) and (d) both drive commit boundaries) and re-asking them
one at a time would fragment a single design decision into five
separate prompts.

1. **Author code in its final location/structure.** No commit in
   the rebuilt sequence refactors a file that an earlier commit in
   the *same PR* already introduced. If the final module layout is
   known upfront, write it there directly instead of landing it
   provisionally and moving it two commits later.
2. **One commit per architectural layer, bottom-up.** Each layer
   gets its own commit, ordered so every commit builds on the ones
   before it (dependency order, not file-alphabetical order).
3. **Tests ship with their subject.** A commit that adds or changes
   production code carries its own tests/fakers in the same commit.
   Never split "add the code" and "add tests for it" across commits.
4. **Split on the ticket/PR boundary.** Do not fold unrelated tickets
   or drive-by fixes into the same commit sequence as the PR's stated
   scope; a commit sequence stays legible when it maps 1:1 onto the
   PR's Job Story.
5. **Service/orchestration classes own no data access.** If the
   rebuild surfaces a service or orchestrator class making direct
   data-access calls, the target shape should extract a repository
   or DAL layer as its own bottom commit, not fold data access into
   the service commit.

## REQUIRED: Call `AskUserQuestion`

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text, call
spec: [ask-target-shape.md](../tool-calls/ask-target-shape.md)).

This gate fires for Strategy B regardless of friction level — see
Phase 2 destructive-ambiguity carve-out — because a destructive
rebuild with no deterministic answer is the one case the supervisor
must confirm even at `adaptive`.

Do NOT run `git reset --soft <base>` until the gate returns.

## Atomicity Criterion

Name this criterion explicitly when planning or reviewing the
rebuilt commit sequence:

> **No commit modifies code an earlier commit introduced within the
> same PR.**

A commit sequence that violates this criterion is not "atomic" no
matter how small each individual commit is — it just spreads one
logical change across multiple diffs, defeating the point of a
Full Restructure.

## Smell: "The PR Refactors Its Own Code"

Watch for this smell while drafting the commit-spec list in
`references/tree-reconstruction.md`: if commit N adds a function
and commit N+2 renames or restructures that same function (with no
external event — e.g. a review comment — driving the change), the
PR is refactoring its own code. That is the atomicity criterion
being violated in practice, and it means axis (a) above was not
honored: the code was not written in its final shape the first
time.

When the smell appears while partitioning the diff into commit
specs, merge the two touch points into a single commit spec instead
of preserving the provisional-then-refactored shape.
