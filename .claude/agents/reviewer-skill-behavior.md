# Skill Reviewer — Behavior & Orchestration

Behavioral, orchestration, and config checks for skill definitions.
For structure and tool checks, see `reviewer-skill.md`.

## Trigger

Files matching: `skills/**` (same trigger as `reviewer-skill.md`)

## Required Reading

- `references/task-orchestration.md` — orchestration patterns
- `.claude/rules/skill-orchestration-format.md` — formatting as intent
- `.claude/rules/skill-gates.md` — decision gate pattern

## Checklist

15. **Behavioral constraint language** — when a PR upgrades soft language
    to mandatory, verify: (a) rationale is stated; (b) constraint appears
    in Important Notes; (c) scripts are consistent with the constraint.
    Do NOT flag strong imperative language as "over-emphasis".
15a. **Orchestration list formatting** — mandatory tool invocations
    (`TaskCreate`, `TaskUpdate`, `AskUserQuestion`, `Agent`, `Skill`)
    in Orchestration and decision gate sections must use **numbered lists
    with enforcement markers** (`REQUIRED:`, `MANDATORY:`, `DO NOT SKIP`),
    not fenced code blocks. See `skill-orchestration-format.md`.
    **False-positive prevention**: Do NOT flag tool calls in "Example",
    "Anti-pattern", or "Output Format" subsections.
15b. **Bundled call spec references** — complex `AskUserQuestion` gates
    need a `tool-calls/ask-<purpose>.md` file with full call spec.
    Do NOT require bundled files for trivial calls (`TaskUpdate`,
    simple `TaskCreate`).
16. **Config file schema** — when a skill reads/writes structured config
    (YAML, JSON, TOML), SKILL.md must: (a) show schema example,
    (b) document fallback order, (c) state creation policy.
    **False-positive prevention**: "optional, falls back to X" suffices
    for (b).
17. **Resolution-order completeness** — when SKILL.md documents a
    prioritized fallback list with key variants, verify every variant
    appears as a distinct step. A documented variant never checked is
    a logic bug (WARNING).
18. **Conditional steps** — when a task branch produces no artifact,
    the following step must be absent or marked conditional. An
    unconditional step after a branch-point is INFO severity.
19. **Config-file cache coverage** — when a script uses a skip/cache
    pattern, verify ALL config files are in the staleness check.
20. **Decision gates enforcement** — verify: (a) enforcement marker
    present, (b) evals.json includes assertions for plain-text
    substitution detection, (c) evals include `gate*-uses-tool` signals.
21. **Task dependency cross-validation** — for orchestration skills with
    numbered TaskCreate lists and dependency annotations, verify each
    phase's documented inputs match its dependency list. Skip for
    script-based skills or skills without dependency annotations.
22. **Subagent status protocol presence (GH-69)** — when a skill section
    documents an `Agent(...)` dispatch prompt (Phase 2 Gather, Wave 2
    audit, architect dispatch, fanout sub-agent, etc.), verify the
    prompt body includes the four-status template from
    `references/orchestration/subagent-status-protocol.md` (`DONE`,
    `DONE_WITH_CONCERNS:`, `NEEDS_CONTEXT:`, `BLOCKED:`). Flag missing
    status-protocol instructions as WARNING — controllers cannot
    branch deterministically without it and fall back to heuristic
    parsing of free-form prose.
    **False-positive prevention**: Do NOT flag dispatch examples in
    "Anti-pattern" subsections or in pure background-monitor
    dispatches whose result is a side effect (push notification)
    rather than a status the controller parses.
23. **Inline-context vs read-on-demand (GH-69)** — when an `Agent(...)`
    dispatch is in the Gather, Replicate, or Analyze tier per
    `.claude/rules/model-selection.md`, prefer the inline-context
    pattern: the controller pre-reads files and pastes them into the
    prompt under `<file path="...">...</file>` blocks. Flag prompts
    that instruct the subagent to Read files dynamically when the
    file set is known upfront — this is the source of permission-
    stall failures (mode `dontAsk` does not propagate into the
    subagent).
    **False-positive prevention**: Do NOT flag Investigate/Explore
    tier dispatches where the file set is genuinely unknown.

## Output Format

Same as `reviewer-skill.md`: **File** · **Severity** · **Issue**
