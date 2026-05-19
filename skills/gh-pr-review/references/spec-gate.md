# Step 2b: Phase 0 — Spec Compliance Gate (GH-69)

Before reading per-file context or drafting inline comments,
dispatch the `spec-reviewer` agent to confirm the PR diff matches
the linked ticket's acceptance criteria and the PR's Job Story.
Domain-level review (architecture, style, suggestions) is wasted
effort when scope is wrong or AC are unmet — surfacing that
early lets the reviewer post a single short-circuit comment
instead of a multi-page review against the wrong target.

## Skip Phase 0 when

- The PR has no linked ticket AND no Job Story
- The diff is purely additive infra (a new agent spec, a new
  reference doc) where scope is self-evident from the file path

## Pre-read inputs (controller side)

The diff and PR body are already loaded in Step 2. Fetch the
linked ticket body via the appropriate tracker MCP (parse
`Fixes: GH-N` / `TEAM-N` / `JIRA-N` from the PR body or branch
name) and inline it. Do NOT instruct the agent to fetch the
ticket itself — that triggers permission prompts inside the
subagent.

## Dispatch

```
Agent(
    subagent_type="spec-reviewer",
    description=f"Spec compliance check for PR #{N}",
    prompt="""Verify the following PR diff matches the linked
    ticket's acceptance criteria and Job Story.

    <ticket>
    {inlined ticket body + AC, or "NO_LINKED_TICKET" if none}
    </ticket>

    <pr_body>
    {inlined PR body — Job Story is the first paragraph}
    </pr_body>

    <diff>
    {inlined output of `gh pr diff N`}
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

## Parse the trailing status line and branch

- `DONE` → continue to Step 3 (read changed files)
- `DONE_WITH_CONCERNS: <text>` → continue; record the concern
  as a top-of-summary note in the eventual review body
- `NEEDS_CONTEXT: <what>` → re-dispatch with the requested
  additional inline context once
- `BLOCKED: <verdict>: <reason>` → skip Steps 3–6, post a
  concise review whose body cites the verdict and asks the
  author to address the spec gap before quality review. Still
  hide obsolete summaries (Step 7) and post via Step 8.
