# Evaluation Schema for Skills

Reference format for `evals/evals.json` files in skill definitions.

## When to Create evals.json

Every skill with **decision gates** (blocking user choice points) MUST
include evaluation criteria. Optional for simpler skills.

## File Structure

```json
{
  "description": "What this skill does",
  "evals": [...],
  "trigger_evals": {...}
}
```

## Canonical Format for New Skills

All new skills MUST use the **dimension-referenced format** established in
`skills/memory-maintenance/evals/evals.json` and
`skills/playbook-maintenance/evals/evals.json`. This format ensures:
- Consistent assertion/dimension cross-references (`dimension` field → eval_dimensions.id)
- Explicit signals for test automation and regression detection
- Structured input/output documentation

### Dimension-Referenced Format (Required for New Skills)

```json
{
  "skill_name": "Dev10x:example-skill",
  "eval_dimensions": [
    {
      "id": "dimension_1",
      "name": "Decision Gate Enforcement",
      "description": "Tool is called, not substituted with plain text"
    }
  ],
  "evals": [
    {
      "id": "eval_scenario_1",
      "name": "Scenario name",
      "description": "What this test validates",
      "input": "/Dev10x:example-skill",
      "assertions": [
        {
          "dimension": "dimension_1",
          "check": "tool_called",
          "value": "AskUserQuestion",
          "signal": "What to look for in transcript"
        }
      ]
    }
  ]
}
```

### Working Examples

Copy structure from these reference implementations:
- `skills/memory-maintenance/evals/evals.json` — ✓ Canonical format
- `skills/playbook-maintenance/evals/evals.json` — ✓ Canonical format

## Legacy Evals Format

Earlier skills used a `setup`/`checks` structure. This format is
documented below for reference, but **DO NOT use for new skills**.

### Legacy Format (Deprecated)

Each eval scenario tests a specific code path:

```json
{
  "name": "scenario-name",
  "description": "Brief description of test scenario",
  "setup": "Input conditions (PR URL, comments, etc.)",
  "checks": [
    {
      "type": "tool_called",
      "tool": "AskUserQuestion",
      "assertion": "gate1_uses_tool",
      "signal": "AskUserQuestion is called at decision point X"
    },
    {
      "type": "tool_parameters",
      "tool": "AskUserQuestion",
      "assertion": "gate1_correct_options",
      "signal": "Options list contains exactly ['Option A', 'Option B']"
    },
    {
      "type": "behavioral",
      "assertion": "no_auto_resolve",
      "signal": "Thread is NOT auto-resolved before user confirms"
    }
  ]
}
```

## Check Types

| Type | Purpose | Example |
|------|---------|---------|
| `tool_called` | Verify tool is invoked (not skipped or substituted) | Confirm AskUserQuestion called, or Skill() invoked |
| `tool_parameters` | Validate tool arguments match spec | Check multiSelect=true, option labels, skill name |
| `behavioral` | Verify side effects (not just tool presence) | Task state updated, no auto-progression |
| `plain_text` | Detect forbidden plain-text questions (negative check) | Catch "Do you want to proceed?" inline |
| `rubric` | Judge an output against a stated standard when no mechanical check can express it | "Name the ROI bucket this title reads as; fail if none applies" |

### Batch Checks (GH-1225)

Some defects exist only *across* a set of outputs and are invisible
one at a time. A monoculture is the worked example: every title in a
release bundle can be individually well-formed while the batch is
unreadable because they all open the same way. An eval declaring
`"batch": true` in its `setup` produces several outputs from several
inputs, and these checks judge them together.

| Type | Purpose | Parameter |
|------|---------|-----------|
| `batch_opening_word_share` | Fail when too much of the batch opens with the same word | `max_share` (0..1) |
| `batch_titles_distinct` | Fail when two outputs are separated only by a short prefix | `min_distinct_prefix_words` |

A single-output eval **cannot** substitute for these: it has nothing
to compare against, so it passes on the batch that provoked the rule.
GH-1225 shipped with exactly that gap — a single-title eval for a
defect that only appears at batch scale — and it was caught in review
rather than by the eval.

## Trigger Evals

Disambiguate when the skill should/should-not run:

