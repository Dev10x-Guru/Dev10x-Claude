# GH-1560: Stage A rename rehearsal

Date: 2026-10-11

ADR-0034 makes a rehearsed rename the Stage A exit criterion. This memo
records what was rehearsed, what it proved, and what is left for the
release.

## What ran

`tests/core/test_rename_rehearsal.py` copies the repository's inventory
scope into a temporary directory and never writes to the checkout. The
copy covers `skills/`, `docs/`, `references/`, `agents/`, `commands/`
and `command-skill-map.yaml`. The test then runs both halves of the
rename machinery end to end on the `gog` skill:

1. `dev10x skill rename` (NS-35, GH-1558) moves every core-prefixed
   `gog` reference to the `dev10x-comm` prefix. That is the exact
   rewrite B4 will make when the communication plugin leaves.
2. The user-config migration (NS-36, GH-1559) rewrites the old name in
   a fixture `friction.yaml` through an alias row. A second run writes
   nothing, and the old name resolves to the new one through the alias.
3. The rename runs in reverse.

`gog` was chosen because it is low-traffic. It has 8 pinned references,
all inside its own area, so a miss would show up as a count change and
not hide among hundreds of mentions.

## What it proved

| Check | Result |
|---|---|
| The forward rename moves the whole pinned count | 8 of 8 |
| The inventory loses only `gog` after the forward step | yes |
| The migrated user config carries the new name, and a re-run is a no-op | yes |
| The copy is byte-identical after the reverse step | yes |
| The inventory equals `tests/fixtures/skill_reference_inventory.json` | yes |

The reverse step is exact because the tool refuses a target name that
is already in use. A capital `Dev10x` keeps its case in both directions.

The guard fired during this very rehearsal. An early draft of this memo
spelled out the target name in full, and the rehearsal refused to run
until the draft was reworded. So a doc that names a skill's future
prefix before the move blocks that move. Write the prefix and the skill
apart, as this memo does.

## Limits

- **`.claude/` is outside the rename scope.** Rule files there name
  skills, but they are supervisor-owned, so each Stage B move needs a
  supervisor pass over `.claude/rules/`.
- **Python sources are outside the scope too.** The scope matches the
  NS-05b inventory, so a rename stays verifiable by counts. Docstrings
  under `src/` that name a moved skill need a hand edit in the move PR.
- **The rename is text-only.** Moving the skill directory stays a
  `git mv`, which is step 2 of each Stage B extraction.

## Left for the release

Nothing user-visible changed. No skill was renamed, the alias table
ships empty, and every MCP tool name is unchanged. The last part of the
NS-37 Verify is that "`dev10x` is released and behaves identically".
The supervisor confirms that when cutting the release that carries
this change.
