# dev10x:reflect — Configuration

`<Dev10x config>/knowledge-vault.yaml` (`~/.config/Dev10x/` on Linux and
macOS; see `references/config-resolution.md` at the plugin root). The
plugin ships no default vault: until this file names one, every reflect
step prints one line and skips.

## Keys

| Key | Default | Meaning |
|---|---|---|
| `vault` | — | Vault root. `~` and `$VARS` expand; must be an existing absolute directory |
| `enabled` | `true` | `false` turns reflection off (useful inside a `projects` entry) |
| `folders` | see below | Lesson kind → vault-relative folder |
| `log_folders` | each kind's `folders` value | Lesson kind → folder whose log records it, e.g. `retro: Project` when `Project/log.md` links `Project/Retros/<note>` |
| `index_note` | `index.md` | Per-folder index note name; a bare Markdown file name (no `/`, ends in `.md`) |
| `log_note` | `log.md` | Per-folder log note name; a bare Markdown file name (no `/`, ends in `.md`) |
| `rules_note` | — | Vault-relative note with the vault's own conventions, read first |
| `projects` | — | `match_repo:` entries whose keys override the top level |

Default `folders`: `retro: Retros`, `platform: Platform`,
`process: Process`, `patterns: Patterns`. Folder values must stay inside
the vault: no absolute paths, no `..`, no symlink pointing out.

## Project overrides

The first `projects[]` entry whose `match_repo` glob fits the
checkout's `org/repo` (from `git remote get-url origin`) overrides the
top-level keys. `folders` and `log_folders` merge key by key, so an
entry can move only the retro folder.
An entry that moves `folders.<kind>` without naming its own
`log_folders.<kind>` drops the inherited one, so that kind logs next
to its new folder rather than in the shared log. A checkout with no `origin` remote uses the top level.

```yaml
vault: ~/Notes/Knowledge
rules_note: Meta/conventions.md
folders:
  retro: Engineering/Retros
  patterns: Patterns
projects:
  - match_repo: "example-org/*"
    folders:
      retro: Clients/Example/Retros
      platform: Clients/Example/Platform
  - match_repo: "example-org/sandbox"
    enabled: false
```

`dev10x config doctor` reports a `projects` list that matches nothing
for the current checkout.

## Commands

| Command | Writes | Output |
|---|---|---|
| `dev10x skill reflect config` | nothing | resolved config, or `configured: false` + `reason` |
| `dev10x skill reflect index-add --folder F --line L [--seed-listing]` | `F/<index_note>` | `{path, action}` — `created`, `appended` or `unchanged` |
| `dev10x skill reflect log-add --folder F --entry E [--date D] [--create]` | `F/<log_note>` | `{path, action}` — adds `skipped` when the folder keeps no log |

Both writers take an exclusive lock per note (sidecar under
`<Dev10x config>/locks/reflect/`, never in the vault), re-read the note
under the lock and replace it atomically, so concurrent sessions never
lose a line. A line already present is `unchanged`, so a retried
reflection does not duplicate entries. A new line takes the list marker
(`-`, `*` or `+`) the note already uses, and an entry differing only in
its marker counts as present. An index or log note that is a symlink is
refused rather than followed, so it cannot pull content from outside the
vault into it.

All three commands share one exit contract: no vault configured is an
answer, not an error — `config` reports `configured: false`, and the
two writers print `{"path": null, "action": "skipped", "reason": …}` —
all exit 0. Real errors (a broken config file, a refused path, a lock
timeout) print one JSON object with an `error` key and exit 1.

Locks only coordinate processes on one machine. A vault synced between
machines can still conflict at the sync layer; that is the sync tool's
job, not this one's.