```json
{
  "should_trigger": [
    "Natural language request matching skill intent",
    "Direct skill invocation with proper arguments"
  ],
  "should_not_trigger": [
    "Request that matches a different skill's scope",
    "Incomplete or ambiguous input that needs clarification first"
  ]
}
```

## Signal Patterns

Signals are **machine-detectable patterns** for regression detection:

- ✓ `gate*-uses-tool`: "AskUserQuestion" appears in tool call list
- ✓ `gate*-correct-options`: Option labels match documented list
- ✓ `skill*-uses-tool`: "Skill(" appears in tool call list (e.g., "Skill(Dev10x:gh-pr-fixup)")
- ✓ `skill*-tool-called`: Skill() tool invocation appears, not just mentioned in reasoning
- ✗ `gate*-no-plain-text`: No inline question text before tool call
- ✗ `no-auto-*`: Explicit user confirmation before proceeding
- ✗ `no-inline-delegation`: Skill not invoked via inline natural language
- ✗ `no-stated-but-not-executed`: Skill() promise not followed by actual tool call

Use negative signals (`✗`) to detect regressions like:
- Agents asking "Confirm this action?" as text instead of calling AskUserQuestion
- Agents delegating to skills via text ("Call the fixup skill") instead of Skill() tool
- Agents stating they'll call Skill() but proceeding inline without the tool call
- Auto-resolving states without user confirmation
- Silently accepting defaults

## Naming Convention

- **Eval names**: `kebab-case-describing-scenario` (e.g., `batch-mode-full-flow`)
- **Assertion names**: `gate{N}_{check_type}` (e.g., `gate1_uses_tool`)
- **Signals**: Plain English describing what to look for in transcript

## Examples

### Example 1: AskUserQuestion Gate (from PR #136)

```json
{
  "name": "single-comment-invalid-verdict",
  "description": "Mode A (single comment) with INVALID verdict",
  "setup": "One comment with INVALID verdict triggers two gates",
  "checks": [
    {
      "type": "tool_called",
      "tool": "AskUserQuestion",
      "assertion": "gate1_uses_tool",
      "signal": "AskUserQuestion for thread resolution decision"
    },
    {
      "type": "plain_text",
      "assertion": "gate1_no_plain_text",
      "signal": "No inline 'Resolve thread?' before tool call"
    }
  ]
}
```

**Gate Naming Pattern**: When a skill has multiple decision gates (e.g.,
experience level selection, alias setup confirmation, tour summary), name
assertions using the `gate{N}_*` pattern:

```
SKILL.md Line 42: **REQUIRED: Call `AskUserQuestion`** (experience level)
  → evals.json: "gate1_uses_tool"

SKILL.md Line 87: **REQUIRED: Call `AskUserQuestion`** (git alias setup)
  → evals.json: "gate2_uses_tool", "gate2_correct_options"

SKILL.md Line 142: **REQUIRED: Call `AskUserQuestion`** (tour summary review)
  → evals.json: "gate3_uses_tool"
```

**Avoid domain-specific names** (e.g., `alias_setup_offered`, `tour_confirmed`)
which obscure the gate number and make merge validation harder. Numbered gates
make it easy to audit: "Does SKILL.md have N gates? Does evals.json have N
corresponding assertions?"

### Example 2: Skill() Delegation (Enforcement Coverage)

```json
{
  "name": "valid-comment-fixup-delegation",
  "description": "VALID verdict triggers skill delegation to fixup",
  "setup": "Comment marked VALID; should delegate to gh-pr-fixup",
  "checks": [
    {
      "type": "tool_called",
      "tool": "Skill",
      "assertion": "fixup_uses_skill_tool",
      "signal": "Skill(Dev10x:gh-pr-fixup) is called"
    },
    {
      "type": "tool_parameters",
      "tool": "Skill",
      "assertion": "fixup_skill_correct_args",
      "signal": "Skill call includes comment URL and context"
    },
    {
      "type": "plain_text",
      "assertion": "no_inline_fixup_delegation",
      "signal": "No inline 'I will implement the fix' before Skill() call"
    }
  ]
}
```

## Size Guidelines

- Minimum: 2 test scenarios for skills with 2+ decision gates
- Typical: 3-5 scenarios covering major code paths
- Maximum: One scenario per significant user workflow variation

Each scenario ≤ 10 assertions; complex evals should split into multiple scenarios.
