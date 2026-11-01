# Spec Gate Dispatch — Step 1b of `dev10x:review` (GH-69)

The dispatch template for the Phase 0 `spec-reviewer` gate. When to
skip the gate, and how to branch on its verdict, stay in SKILL.md
because they decide whether the rest of the review runs.

## Pre-read inputs (controller side)

Read the linked ticket body (via `mcp__plugin_dev10x_cli__issue_get`
or the appropriate tracker MCP) and the PR Job Story if present, plus
the full branch diff. Phase 0 runs before Step 2, so resolve the base
the way Step 2 does first — `<base>` from
`mcp__plugin_dev10x_cli__detect_base_branch`, then
`git fetch origin <base>` and `git diff origin/<base>...HEAD` — and
reuse that diff in Step 2 rather than taking a second one against a
possibly stale local ref (GH-1463). Inline both
into the dispatch prompt under `<ticket>` and `<diff>` blocks —
`spec-reviewer` will not Read files dynamically (see
`agents/spec-reviewer.md`).

## Dispatch

```
Agent(
    subagent_type="spec-reviewer",
    description="Spec compliance check for current branch",
    prompt="""Verify the following diff matches the linked ticket's
    acceptance criteria and Job Story.

    <ticket>
    {inlined ticket body + AC}
    </ticket>

    <job_story>
    {inlined Job Story from latest commit or PR body}
    </job_story>

    <diff>
    {inlined branch diff}
    </diff>

    Follow the checklist in your spec. Return one paragraph per
    finding (AC ref / file:line / verdict).

    Report your final status as the LAST line of your output,
    with exactly one of these prefixes:

    - DONE                       — PASS
    - DONE_WITH_CONCERNS: <text> — PARTIAL (proceed but flag)
    - NEEDS_CONTEXT: <what>      — re-dispatch needed
    - BLOCKED: <verdict>: <reason> — FAIL_SCOPE / FAIL_MISSING /
                                     FAIL_OVER

    Do not write anything after the status line.""")
```
