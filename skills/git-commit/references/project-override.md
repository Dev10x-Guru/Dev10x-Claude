# Project-Level Commit Configuration

Override the git-commit skill's gitmoji mapping and title format
via a shared YAML config file with named strategies. Multiple
repos can share the same strategy.

## Config File Location

```
<Dev10x config>/gitmoji.yaml
```

Global file — not per-project. Strategies are defined once and
mapped to repos by pattern.

## Schema

```yaml
# Named strategies — define once, reuse across repos
strategies:
  semantic-release-gitmoji:
    title-format: "<gitmoji> <ticket> <description>"
    gitmoji-mapping:
      - emoji: "✨"
        label: Feature
        description: "New features"
        release: minor
      - emoji: "🐛"
        label: Fix
        description: "Bug fixes"
        release: patch
      # ... more entries

  conventional-gitmoji:
    title-format: "<gitmoji> <conventional-type>: <description>"
    gitmoji-mapping:
      - emoji: "✨"
        label: feat
        description: "New features"
        release: minor
      # ... more entries

# Map repos to strategies by remote URL pattern or repo name
projects:
  # Glob patterns matched against git remote origin URL
  - match: "*/Dev10x*"
    strategy: semantic-release-gitmoji
  - match: "*/app-pos*"
    strategy: semantic-release-gitmoji
  - match: "*/example-backend*"
    strategy: semantic-release-gitmoji

# Fallback when no project matches (optional)
default-strategy: null  # null = use hardcoded defaults
```

## Field Reference

### strategies

Named mapping definitions. Each strategy has:

| Field | Required | Description |
|-------|----------|-------------|
| `title-format` | No | Override commit title assembly |
| `gitmoji-mapping` | Yes | List of type entries |

### gitmoji-mapping entries

| Field | Required | Description |
|-------|----------|-------------|
| `emoji` | Yes | Emoji character (not `:code:`) |
| `label` | Yes | Short label shown in type menu |
| `description` | Yes | Explanation shown in type menu |
| `release` | No | Release impact: `patch`, `minor`, `major`, `none` |

When `release` is present, the type menu shows it as a badge:
```
Feature [minor] — New features
Fix [patch] — Bug fixes
Refactor [none] — Code restructuring
```

### title-format

Override the commit title assembly. Default:
`<gitmoji> <ticket> <description>`

Supported placeholders:
- `<gitmoji>` — emoji from selected type
- `<ticket>` — extracted ticket ID
- `<description>` — user-provided description
- `<conventional-type>` — label field, lowercased

### projects

List of match rules. Each entry:

| Field | Required | Description |
|-------|----------|-------------|
| `match` | Yes | Glob pattern against remote origin URL |
| `strategy` | Yes | Name of a strategy defined above |

Patterns are tested in order; first match wins. The match
is checked against the output of `git remote get-url origin`.

## Resolution Order

1. Read `<Dev10x config>/gitmoji.yaml`
2. Get current repo's origin URL via `git remote get-url origin`
3. Walk `projects` list — first `match` that fits selects the
   strategy
4. If no match and `default-strategy` is set, use that
5. If still no match, check for a semantic-release config in the
   project root and auto-derive release tags (see
   `semantic-release.md`)
6. If no config found, load `references/gitmoji-defaults.yaml`

If the YAML file is invalid or unreadable, the skill logs a
warning and falls back to the defaults file — the commit is
never blocked by a config error.

## Behavior

1. **Full replacement:** When a strategy's `gitmoji-mapping` is
   present, it replaces the entire default mapping. Define all
   types you want available.
2. **AskUserQuestion adaptation:** The type selection gate
   presents the first 4 entries as options (AskUserQuestion
   limit). Remaining entries are noted as "Other" choices.
3. **Unattended mode:** Auto-selection uses `label` matching
   against the detected change type. Release impact is logged
   but does not affect selection.

## Example

See `gitmoji-defaults.yaml` for a complete mapping. A minimal
user override adding `release` tags and project routing:

```yaml
strategies:
  with-release-tags:
    gitmoji-mapping:
      - emoji: "✨"
        label: Feature
        description: "New features"
        release: minor
      - emoji: "🐛"
        label: Fix
        description: "Bug fixes"
        release: patch
      - emoji: "♻️"
        label: Refactor
        description: "Code restructuring"
        release: none

projects:
  - match: "*/my-repo*"
    strategy: with-release-tags
```
