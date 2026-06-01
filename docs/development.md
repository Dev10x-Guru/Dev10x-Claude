# Development

## Test locally without installing

```bash
claude --plugin-dir /path/to/Dev10x
```

## Validate plugin structure

```bash
claude plugin validate /path/to/Dev10x
```

## Run tests

```bash
uv run --extra dev pytest           # all tests with coverage
uv run --extra dev pytest -x        # stop on first failure
uv run --extra dev pytest -k "test_name"  # filter by name
```

## Lint and format

```bash
uv run ruff check .                 # lint
uv run ruff format --check .        # format check
uv run ruff format .                # auto-format
```

## Project structure

| Directory | Purpose |
|-----------|---------|
| `src/dev10x/` | Python package — CLI, validators, hooks, MCP servers |
| `tests/` | Unified test suite (mirrors `src/`) |
| `skills/` | 67 skill definitions (SKILL.md + optional scripts) |
| `agents/` | 21 plugin-distributed sub-agent specs |
| `hooks/` | 14 hook scripts across 5 lifecycle events |
| `servers/` | MCP server entry points |
| `commands/` | Slash command definitions |
| `references/` | Shared docs (git, review, JTBD guides) |
| `bin/` | Release and CI helper scripts |
| `.claude-plugin/` | Plugin manifest (`plugin.json`) |
| `.claude/rules/` | Always-loaded essentials + path-scoped rules |
| `.claude/agents/` | Internal domain-specific reviewer agents |

## MCP servers

The plugin exposes tools via MCP servers registered in
`.claude-plugin/plugin.json`:

- **`cli`** — Git operations, PR management, tracker detection,
  worktree creation, temporary files
- **`db`** — Safe read-only database queries

See `.claude/rules/mcp-tools.md` for the full tool inventory
and naming conventions.

## Adding a new skill

1. Create `skills/<name>/SKILL.md` with frontmatter
2. Use `Dev10x:<name>` as the invocation name
3. Declare external tools in `allowed-tools:` frontmatter
4. Add scripts under `skills/<name>/scripts/` if needed
5. Run `claude plugin validate` to check structure

See `.claude/rules/skill-naming.md` for naming conventions and
`.claude/rules/skill-patterns.md` for the two skill patterns
(script-based vs orchestration-based).

## Adding a new hook

Hooks live in `hooks/scripts/` and are registered in
`hooks/hooks.json`. Supported lifecycle events:

| Event | When it fires |
|-------|--------------|
| `SessionStart` | Session begins |
| `PreToolUse` | Before a tool executes |
| `PostToolUse` | After a tool executes |
| `PreCompact` | Before context compaction |
| `Stop` | Session ends |

See `.claude/rules/hook-input-patterns.md` for safe input
parsing patterns.

## Release process

```bash
bin/release.sh features   # strip .dev0, tag, release, bump to next minor .dev0
bin/release.sh fixes      # bump patch, strip .dev0, tag, release
bin/release.sh major      # bump major, strip .dev0, tag, release
```

Releases merge `develop` → `main` and create a GitHub release.

### Dogfood smoke gate (Phase 2b)

The release script requires a manual smoke confirmation before tagging.
After preparing the version (Phase 2), the script pauses and prints:

```
claude --plugin-dir /path/to/Dev10x-Claude
```

You must run a real `--plugin-dir` session with the release candidate and
verify:

- Plugin loads without errors
- One Dev10x skill that exercises recent MCP-server changes runs cleanly
  (e.g. `Dev10x:gh-pr-review` or `Dev10x:gh-pr-respond`)
- One `Dev10x:git-commit` to exercise the bash tokenizer and
  privilege-escalation denies
- No unexpected permission prompts or tool errors

The script also surfaces a version-skew warning when the installed
marketplace plugin lags the develop checkout, so you know which MCP server
is active.

Type `ship <version>` at the prompt to confirm and proceed to tagging.

**Why**: CI runs under mocks. The only true runtime validation of
MCP-server and permission-hook changes requires a live session with the
develop checkout loaded via `--plugin-dir`.

To skip in CI (automated pipelines only):

```bash
SKIP_DOGFOOD=1 bin/release.sh features
```

[Back to README](../README.md)
