---
name: Dev10x:skill-reinforcement
description: >
  Remind the agent about available skills when it uses CLI commands
  that should be handled by skills or MCP tools instead. Reads
  conversation context to identify the offending command, matches
  it against a command-to-skill map, and outputs a firm reinforcement
  message pointing to the correct skill.
  TRIGGER when: user sees agent using CLI instead of a skill, user
  rejects a command that should have been a skill, or user says
  "use the skills".
  DO NOT TRIGGER when: agent is already using skills correctly,
  or the CLI command has no skill equivalent.
user-invocable: true
invocation-name: Dev10x:skill-reinforcement
allowed-tools:
  - AskUserQuestion
  - Read(~/.claude/SKILLS.md)
  - Read(~/.claude/settings.json)
  - Read(~/.claude/settings.local.json)
  - Read(.claude/settings.json)
  - Read(.claude/settings.local.json)
  - Read(${CLAUDE_PLUGIN_ROOT}/skills/skill-reinforcement/references/*)
  - Read(${CLAUDE_PLUGIN_ROOT}/src/dev10x/validators/command-skill-map.yaml)
---

# Dev10x:skill-reinforcement

Quick reinforcement nudge when an agent reaches for CLI commands
instead of using available skills or MCP tools.

## When to Use

Invoke this skill when:
- The agent ran a CLI command that a skill already handles
- You rejected a command and want the agent to use a skill instead
- You approved a command but want to reinforce the skill habit
- You want to say "use the skills" with a structured response

## Orchestration

**REQUIRED: Create a task at invocation.** Execute at startup:

1. `TaskCreate(subject="Reinforce skill usage", activeForm="Reinforcing")`

Mark completed when done: `TaskUpdate(taskId, status="completed")`

## Instructions

### Step 1: Identify the offending command

Scan the recent conversation for the CLI command that triggered
this invocation. Look for:
- The most recent `Bash` tool call that was rejected or approved
- Any command the user flagged as wrong
- If the user provided arguments (e.g., `/Dev10x:skill-reinforcement kubectl`),
  use that as the command identifier

Store the command string for matching.

### Step 2: Match against command-skill map

Read the command-skill mapping from the canonical location:
`${CLAUDE_PLUGIN_ROOT}/src/dev10x/validators/command-skill-map.yaml`.

The YAML in `skills/skill-reinforcement/references/command-skill-map.yaml`
is a legacy copy — prefer the hook's YAML which is the single
source of truth.

Match the identified command against the `patterns` list in each
mapping entry. Use prefix matching — if the command starts with
any pattern in the list, it matches that entry.

If no match is found in the map, fall back to Step 3.

### Step 2b: Check workflow context

If a pattern match is found but the command appears to be a valid
part of the currently active skill's documented workflow, check
whether the skill says to **delegate** for this case:

- Read the active skill's SKILL.md (if identifiable from context)
- Check if the command matches a delegation point marked with
  `REQUIRED: Skill()` — a command can be valid syntax within
  a skill but still a violation if the skill mandates delegation
  to a sub-skill for that operation
- Example: `gh api --method POST .../replies` is documented in
  `gh-pr-respond` but the skill requires VALID comments to go
  through `Dev10x:gh-pr-fixup` — using the raw API is a violation

If the command is a delegation bypass, treat it as a match and
output the reinforcement pointing to the correct sub-skill.

### Step 3: Fall back to SKILLS.md

If no direct mapping exists, read `~/.claude/SKILLS.md` and scan
skill descriptions from the system-reminder context to find the
best match based on the command's purpose.

### Step 3b: Permission friction audit

Most rejections happen not because the command is wrong but
because the agent packed too much into a single Bash call and
the resulting prefix does not match any pre-approved allow-rule.
Before producing the final reinforcement, audit settings for a
simpler, pre-approved alternative.

**Sources** (read each; tolerate missing files):
- `.claude/settings.local.json` — project-local overrides
- `.claude/settings.json` — project shared
- `~/.claude/settings.json` — user global
- `~/.claude/settings.local.json` — user local

Parse `permissions.allow` from each. Allow-rule shapes to handle:
- `Bash(<exact>)` — exact command match
- `Bash(<prefix>:*)` — prefix match
- `Read(<glob>)`, `Edit(<glob>)`, etc. — non-Bash tools

**Audit procedure:**
1. Extract the leading executable + first 1–2 args from the
   offending command (the "effective prefix" used by Claude
   Code's matcher).
2. Compare against each allow-rule prefix. Note any rule that
   would match a simpler form of the same intent:
   - Command had `&&`, `;`, or subshell chaining → propose the
     unchained first command; if it matches an allow-rule,
     that's the pre-approved alternative
   - Command had an env-var prefix (`FOO=bar git ...`) → strip
     the prefix and recheck
   - Command used `cd <path> && <cmd>` → drop the `cd`
     (CWD is already correct) and recheck
3. If a close allow-rule exists, surface it as a **pre-approved
   alternative** — instruct the agent to invoke the simpler
   form (one command per Bash call, no chaining).
4. If no allow-rule covers any simplified variant, propose a
   **safe, targeted addition** to `.claude/settings.local.json`.
   Prefer narrow prefixes (`Bash(git fetch:*)`) over broad ones
   (`Bash(git:*)`). Never propose `Bash(*)` or rules that span
   destructive verbs.

The audit output feeds Step 4 — surface findings even when a
skill match was also found, since switching to the simpler
pre-approved form is often what the supervisor actually wanted.

### Step 4: Output reinforcement message

Output a firm, concise reinforcement message with these sections:

1. **Command detected:** — the CLI command that was identified
2. **Use instead:** — skill invocation name and one-line description
3. **Why:** — reason from the map entry (if available)
4. **How to invoke:** — `Skill("<skill-name>")` call syntax.
   For MCP tools, add: "Call this as an MCP tool call, NOT as a
   Bash command. MCP tool names are tool interface identifiers,
   never shell executables. Example:
   `mcp__plugin_Dev10x_cli__mktmp(namespace='git',
   prefix='commit-msg', ext='.txt')` — not
   `mcp__plugin_Dev10x_cli__mktmp git commit-msg .txt`."
5. **Pre-approved alternatives:** — from Step 3b audit. If a
   simpler form of the command matches an existing allow-rule,
   show that form and the rule that covers it. If no rule
   matches, show the proposed targeted allow-rule snippet and
   the settings file it should land in. Omit this section when
   the audit found no friction (the command was already simple
   and pre-approved, or no Bash command was involved).
6. **Related skills:** — from the map entry (if available)

If multiple skills could apply, list all of them ranked by
relevance.

### Step 4b: Respect user rejection

**If the user explicitly rejected the command** (denied the Bash
tool call), do NOT conclude "no violation found" and resume the
rejected workflow. A user rejection overrides documentation
matching — even if the command appears valid within the skill,
the user's denial takes precedence. Instead, ask the user what
they expected if no skill match is found.

### Step 5: Reinforce the general principle

End with a brief reminder:

> Always check if a skill or MCP tool exists before reaching for
> CLI commands. Skills provide consistent behavior, proper tool
> declarations, and avoid permission friction.
>
> Prefer pre-approved commands. Keep each Bash call to one simple
> command — no `&&`/`;` chaining, no env-var prefixes, no leading
> subshells. Packing multiple steps into one call shifts the
> effective prefix and breaks allow-rule matching, which is the
> main reason supervisors see avoidable permission prompts. When
> no pre-approved form fits, propose a narrow targeted allow-rule
> rather than crafting a more elaborate command.

### Step 6: Offer follow-up action (REQUIRED when command was rejected)

If the triggering command was **rejected** by the user (denied
the Bash tool call), the reinforcement must actively offer to
retry the intended action via the recommended skill. Plain text
offers ("Want me to invoke X?") do NOT block execution and break
the structured decision flow used across Dev10x skills.

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text).

1. `AskUserQuestion(questions=[{question: "Invoke <recommended-skill> now to complete the intended action?", header: "Retry", options: [{label: "Yes, invoke <skill> now (Recommended)", description: "Re-run the intended action via the correct skill"}, {label: "I'll invoke it manually later", description: "Skip for now — user will handle"}, {label: "Cancel — discard the attempted operation", description: "Do not retry"}], multiSelect: false}])`

Substitute `<recommended-skill>` with the skill identified in
Step 2 (e.g., `Dev10x:gh-pr-monitor`, `Dev10x:k8s`,
`Dev10x:git`).

**Skip this gate when:**

- The user invoked the skill informationally (not after a
  rejection) and no follow-up action is implied
- No recommended skill was identified (Step 3 fallback with
  no clear match) — ask the user what they expected instead
- The triggering command was approved, not rejected — the
  intended action has already run

On approval, invoke the recommended skill immediately. On
cancellation, acknowledge and stop — do NOT resume the
rejected workflow.

## Examples

See [`references/examples.md`](references/examples.md) for four
walkthroughs:

1. **kubectl usage** — direct CLI match (`Dev10x:k8s`)
2. **direct git push** — bypassed safety skill (`Dev10x:git`)
3. **friction from chaining** — Step 3b audit surfaces a
   pre-approved alternative
4. **no match found** — fallback to SKILLS.md scan
