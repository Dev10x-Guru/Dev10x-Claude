# Dev10x:doctor — Strategy Catalog

The doctor ships with a base catalog of strategies, each owning
one drift category. Strategies are pluggable: adding a new
strategy file under `src/dev10x/skills/doctor/strategies/` and
registering it in `strategies.yaml` is enough — no skill-core
changes required.

## Shipped Strategies

| Strategy | Detects | Remediation |
|----------|---------|-------------|
| `mcp-vs-script-drift` | Memory / settings / SKILL.md references to `*.sh` paths that have MCP equivalents (`mktmp`, `ci_check_status`, `pr_detect`, `push_safe`, `issue_get`, `pr_comments`). | Sanitize memories; offer to rephrase to MCP-only; flag SKILL.md examples for upstream PR. |
| `cluster-coverage` (GH-115) | User-wide directories repeatedly accessed in tool-use that lack `additionalDirectories` + Read/Write/Edit + find/ls/grep allow rules. | Propose a coherent four-piece patch per cluster. |
| `local-skill-approval` (GH-116) | Local skills under `~/.claude/skills/` that lack `Skill(<name>)` allow rules in active projects. | Per-project AskUserQuestion matrix; emit namespace wildcard when threshold met. |
| `uv-run-project` (GH-137) | `uv run --project <path> <tool>` invocations not covered by global `Bash(uv run <tool>:*)` rules. | One `Bash(uv run --project <path>:*)` per detected pyproject directory. |
| `hook-message-drift` | Hook error messages that suggest patterns conflicting with the current preferred flow (e.g., script fallback after MCP became canonical). | File an upstream PR against the hook script. |
| `memory-negative-reinforcement` | Memories whose negative examples literally contain the offending path string — re-loading the forbidden token into every session. | Rephrase to remove the literal forbidden path. |
| `skill-doc-fallback-first` | SKILL.md files showing a script fallback before/alongside its MCP equivalent. | Suggest doc reorder so the MCP path is the only first-class option. |

## Strategy Interface

```python
@dataclass
class Strategy:
    id: str
    description: str
    detect: Callable[[Context], list[Finding]]
    remediate: Callable[[Finding], Remediation]
```

`Context` carries paths to settings files, memory directories, and
hook log accessors. Strategies must treat the context as read-only —
the doctor's Phase 4 owns all writes.

`Finding` carries `strategy_id`, `severity`, `location`,
`evidence`, and `proposed_fix`. `severity` is one of `critical`,
`drift`, `suggestion`.

`Remediation` describes the concrete edit:

```python
@dataclass
class Remediation:
    kind: Literal["edit_memory", "edit_settings", "file_issue", "delegate_skill"]
    target: str            # path or skill name
    action: dict           # strategy-specific payload
```

## Adding a Strategy

1. Create `src/dev10x/skills/doctor/strategies/<id>.py`
2. Export a module-level `STRATEGY: Strategy` constant
3. Add the module path to `strategies.yaml` under `enabled:`
4. Add tests under `tests/skills/doctor/strategies/test_<id>.py`

User strategies live under
`~/.claude/Dev10x/doctor/strategies/` and load after defaults so
project-specific detectors don't require plugin changes.
