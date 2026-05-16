# Strategy: mcp-vs-script-drift

The plugin offers MCP tools that wrap a shell-script fallback.
When the MCP tool becomes the preferred entry point, the script
form should fade out of the agent's context — but it leaks
through several channels:

- **Hook error messages** (e.g., `validate-bash-command.py`) that
  suggest the script path verbatim when blocking a heredoc.
- **SessionStart guidance** listing the script under "Fallback" —
  agents read this and treat it as endorsed.
- **Skill SKILL.md examples** (slack, git-commit, git-fixup,
  skill-audit) that show both forms with the script first.
- **User memories** that accumulate negative rules ("never use the
  script") whose literal forbidden token gets loaded into the
  agent's context every session.

The strategy detects each channel and proposes a targeted fix.

## Script ↔ MCP Equivalence

| Script path | MCP tool |
|-------------|----------|
| `/tmp/Dev10x/bin/mktmp.sh` | `mcp__plugin_Dev10x_cli__mktmp` |
| `.../skills/gh-context/scripts/gh-issue-get.sh` | `mcp__plugin_Dev10x_cli__issue_get` |
| `.../skills/gh-context/scripts/gh-issue-comments.sh` | `mcp__plugin_Dev10x_cli__issue_comments` |
| `.../skills/gh-context/scripts/gh-pr-detect.sh` | `mcp__plugin_Dev10x_cli__pr_detect` |
| `.../skills/gh-pr-monitor/scripts/ci-check-status.py` | `mcp__plugin_Dev10x_cli__ci_check_status` |
| `.../skills/git/scripts/git-push-safe.sh` | `mcp__plugin_Dev10x_cli__push_safe` |
| `.../skills/gh-pr-create/scripts/create-pr.sh` | `mcp__plugin_Dev10x_cli__create_pr` |

## Detection Heuristics

1. **Memory scan** — walk
   `~/.claude/projects/*/memory/*.md` and
   `~/.claude/memory/Dev10x/**/*.md`. Match any of the script
   paths above. Flag if the memory body cites the path literally
   even in a negative context.
2. **Settings scan** — walk `~/.claude/settings.json`,
   `~/.claude/settings.local.json`, and project
   `.claude/settings.local.json`. Flag allow rules referencing the
   scripts above when the MCP equivalent has its own allow rule
   nearby (i.e., the script rule is now redundant).
3. **SKILL.md scan** — walk
   `~/.claude/plugins/cache/Dev10x-Guru/Dev10x/**/SKILL.md`.
   Flag files showing the script form before the MCP form, or
   showing both without indicating the MCP form as canonical.
4. **Hook message scan** — read recent records via
   `mcp__plugin_Dev10x_cli__audit_hook_recent`. Flag hook messages
   that suggest a script path when the MCP equivalent exists.

## Remediation Map

| Finding source | Remediation kind | Target |
|----------------|------------------|--------|
| Memory | `edit_memory` | rewrite to remove literal script path |
| Project settings | `delegate_skill` | `Dev10x:plugin-maintenance` (clean stale rules) |
| Plugin SKILL.md | `file_issue` | upstream PR against the SKILL.md |
| Hook message | `file_issue` | upstream PR against the hook script |

## Anti-patterns

- **Quoting the script path in the fix output.** Rephrase findings
  using the MCP tool name only — never load the forbidden token
  back into context.
- **Auto-fixing across multiple memories.** Each memory edit is
  its own gate. The user owns memory voice and emphasis.
