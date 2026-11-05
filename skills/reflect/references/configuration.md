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
top-level keys. `folders` merges key by key, so an entry can move only
the retro folder. A checkout with no `origin` remote uses the top level.

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
reflection does not duplicate entries. Errors print as one JSON object
with an `error` key and exit 1.

Locks only coordinate processes on one machine. A vault synced between
machines can still conflict at the sync layer; that is the sync tool's
job, not this one's.
