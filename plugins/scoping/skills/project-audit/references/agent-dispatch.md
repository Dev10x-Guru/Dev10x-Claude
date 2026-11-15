# Agent Dispatch Template

Template for dispatching Phase 3 audit agents.

## Dispatch Call

```
Agent(subagent_type="Explore",
    model="sonnet",
    description="Audit Phase X: <name>",
    prompt="""You are auditing a codebase for <phase description>.

    Project context:
    - Language: <detected>
    - Framework: <detected>
    - Architecture: <detected>
    - Modules: <list>

    <phase-specific instructions from references/phase-prompts.md>

    Output format (REQUIRED — use exactly this structure):
    For each finding, produce a structured block:

    ## Finding: <short title>
    - **Location**: <file:line>
    - **Pattern**: <pattern name from catalog>
    - **Current**: <what exists now>
    - **Issue**: <what's wrong or missing>
    - **Recommendation**: <specific action>
    - **Impact**: HIGH | MEDIUM | LOW
    - **Effort**: S | M | L | XL

    End with a ## Summary section counting findings by impact.
    """,
    run_in_background=true)
```

## Dispatch Rules

- One agent per selected phase, all launched in a single tool-call block
- Use `Explore` subagent type (read-only, no edits)
- Model: `sonnet` (Analyze tier)
- Each agent receives the full project context from Phase 1
- Phase-specific instructions come from `references/phase-prompts.md`
- Finding output format comes from `references/finding-format.md`
