# Semantic-Release Auto-Detection

Auto-derive gitmoji-to-release mappings from a project's
semantic-release configuration. Eliminates manual strategy
setup for projects already using semantic-release with
gitmoji-based release rules.

## When This Applies

This step runs when no manual strategy matched the project
in `~/.config/Dev10x/gitmoji.yaml`. It checks for a
semantic-release config in the project root before falling
back to the plugin defaults.

## Supported Config Locations

Search in order (first found wins):

1. `release.config.mjs`
2. `release.config.cjs`
3. `release.config.js`
4. `.releaserc` (JSON or YAML)
5. `.releaserc.json`
6. `.releaserc.yaml` / `.releaserc.yml`
7. `package.json` → `"release"` key

Use the Glob tool to find the first match. If none found,
skip this step entirely.

## Extracting Release Rules

Semantic-release configs define `releaseRules` inside the
`@semantic-release/commit-analyzer` plugin. The structure
varies by format:

### JavaScript/ESM configs (`release.config.mjs`, `.cjs`, `.js`)

```javascript
export default {
  plugins: [
    ["@semantic-release/commit-analyzer", {
      releaseRules: [
        { emoji: "✨", release: "minor" },
        { emoji: "🐛", release: "patch" },
        { emoji: "♻️", release: "patch" },
        { emoji: "⚡", release: "patch" },
        { emoji: "🔒", release: "patch" },
        { emoji: "📝", release: false },
        { emoji: "✅", release: false },
      ]
    }]
  ]
}
```

**Parsing JS configs:** Read the file and extract the
`releaseRules` array. Look for objects with `emoji` and
`release` fields. JS configs may use `export default` (ESM)
or `module.exports` (CJS). Both follow the same structure.

Handle these `release` values:
- `"major"`, `"minor"`, `"patch"` → map directly
- `false` → map to `"none"` (no release triggered)
- `"prerelease"` → map to `"none"` (skip for gitmoji menu)

### JSON configs (`.releaserc.json`, `.releaserc`)

```json
{
  "plugins": [
    ["@semantic-release/commit-analyzer", {
      "releaseRules": [
        { "emoji": "✨", "release": "minor" },
        { "emoji": "🐛", "release": "patch" }
      ]
    }]
  ]
}
```

### YAML configs (`.releaserc.yaml`, `.releaserc.yml`)

```yaml
plugins:
  - - "@semantic-release/commit-analyzer"
    - releaseRules:
        - emoji: "✨"
          release: minor
        - emoji: "🐛"
          release: patch
```

### `package.json` format

```json
{
  "release": {
    "plugins": [
      ["@semantic-release/commit-analyzer", {
        "releaseRules": [...]
      }]
    ]
  }
}
```

## Building the Gitmoji Mapping

After extracting `releaseRules`:

1. Load `references/gitmoji-defaults.yaml` as the base mapping
2. For each rule in `releaseRules` that has an `emoji` field:
   a. Find the matching entry in the base mapping by emoji
   b. Add or update the `release` field with the rule's value
   c. If the emoji is not in the base mapping, skip it (do
      not invent new entries — the base mapping defines the
      available types)
3. Return the enriched mapping

**The result is the defaults + release tags**, not a
replacement. The semantic-release config only adds `release`
metadata to existing types — it does not change labels,
descriptions, or the type menu order.

## Example

Given this `release.config.mjs`:

```javascript
export default {
  plugins: [
    ["@semantic-release/commit-analyzer", {
      releaseRules: [
        { emoji: "✨", release: "minor" },
        { emoji: "🐛", release: "patch" },
        { emoji: "♻️", release: "patch" },
        { emoji: "📝", release: false },
      ]
    }]
  ]
}
```

The enriched mapping becomes:

```yaml
gitmoji-mapping:
  - emoji: "✅"
    label: Test
    description: "Adding/updating/fixing tests"
    # no release tag — not in releaseRules
  - emoji: "🐛"
    label: Fix
    description: "Bug fixes"
    release: patch
  - emoji: "♻️"
    label: Refactor
    description: "Code refactoring"
    release: patch
  - emoji: "✨"
    label: Feature
    description: "New features"
    release: minor
  - emoji: "📝"
    label: Docs
    description: "Documentation"
    release: none
```

The type menu then shows release impact:

```
Feature [minor] — New features
Fix [patch] — Bug fixes
Refactor [patch] — Code refactoring
Test — Adding/updating/fixing tests
```

## Error Handling

- Config file is unreadable or malformed → log warning, skip
  to defaults (never block the commit)
- `releaseRules` not found in config → skip (config may not
  use gitmoji-based rules)
- `release` value is unexpected → skip that rule
- JS config uses dynamic imports or computed values → skip
  (only static structures are parseable)

## Precedence

Manual strategy overrides (`gitmoji.yaml`) always take
precedence over auto-detection. The resolution order is:

1. Manual strategy from `gitmoji.yaml` (highest)
2. Semantic-release auto-detection (this step)
3. Plugin defaults from `gitmoji-defaults.yaml` (lowest)
