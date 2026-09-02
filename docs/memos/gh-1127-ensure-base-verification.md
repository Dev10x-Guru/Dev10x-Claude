# GH-1127 — `ensure-base` re-seeding: read-only verification

Read-only slice of GH-1127. The write half is **not** performed here: a
maintainer comment on the issue reserves it for a human, and the crew
contract excludes `~/.claude/settings.json` from agent writes by any
route. Everything below comes from `--dry-run` output and source
reading.

Verified 2026-09-02 against `dev10x v0.95.0` (`uv tool list`), which
matches the loaded plugin cache — so this is not the stale-CLI trap.

## Answer to the acceptance criterion that mattered

The issue's step 6 asks: *does `upgrade-cleanup` actually invoke
`ensure-base` on a normal upgrade?*

**Yes.** `Dev10x:upgrade-cleanup` delegates to
`Skill(Dev10x:plugin-maintenance, args="full")`, whose full-mode task
list has "Ensure base permissions" as task 5, backed by § 4. The chain
is intact and needs no repair.

The doubt was well-founded, though — the Modes table said otherwise.
See the fix below.

## Finding 1 — the catalog is not yet a durable home (the real defect)

The issue's premise is that moving the 12 entries into the user catalog
makes them survive a settings reset, replacing the hand-edited
`~/.claude/settings.json` as the guarantee. **That does not hold**, for
a structural reason.

`ensure_base` (`src/dev10x/skills/permission/update_paths.py:1252-1254`):

```python
global_rules, stale_wildcards = _load_global_allow_rules()
filtered = [p for p in base_permissions if p not in global_rules]
```

`_load_global_allow_rules` (`:1011`) reads `~/.claude/settings.json`,
and every base permission already present there is dropped before
seeding. The files actually written are the **project** settings files
discovered by `find_settings_files(roots=...)`
(`src/dev10x/commands/permission.py:395`). The global file is a *dedupe source*,
never a write target.

Consequences, in order:

1. While the global file still holds a rule, that rule is filtered out
   — it shows as nothing-to-do, which reads like "already handled" but
   means "not seeded anywhere".
2. If the global file is reset — precisely the scenario the catalog
   entries were added to survive — `ensure-base` will seed those rules
   into **project** settings files, not back into
   `~/.claude/settings.json`. The global grant is not restored.
3. So the catalog protects the rules' *existence*, not their *scope*.
   For a rule whose value depends on being global, that is a different
   guarantee than the issue assumed.

This is the same root cause already recorded as GH-1100 E7/E8
(`ensure-base`/`seed_worktree` skipping every rule the global file
has), observed here from the opposite direction.

Note the deliberate asymmetry: `ensure_base_denies` (`:303`) skips the
global filter on purpose, and says so in its docstring — a deny must be
enforced per project even when a global setting already denies it. Only
allows are filtered.

## Finding 2 — the `gog` rules will not land as the issue expects

The issue lists "all four `gog` rules" among the 12 entries expected to
land. The dry run emits **zero** `gog` lines.

Two independent reasons:

- In the plugin catalog
  (`src/dev10x/skills/permission/baseline-permissions.yaml:507,529`) they are
  opt-in tier-3 groups, `gog-readonly` and `gog-credentialed`, the
  latter documented as "NOT shipped by default" and tagged
  `sensitivity: secret` because `gog auth tokens export` materializes a
  live OAuth token on disk.
- In the user catalog they are present, but filtered by Finding 1
  because the hand-edited global file already has them.

The `~/.claude/skills/my:*/scripts/*.py` paths, by contrast, **do**
appear as pending additions — those are genuinely missing from the
global file.

## Finding 3 — the Modes table contradicted the task lists

`skills/plugin-maintenance/SKILL.md` § Modes listed:

| Mode | Steps as written | Actual task list |
|------|------------------|------------------|
| `bootstrap` | version-check, 2, 3, 5 | version-check, §§ 2, 3, **4**, 7, 8 |
| `full` | version-check, 1–8 | version-check, §§ **1–13** |

The `bootstrap` row omitted § 4 — *which is the `ensure-base` step, is
itself tagged `[bootstrap]`, and which the prose one line below says
bootstrap does*. The `full` row stopped at 8, omitting §§ 9–13, all of
which carry an explicit *(full only)* marker.

An agent executing from the table rather than the task list would skip
`ensure-base` entirely in bootstrap, and skip the worktree merge,
friction audit, project-file clean, doctor sweep and playbook diff in
full. This is the likeliest source of the issue's doubt about the
chain. Corrected in this commit — documentation only, no behaviour
change.

## Not verified here (needs the write, i.e. a human)

Untouched, and still open on the issue:

1. That the write lands in the file that wins at resolution time.
2. Deny/ask counts before and after — a drop is a stop-and-revert
   signal, not a detail.
3. Idempotency — a second run adds nothing.
4. That the entries return after a simulated reset. **Finding 1 says
   they will return to project files, not to global** — worth deciding
   whether that satisfies the intent before running the write.

Current dry-run backlog: **208 permissions across 64 files** (the issue
recorded 574 across 62; it has since shrunk). That is the normal
accumulated backlog, not something these entries caused.

Until the write is verified, the working guarantee for the 12 entries
remains the hand-edited `~/.claude/settings.json` — the fragility the
catalog entries were meant to remove.
