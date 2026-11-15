# Repairing a corrupted worktree

What to do when the checkout itself is damaged — tracked files truncated
to zero bytes, git objects empty — rather than merely unreachable.

Companion to [`worktree-recovery.md`](worktree-recovery.md), which covers
*reaching another worktree's content*. That is a different failure: there
the tree is intact and the agent cannot get to it. Here the agent is
standing in the tree and the tree is broken.

## How it happens

A process killed mid-write leaves partial state behind. The observed
case (GH-1039): an org spend limit terminated a run between git's
object writes and its index update, leaving 47 zero-byte objects under
`.git/objects/` and 15 tracked files truncated to 0 bytes in the
working tree. Any hard kill during a checkout, rebase, gc, or clone can
produce the same shape.

The signature is **zero length, not missing**. Files still exist and git
still reports them as modified, so the usual "did something delete my
work?" instincts point the wrong way.

## Wait before acting

**This is the step that matters most, and the one an agent skips.**

A concurrent `git gc` or an in-flight rebase may still be running. Those
processes finish and repopulate objects on their own — the tree
self-heals with no intervention. Acting during that window turns a
transient inconsistency into a real loss, because the "repair" discards
content git was about to restore.

So: observe, wait, re-check. Only treat the corruption as settled when a
second look some minutes later shows the same zero-byte set.

## Diagnose read-only

Every step here is non-destructive. Run them; do not fix anything yet.

1. **Find truncated tracked files** — list files of size 0 that git
   knows about, and compare against `git status`.
2. **Find empty objects** — zero-byte files under `.git/objects/`.
   A non-zero count with a healthy working tree means the damage is in
   the object store, not the checkout.
3. **Ask git for its own verdict** — `git fsck` names broken links and
   missing objects.
4. **Check whether the work is already safe elsewhere** — if the branch
   was pushed, the remote has it and the local tree is disposable. This
   is the fastest exit and should be checked before anything else.

## Choosing a repair

Ranked by cost, cheapest first. Stop at the first one that applies.

| Situation | Action |
|---|---|
| Branch was pushed | Abandon the tree. Create a fresh worktree from the remote branch — nothing is lost. |
| Objects intact, only working-tree files truncated | The content is recoverable from git; this needs a restore, which is **gated** (below). |
| Objects damaged, work also exists on the remote | Same as row 1 — re-clone rather than repair. |
| Objects damaged, work exists nowhere else | Salvage what is readable, report the rest as lost. Do not overwrite anything while salvaging. |

## The restore is supervisor-run by design

Recovering truncated files means `git restore <paths>` (equivalently
`git checkout HEAD -- <paths>`), and both spellings sit inside the
deny rail that protects uncommitted work — see
[`../../diag-friction/references/deny-rail-vs-approval-gate.md`](../../diag-friction/references/deny-rail-vs-approval-gate.md)
§ `git restore` is inside the rail. The rail is not defeated by the fact
that this instance is repair rather than discard; that is a judgment
about intent, and the rail deliberately does not read intent.

**Attended:** hand the supervisor the exact command with its working
directory, ready to paste. It takes seconds.

**Unattended, no human to hand it to:** do NOT re-spell the command and
do NOT propose an allow rule. Route around the *need* instead:

1. Prefer abandoning the tree — a fresh worktree from the remote branch
   is almost always available and costs less than a repair.
2. Record the blocked command, its working directory, and its intent in
   the run's decision log as a supervisor item for the morning.
3. Leave the damaged tree in place, untouched, on a branch nobody else
   is using. A dirty tree that nobody touches loses nothing; a
   half-repaired tree can.

## Prevention

The crew contract already asks for a push as soon as there is anything
worth keeping. Corruption is another argument for it: a pushed branch
turns every failure in this document into row 1 of the table above.
