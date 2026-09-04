# Post-Upgrade Verification (GH-1137)

Run this after a local plugin upgrade's maintenance pass, before
trusting the new version.

**Read the maintenance log for what it did, not for what it
achieved.** GH-1136 is the reason this checklist exists:
`ensure-base` reported "All base permissions already covered by
global settings" while 137 of 285 catalog rules were absent from
every project file. The run was truthful and the outcome was
wrong, because the check was a reading of the log rather than of
the files. Silence was the defect. So verify against the files.

## 1. Catalog reach

Run `dev10x permission catalog-gap` for the main checkout AND
every worktree root. Each must report:

```
0 missing allow / 0 missing deny / 0 missing ask
```

Include a **freshly created** worktree as its own case: seeding a
new worktree is a separate code path (`seed_worktree`) from
seeding an existing checkout, and the two have regressed
independently.

The `ask` count is new as of GH-1154. A catalog predating the ask
tier reports `0 missing ask` trivially; a non-zero count means the
tier shipped but did not propagate.

## 2. Nothing git-tracked was written

`git status` must be clean in every repo whose
`.claude/settings.json` is git-tracked.

A dirty tracked settings file means a writer bypassed the shared
guard (`partition_writable`, shared across every writer as of
GH-1155). **Report it rather than reverting.** GH-1155's evidence:
one maintenance run took a tracked file from 2 committed rules to
1495 allow / 51 ask / 82 deny, and 597 of those rules existed ONLY
in the tracked file — reverting it to its committed state would
have silently destroyed them and reintroduced prompts everywhere.

## 3. Safety keys intact

`disableAutoMode` and `disableBypassPermissionsMode` must still be
the **string** `"disable"` in every settings layer.

`true` is silently ignored, so a boolean here reads as protection
that is not actually in force.

## 4. Spot-check the shapes users actually type

Confirm that a sanctioned command does not prompt.

`pre-commit run` is the worked example. It was catalogued only in
its discouraged `uv run pre-commit run` form until GH-1149, while
the *sanctioned* direct form was absent. The user's global
settings happened to carry the direct form, which masked the gap
entirely — until GH-47 (a project `settings.local.json` wins
outright) made the global entry irrelevant to every project.

The lesson generalizes: a rule present *somewhere* is not a rule
that applies *here*. Check the form the docs tell people to use,
in a project that has its own settings file.

## Filing what you find

A gap found here belongs in its own focused issue that references
the permission-friction tracker (GH-1100) — not appended to this
checklist, and not implemented directly from the tracker. That is
exactly how GH-1149 was split out of GH-1137's own first run: the
verification passed every check except the `pre-commit` spot-check,
and the one failure became a separate, closable issue.
