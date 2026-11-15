# Rename-First Split (Strategy E)

Split a commit that both **moves** files and **edits** them into two
commits: a pure rename with zero content change, then the structural
edit. GH-1629.

## Why

A file move committed together with its edits reaches the reviewer as
a delete plus an add. GitHub and `git diff` only pair the two when the
content is still similar enough, and even then the reviewer reads the
whole file to find what changed. Split in two:

1. The **rename commit** shows as `R100` — "file moved, nothing else" —
   and is reviewed in seconds.
2. The **edit commit** then diffs the new path against itself, so the
   reviewer sees only the lines that actually changed.

The GH-970 refactor (PR #975) is the worked example: splitting
`references/task-orchestration.md` into `references/orchestration/*.md`
landed as a move commit followed by an edit commit, and review of the
second commit covered only the real changes.

## Detection (Phase 1)

Run once against the branch range, with rename detection lowered to
30% similarity so a heavily edited move is still paired:

```bash
git log -M30% --name-status --format='--- %h %s' origin/<base>..HEAD
```

Every `R<nnn>` line with `nnn < 100` is a **rename-first candidate**:
git paired a delete and an add (or a rename) whose content also
changed. `R100` lines are already pure renames and need nothing.
A `D old` + `A new` pair that git did not pair even at 30% is a
rewrite, not a move — leave it alone.

Report the candidates in the Phase 1 summary:

```
Rename-first candidates:
  abc1234 ♻️ GH-970 Split orchestration patterns
    R062 references/task-orchestration.md → references/orchestration/subagent-dispatch.md
```

**Uncommitted work.** Untracked files never pair with deletions, so
the working tree cannot be checked reliably before staging. When the
staged set shows a candidate (`git diff --cached -M30% --name-status`),
say so and recommend committing the move and the edit separately
instead of grooming it apart afterwards.

## Execution (Phase 3)

The split runs through `git-rebase-groom.sh` with a sequence file, the
same unattended path Strategy D uses. Each candidate commit `C` is
replaced by two `exec` lines; every other commit stays a `pick`.

1. Tag the tip: `git tag -f groom-backup-<branch-slug> HEAD`.
2. Re-read fresh SHAs (`git log --oneline origin/<base>..HEAD`) — never
   reuse analysis-time SHAs.
3. Write one message file per rename commit with the Write tool, in a
   workdir from `mktmp(namespace="git", prefix="groom", directory=True)`.
4. Write the sequence file, oldest commit first, replacing `pick <C>`:

   ```
   pick 1111111 Earlier commit
   exec mkdir -p references/orchestration && git mv references/task-orchestration.md references/orchestration/subagent-dispatch.md && git commit -q -F $WORKDIR/msgs/rename-abc1234
   exec git read-tree -u --reset abc1234 && git commit -q -C abc1234
   pick 2222222 Later commit
   ```

   - The first `exec` performs every move of `C` on its parent's tree
     and commits it. Keep all moves of one commit on **one** line (see
     "exec Steps Leaving Staged Changes Halt Rebase" in
     `instructions.md`).
   - The second `exec` sets the index and working tree to exactly
     `C`'s tree — files `C` deleted are removed too — and commits it
     with `C`'s original message and authorship.

5. Run `${CLAUDE_PLUGIN_ROOT}/skills/git/scripts/git-rebase-groom.sh <seq-path> <base>`.
6. Verify each rename commit is pure:
   `git show --name-status -M --format= <rename-sha>` must list only
   `R100` entries (`--stat` prints paths and counts, not status letters).
7. Run the tree-equality post-condition from
   [`tree-reconstruction.md`](tree-reconstruction.md):
   `git diff groom-backup-<branch-slug> HEAD` must be empty.

## Commit message for the rename commit

Use 🚚 and title it by the structure the move establishes, not by the
move itself — "Move X to Y" names the mechanism and trips the JTBD
self-check that `dev10x:git-commit` applies and the strict-tier
commit-jtbd validator (DX008) enforces:

```
🚚 GH-970 Group orchestration patterns under one directory

Pure rename, no content change: review this commit as R100 entries.
The edits that follow the move are in the next commit.

Fixes: GH-970
```

The edit commit keeps the original message unchanged.

## When not to split

- The candidate's similarity is below ~50% **and** the file is short —
  reviewers read it whole either way.
- The branch already has open review threads on the commit: the split
  rewrites its SHA and orphans the thread permalinks. Phase 0 already
  refuses a groom in that state.
