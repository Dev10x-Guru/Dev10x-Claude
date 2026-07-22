# Dev10x

Claude Code plugin providing reusable skills, hooks, and commands for
development workflows.

## Directory Layout

This repo is a **single unified `Dev10x` plugin** (consolidated from 11
separate plugin directories). All skills, hooks, and config are defined at
the root level.

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
never inline — `.pre-commit-config.yaml` is the single source of truth
(GH-619). Skills defer to `pre-commit run` (GH-592, GH-596).

MCP migration: shell scripts → MCP tools. See `.claude/rules/mcp-tools.md`.

## External Tool Declarations

All skills that invoke external scripts (shell, Python, etc.) must declare
them in SKILL.md front matter under `allowed-tools:`:

```yaml
allowed-tools:
  - Bash(${CLAUDE_PLUGIN_ROOT}/skills/<name>/scripts/:*)
```

When a skill delegates to an `instructions.md` file, verify `allowed-tools:` in
SKILL.md covers ALL external tool calls in both SKILL.md AND instructions.md.

Missing declarations cause per-invocation approval friction — users cannot
invoke the skill without approving tool access each time. See
`.claude/rules/mcp-tools.md` for MCP vs. direct script trade-offs.

## Coding Style

- **Python scripts**: ruff + black (line-length 99)
- **Shell scripts**: shellcheck, `set -e`, POSIX-compatible where possible
- **Markdown**: one sentence per line, 80-char soft wrap
- **Data-retrieval naming**: prefer `get_*` for functions that fetch and
  return data. Use `load_*` for reading and parsing config/catalog files
  (`load_yaml`, `load_json`, `load_config`) and `read_*` for byte- or
  line-level file I/O (`read_applied_version`, `read_plugin_version`) —
  both are blessed, dominant conventions, not exceptions. Reserve
  `fetch_*` for names carrying protocol/domain semantics (`git fetch`,
  HTTP fetch) or documented exceptions such as `fetch_mergeable` and
  `fetch_merged_prs` (`skills/release/collect_prs.py`). Do not
  rename-sweep existing `load_*`/`read_*` functions to `get_*`.

## Rule Documentation Standards

When documenting new rules in `.claude/rules/*.md`:
- Expand reviewer checklists with concrete checks before they accumulate as
  lint suggestions (a new rule invites new edge cases; document them when the
  rule lands to prevent silent divergence)
- Document acceptable exceptions explicitly (e.g., when `sys.exit()` is OK in
  a domain function): future consolidations need clear guidance on what violates
  the rule vs. what is an documented exception
- Use numbered lists in checklists (not bullets) to signal mandatory sequential
  verification steps to reviewers

### CWD Discipline (GH-979)

Route subprocess/CWD access through `subprocess_utils` (`run`,
`async_run`, `effective_cwd()`) and `GitContext()` — never bare
`subprocess.run` / `os.getcwd()` / module-scope `GitContext()`. Standalone
uv-scripts are exempt. Full rules: `.claude/rules/cwd-discipline.md`.

## Skill Naming Convention

- **Directory name**: plain feature name — `git-worktree/`, `skill-audit/`
- **Invocation name** (`name:` in SKILL.md): `Dev10x:<feature>` — `Dev10x:git-worktree`
- The `Dev10x:` prefix identifies this plugin's skills at invocation time
  without cluttering the filesystem
- See `.claude/rules/skill-naming.md` for full convention
- **Decision Gates**: Skills with blocking user choice points MUST use
  `AskUserQuestion` tool calls (not plain text). See `.claude/rules/skill-gates.md`

## Git Conventions

- **Default branch**: `develop` (PR target)
- **Release branch**: `main` (merge from develop via release script)
- **Branch naming**: `username/TICKET-ID/short-description`
  (worktree: `username/TICKET-ID/worktree-name/short-description`)
- **Commit format**: `<gitmoji> <TICKET-ID> <JTBD outcome>`
- **Commit titles**: outcome-focused — "Enable X" not "Add X"
- **Job Story voice** (REQUIRED): Third-person domain actor —
  "**[actor] wants to** ... **so [beneficiary] can** ..." with concrete
  roles (service writer, dealer, admin, wholesaler) — never first-person
  ("I want to") or a faceless "the user wants to". See
  `.claude/rules/essentials.md` and `references/git-jtbd.md`
  § Choosing the Actor
- See `references/git-commits.md`, `git-pr.md`, `git-jtbd.md`

### Plugin Directory Renames

When renaming a plugin directory (e.g., `plugins/old/ → plugins/new/`):

1. Use `git mv` to preserve history
2. Update `.claude-plugin/marketplace.json` reference
3. Update all SKILL.md files that reference the old path
4. Search codebase for hardcoded directory paths

## Code Review

Multi-agent architecture with domain-routed reviewers.
See `.claude/rules/INDEX.md` for the routing table and
`references/rules-architecture.md` for the full architecture.
