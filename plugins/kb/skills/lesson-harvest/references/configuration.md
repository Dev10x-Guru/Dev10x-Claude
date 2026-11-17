# dev10x-kb:lesson-harvest — Configuration

## Prerequisites

| Tool | Needed for | Install |
|---|---|---|
| Obsidian with its CLI enabled | daily-note path, vault root (always) | install Obsidian, enable the command line interface in Settings → General |
| `yt-dlp` | YouTube captions and reach | `uv tool install yt-dlp` |
| `defuddle` | readable text of web pages | `npm install -g defuddle` |
| `whisper-ctranslate2` | transcribing Spotify episodes locally | `uv tool install whisper-ctranslate2` |

`uvx dev10x skill kb config` reports each tool's path, or null with the
install command. A missing tool is reported, never worked around.

Spotify streams are DRM-protected and have no transcript API, so an
episode's audio comes from the show's public RSS feed (found through
the iTunes Search API, then confirmed by matching the episode title in
the feed). Spotify-exclusive shows have no public feed and cannot be
harvested.

## Vault

The vault is the one `dev10x-tasks:reflect` uses:
`<Dev10x config>/knowledge-vault.yaml` (`~/.config/Dev10x/` on Linux
and macOS), keys `vault`, `rules_note`, `projects` — see that skill's
`references/configuration.md`. The harvest adds a top-level `kb:`
mapping; every key is optional and an unset one turns its step off.

| Key | Meaning |
|---|---|
| `kb.hub` | Vault-relative note (`.md`) with one row per harvested source |
| `kb.topics` | Vault-relative folder with the topic hub, `index.md` and one page per topic |
| `kb.people` | Vault-relative folder with one note per speaker or author |
| `kb.strategy_hub` | Vault-relative note that links topic pages flagged `strategy` |
| `kb.transcribe_model` | Whisper model for podcast audio (default `small`) |

```yaml
vault: ~/Notes/Knowledge
rules_note: Meta/conventions.md
kb:
  hub: Sources/Harvested.md
  topics: Sources/Topics
  people: People
  strategy_hub: Projects/Strategy.md
  transcribe_model: small
```

Paths must stay inside the vault: no absolute paths, no `..`. The
`kb:` mapping is read from the top level only; `projects` entries
switch the vault, not the harvest places.

## Commands

| Command | Writes | Output |
|---|---|---|
| `dev10x skill kb config` | nothing | resolved places + `tools` |
| `dev10x skill kb fetch URL...` | `<tmp>/Dev10x/kb/<id>.txt`, `<id>.meta.txt` | `{records, errors}`; exit 1 when nothing was fetched |
| `dev10x skill kb persist --id --dest --name` | two files in `--dest` | `{text, meta}` |
| `dev10x skill kb index --id --name --structure --note` | the hub note | `{path, action}` — `created`, `appended`, `refreshed` or `skipped` |
| `dev10x skill kb link SOURCE TARGET [TEXT]` | nothing | `{link}` |

Hub writes take an exclusive lock (sidecar under
`<Dev10x config>/locks/kb/`, never in the vault), re-read the note and
replace it atomically. Errors print one JSON object with an `error`
key and exit 1.
