---
name: Dev10x:diag-friction
description: >
  Diagnose permission friction. Guide the agent toward pre-approved
  commands, simplify complex command chains, and (when no safe local
  rule fits) file an upstream issue to improve the permission
  friction hooks. Replaces the former Dev10x:skill-reinforcement
  skill — reinforcement of skill usage is still part of the job,
  but the broader goal is reducing the friction supervisors see.
  Reads conversation context to identify the offending command,
  matches it against a command-to-skill map, audits local + global
  settings for simpler pre-approved forms, and outputs a firm
  reinforcement message pointing to the correct skill or pre-approved
  command.
  TRIGGER when: user sees agent using CLI instead of a skill, user
  rejects a command that should have been a skill, supervisor is
  bothered by repeated permission prompts, or user says "use the
  skills" / "diag friction" / "skill reinforcement".
  DO NOT TRIGGER when: agent is already using skills correctly,
  or the CLI command has no skill equivalent and no friction is
  observed.
user-invocable: true
invocation-name: Dev10x:diag-friction
allowed-tools:
  - AskUserQuestion
  - Read(~/.claude/SKILLS.md)
  - Read(~/.claude/settings.json)
  - Read(~/.claude/settings.local.json)
  - Read(.claude/settings.json)
  - Read(.claude/settings.local.json)
  - Read(${CLAUDE_PLUGIN_ROOT}/skills/diag-friction/references/*)
  - Read(${CLAUDE_PLUGIN_ROOT}/src/dev10x/validators/command-skill-map.yaml)
---

# Dev10x:diag-friction

Diagnose and reduce permission friction. Guides the agent toward
pre-approved commands, simplifies command chains that defeat
allow-rule matching, and points to upstream issue filing when the
friction is structural (the hook itself needs updating).

> Formerly `Dev10x:skill-reinforcement`. The skill-reinforcement
> behavior (firm nudge toward the right Dev10x skill or MCP tool)
> is still core to this skill — it is one slice of the broader job
> of diagnosing why the supervisor saw a permission prompt in the
> first place. If you're looking for the old `skill-reinforcement`
> invocation, you're in the right place.

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
- If the user provided arguments (e.g., `/Dev10x:diag-friction kubectl`),
  use that as the command identifier

Store the command string for matching.

### Step 2: Match against command-skill map

**REQUIRED — `Read` the canonical map first (GH-181 F9).** Do
NOT inline knowledge from the parent skill's SKILL.md or
recall mappings from training. The hook's YAML is authoritative
and ships updates ahead of skill docs; skipping the Read is a
documented Step 2 violation.

1. `Read(file_path="${CLAUDE_PLUGIN_ROOT}/src/dev10x/validators/command-skill-map.yaml")`

The YAML in `skills/diag-friction/references/command-skill-map.yaml`
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

Audit project + user settings for a simpler, pre-approved
alternative to the offending command. Most rejections happen
because chaining shifts the effective prefix away from any
allow-rule.

See [`references/audit-procedure.md`](references/audit-procedure.md)
for sources, allow-rule shapes, and the four-step audit procedure.
The audit output feeds Step 4 — surface findings even when a
skill match was also found.

### Step 3c: Detect structural friction (file upstream)

When the hook itself is too aggressive, the command-skill map is
missing an entry, or no safe targeted allow-rule fits, point the
user at the upstream issue tracker so the hooks can be improved
for everyone — not patched locally over and over.

See [`references/upstream-friction.md`](references/upstream-friction.md)
for the signals that suggest structural friction and the
"Upstream issue" section template (problem statement, suggested
resolution, pre-filled `gh issue create` invocation). Do NOT
auto-file — the user approves first.

### Step 4: Output reinforcement message

Output a firm, concise reinforcement message with seven sections:
command detected, use instead, why, how to invoke, pre-approved
alternatives (from Step 3b), upstream issue (from Step 3c when
friction is structural), related skills.

See [`references/audit-output.md`](references/audit-output.md)
for the per-section schema, MCP invocation example, and ranking
rules when multiple skills apply.

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

See [`references/examples.md`](references/examples.md) for five
walkthroughs:

1. **kubectl usage** — direct CLI match (`Dev10x:k8s`)
2. **direct git push** — bypassed safety skill (`Dev10x:git`)
3. **friction from chaining** — Step 3b audit surfaces a
   pre-approved alternative
4. **no match found** — fallback to SKILLS.md scan
5. **structural friction** — no safe local rule fits, file an
   upstream issue
