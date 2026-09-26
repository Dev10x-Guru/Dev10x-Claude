# Dev10x

Claude Code plugin providing reusable skills, hooks, and commands for
development workflows.

## Directory Layout

This repo is a **single unified `Dev10x` plugin**. All skills, hooks,
and config are defined at the root level.

| Directory        | Purpose                                    |
|------------------|--------------------------------------------|
| `src/dev10x/`    | Python package (CLI, validators, hooks, MCP)|
| `tests/`         | Unified test directory (mirrors src/)      |
| `skills/`        | Skill definitions (SKILL.md + scripts)     |
| `commands/`      | Slash command definitions                  |
| `hooks/`         | PreToolUse / PostToolUse hook entry points |
| `servers/`       | MCP server scripts                         |
| `bin/`           | Helper scripts (release, CI)               |
| `.claude-plugin/`| Plugin manifest (`plugin.json`)            |
| `agents/`        | Plugin-distributed sub-agent specs         |
| `references/`    | Shared docs (git, review, JTBD guides)     |
| `.claude/rules/` | Always-loaded essentials + path-scoped rules |
| `.claude/agents/`| Internal domain-specific reviewer agents   |

## Development

```bash
claude --plugin-dir .          # load plugin locally
claude plugin validate         # validate plugin structure
dev10x --help                  # CLI entry point
uv run --extra dev pytest      # run tests with coverage
uv run --extra dev pre-commit install      # one-time: enable lint-on-commit
uv run --extra dev pre-commit run --all-files  # run the canonical lint suite
```

Linting/formatting (ruff, mypy, shellcheck) runs via `pre-commit`,
never inline — `.pre-commit-config.yaml` is the single source of
truth. Skills defer to `pre-commit run`. MCP migration: shell
scripts → MCP tools. See `.claude/rules/mcp-tools.md`.

## External Tool Declarations

Skills that invoke external scripts must declare them in SKILL.md
`allowed-tools:` (e.g. `Bash(${CLAUDE_PLUGIN_ROOT}/skills/<name>/scripts/:*)`),
covering both SKILL.md and any delegated `instructions.md` — missing
entries cause per-invocation approval friction. See
`.claude/rules/mcp-tools.md` for MCP vs. direct script trade-offs.

## Coding Style

- **Python scripts**: ruff + black (line-length 99)
- **Shell scripts**: shellcheck, `set -e`, POSIX-compatible where possible
- **Markdown**: one sentence per line, 80-char soft wrap
- **Data-retrieval naming**: `get_*`/`load_*`/`read_*`/`fetch_*` each
  have a specific meaning — see `.claude/rules/naming-conventions.md`.

## Rule & Config Discipline

- **Rule documentation standards** for authoring new rules in
  `.claude/rules/*.md`: `.claude/rules/rule-documentation-standards.md`.
- **CWD discipline (GH-979)**: route subprocess/CWD access through
  `subprocess_utils` / `GitContext()`, never bare `subprocess.run` /
  `os.getcwd()` / module-scope `GitContext()`. Full rules:
  `.claude/rules/cwd-discipline.md`.
- **uv-script dependency pins (GH-916)**: every PEP 723 dependency
  and `pyproject.toml` array entry needs an upper bound or exact pin
  (`requires-python` is the one exception). Full rules:
  `.claude/rules/uv-script-dependency-pins.md`.

## Skill Naming Convention

- **Directory name**: plain feature name — `git-worktree/`.
  **Invocation name**: `Dev10x:<feature>` — `Dev10x:git-worktree`.
  See `.claude/rules/skill-naming.md` for full convention.
- **Decision Gates**: Skills with blocking user choice points MUST use
  `AskUserQuestion` tool calls (not plain text). See `.claude/rules/skill-gates.md`

## Git Conventions

- **Default branch**: `develop` (PR target). **Release branch**: `main`.
- **Branch naming**: `username/TICKET-ID/short-description` (worktree
  adds `/worktree-name` before the slug).
- **Commit format**: `<gitmoji> <TICKET-ID> <JTBD outcome>`
- **Commit titles**: outcome-focused — "Enable X" not "Add X"
- **Job Story voice** (REQUIRED): third-person concrete domain actor
  — never first-person or a faceless "the user wants to". See
  `.claude/rules/essentials.md` § Choosing the Actor.
- **Story language**: project/ticket language; Gherkin keywords per
  Cucumber's language reference.
- See `references/git-commits.md`, `git-pr.md`, `git-jtbd.md`

**Plugin directory renames**: `git mv`; update
`.claude-plugin/marketplace.json`, every SKILL.md referencing the
old path, and any hardcoded paths.

## Code Review

Multi-agent architecture with domain-routed reviewers. See
`.claude/rules/INDEX.md` and `references/rules-architecture.md`.
