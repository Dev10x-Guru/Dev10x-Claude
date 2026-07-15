# Tree Reconstruction Recipe (Strategy B: Full Restructure)

Hook-safe, non-interactive procedure for rebuilding N atomic commits
after the target-shape gate (`references/target-shape-gate.md`) has
been confirmed. Use this recipe instead of ad hoc `git commit -m`
calls, `git commit --amend`, or `git rebase -i` — those three commands
are hook-blocked in this environment (they trigger an interactive
editor or run outside the plumbing layer the hooks were designed to
audit). The plumbing sequence below builds each commit object
directly, so it never opens an editor and never re-triggers a
commit-msg/pre-commit hook mid-sequence.

## REQUIRED: Backup Tag Before the Soft Reset

Before running `git reset --soft <base>` (Strategy B's first step),
tag the current tip so the pre-rebuild tree is recoverable by name,
not only by reflog entry:

```bash
git tag -f groom-backup-<branch-slug> HEAD
```

`<branch-slug>` is the current branch name with `/` replaced by `-`
(tag names cannot contain `/`-adjacent slashes safely across all git
plumbing). Do this unconditionally for every Strategy B run — it is
the rollback target for the tree-equality check below, and it costs
nothing (a tag is a cheap ref, not a copy).

## Partition-Completeness Check (REQUIRED, before building any commit)

Before creating the first commit-tree object, verify the commit-spec
list (drafted from the target-shape gate's confirmed axes) is a
complete partition of the changed files:

```bash
git diff --name-only <base>..HEAD
```

Take the union of every commit spec's path list and diff it against
this full changed-file set:

- **Missing path** (in the full set, absent from every spec) →
  abort. A file the rebuild forgot to assign silently disappears
  from the new history.
- **Duplicate path** (assigned to more than one spec) → abort. A
  duplicate means either a genuine same-file split (rare — needs an
  explicit hunk-level spec, not two whole-file specs) or a planning
  error.

Do not proceed to the reconstruction loop until the union equals the
full set exactly.

## Reconstruction Loop

Inputs: `base` (the pre-groom base commit, e.g. `origin/develop` fork
point), and an ordered list of commit specs, each with a `paths` list
and a `msgfile` (written via the Write tool, one message per commit,
JTBD-style title per `references/git-commits.md`).

Strategy B has already run `git reset --soft <base>` at this point,
so every changed file's content is present in the working tree and
fully staged against `<base>`.

```bash
parent=<base-sha>

# For each commit spec, oldest-first:
git reset HEAD                       # unstage everything
git add -f <paths for this spec>     # -f: bypass global .gitignore (see instructions.md
                                      #     "Files Excluded by Global ~/.gitignore" pitfall)
tree=$(git write-tree)
new_commit=$(git commit-tree "$tree" -p "$parent" -F <msgfile-for-this-spec>)
parent=$new_commit
# repeat for the next spec, using the updated $parent
```

After the last spec, `parent` holds the final commit SHA of the
rebuilt sequence.

```bash
git reset --hard "$parent"
```

`git reset --hard` here is safe: the working tree already matches
`$parent`'s tree (it was built from the same staged content), so this
step only moves the branch ref and HEAD, not any file content.

### Why plumbing, not porcelain

- `git commit-tree` takes a tree object and parent(s) directly — it
  never opens `$EDITOR` and never re-runs `commit-msg`/`pre-commit`
  hooks per commit, so N commits build in one unattended pass.
- `git write-tree` snapshots the current index without touching HEAD,
  which is what lets the loop build commit N+1 on top of commit N's
  SHA without ever checking that intermediate commit out.
- Raw `git commit`, `git commit --amend`, and `git rebase -i` are
  blocked by the permission hooks in this environment (they require
  an interactive editor or a sequence-editor override) — the plumbing
  sequence above is the sanctioned non-interactive path for building
  a specific N-commit shape.

## REQUIRED: Tree-Equality Post-Condition (before the force-push)

After the reconstruction loop finishes and before Phase 3's
`git push --force-with-lease`, verify the rebuild changed nothing
about the final tree — only the commit boundaries:

```bash
git diff groom-backup-<branch-slug> HEAD
```

- **Empty diff** → the rebuild is a pure history restructure, safe to
  force-push.
- **Non-empty diff** → the rebuild dropped, duplicated, or altered
  content relative to the pre-groom tree. Roll back immediately:

  ```bash
  git reset --hard groom-backup-<branch-slug>
  ```

  Do NOT force-push a tree that fails this check. Diagnose the
  partition (a missed path, a stale `msgfile`, a bad `-p` parent
  chain) and re-run the reconstruction loop from the backup tag.

This check is the hard gate between "commits were reorganized" and
"content silently changed" — the two are indistinguishable from a
`git log --stat` skim, but `git diff <tag> HEAD` catches both a
missing hunk and an accidental double-apply in one command.
