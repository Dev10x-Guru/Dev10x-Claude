---
name: dev10x:diag-friction
description: >
  Diagnose permission friction and end in a fix: a rewrite, a
  wrapper, a backfill, or a pre-approval written everywhere through
  dev10x:permission-grant, so the same prompt does not come back next
  session. Guides the agent toward pre-approved commands, simplifies
  complex command chains, and (when no safe local rule fits) files an
  upstream issue to improve the permission friction hooks. Replaces the former dev10x:skill-reinforcement
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
invocation-name: dev10x:diag-friction
allowed-tools:
  - AskUserQuestion
  - Read(~/.claude/SKILLS.md)
  - Read(~/.claude/settings.json)
  - Read(~/.claude/settings.local.json)
  - Read(.claude/settings.json)
  - Read(.claude/settings.local.json)
  - Read(${CLAUDE_PLUGIN_ROOT}/skills/diag-friction/references/*)
  - Read(${CLAUDE_PLUGIN_ROOT}/src/dev10x/core/validators/command-skill-map.yaml)
  - Read(${CLAUDE_PLUGIN_ROOT}/src/dev10x/core/validators/command-skill-map.d/*)
  - Glob
  - Bash(uvx dev10x permission catalog-gap:*)
  - Bash(dev10x permission catalog-gap:*)
  - Bash(uvx dev10x permission ensure-base:*)
  - Bash(dev10x permission ensure-base:*)
  - Bash(uvx dev10x permission seed-worktree:*)
  - Bash(dev10x permission seed-worktree:*)
  - mcp__plugin_dev10x_cli__audit_analyze_permissions
  - mcp__plugin_dev10x_cli__background_preamble
  - mcp__plugin_dev10x_cli__permission_catalog_gap
  - mcp__plugin_dev10x_cli__permission_triage
  - Skill(dev10x:permission-grant)
---

# dev10x:diag-friction

Diagnose and remove permission friction. Guides the agent toward
pre-approved commands, simplifies command chains that defeat
allow-rule matching, and points to upstream issue filing when the
friction is structural (the hook itself needs updating). The skill
ends in a fix (Step 3h), not a coaching note: a reinforcement alone
leaves the same prompt waiting for the next session (GH-1669).
Formerly `dev10x:skill-reinforcement`.

> **[OVERRIDE DETECTED]** — over the 200-line SKILL.md budget
> (GH-1727). Step procedures live in `references/` (`step-details.md`,
> `audit-procedure.md`, `fix-routing.md`, …); what remains is
> execution-gating and must stay inline: the Step 2 map-read mandate,
> the Step 3a backfill gate, the Step 3h triage routing table, and the
> Step 6 retry gate. **Split plan:** if it grows past ~400 lines, move
> Steps 4–5 (output shape and closing principle) into
> `references/audit-output.md` and keep only the section list.

## When to Use

Invoke this skill when:
- The agent ran a CLI command that a skill already handles
- You rejected a command and want the agent to use a skill instead
- You approved a command but want to reinforce the skill habit
- You want to say "use the skills" with a structured response

## Orchestration

**REQUIRED: Create a task at invocation.** Execute at startup:

1. `TaskCreate(subject="Diagnose and fix permission friction", activeForm="Fixing friction")`

Mark completed when done: `TaskUpdate(taskId, status="completed")`

## Instructions

### Step 1: Identify the offending command

Scan the recent conversation for the CLI command that triggered
this invocation. Look for:
- The most recent `Bash` tool call that was rejected or approved
- Any command the user flagged as wrong
- If the user provided arguments (e.g., `/dev10x:diag-friction kubectl`),
  use that as the command identifier

Store the command string for matching.

### Step 2: Match against command-skill map

**REQUIRED — `Read` the canonical map first (GH-181 F9).** Do
NOT inline knowledge from the parent skill's SKILL.md or
recall mappings from training. The hook's YAML is authoritative
and ships updates ahead of skill docs; skipping the Read is a
documented Step 2 violation.

1. `Read(file_path="${CLAUDE_PLUGIN_ROOT}/src/dev10x/core/validators/command-skill-map.yaml")`
2. `Glob(pattern="*.yaml", path="${CLAUDE_PLUGIN_ROOT}/src/dev10x/core/validators/command-skill-map.d")`,
   then `Read` every file it lists.

The map is split into per-plugin fragments (ADR-0034 Stage A3): the
base file holds the core rules and `command-skill-map.d/<plugin>.yaml`
holds the rest. The hook evaluates the base rules first, then each
fragment in `src/dev10x/core/plugins.yaml` order (`core`, then `qa`,
`infra`, `db`, `comm`, `teach`, `tasks`, `scoping`, `coding`); the
first matching rule wins. Reading only the base file misses most
rules.

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
  through `dev10x:gh-pr-fixup` — using the raw API is a violation

If the command is a delegation bypass, treat it as a match and
output the reinforcement pointing to the correct sub-skill.

### Step 3: Fall back to SKILLS.md

If no direct mapping exists, read `~/.claude/SKILLS.md` and scan
skill descriptions from the system-reminder context to find the
best match based on the command's purpose.

### Step 3a: Effective-file coverage (GH-1139)

**Run this BEFORE the shape audit.** The most common cause of a
prompt on a seeded machine is a rule that is in the catalog but not
in the file the engine reads (GH-1136). Resolve the effective
settings file, then call
`mcp__plugin_dev10x_cli__permission_catalog_gap()`. When the
command's generalized rule (Step 3d) is catalogued but missing from
the effective file, report a **propagation gap** first. The
procedure, the Bash fallback and the three-outcome routing table
are in
[`references/step-details.md`](references/step-details.md)
§ Step 3a.

**Backfill proposal gate — REQUIRED: Call `AskUserQuestion`** (do
NOT use plain text) whenever the gap is non-empty. Options:

- **Backfill this checkout (Recommended)** — run `ensure-base` /
  `seed-worktree` for this checkout only
- **Backfill every checkout under roots** — the full maintenance run
- **Report only** — write nothing

Never write without this gate, never write a git-tracked
`settings.json`, and always write through the backup + atomic path
(`ensure_base` already does both).

### Step 3b: Permission friction audit

Audit project + user settings for a simpler, pre-approved
alternative to the offending command. Most rejections happen
because chaining shifts the effective prefix away from any
allow-rule.

See [`references/audit-procedure.md`](references/audit-procedure.md)
for sources, allow-rule shapes, and the four-step audit procedure.
The audit output feeds Step 4 — surface findings even when a
skill match was also found.

### Step 3c-pre: Inline-code structured-alternatives (GH-282)

When the offending command starts with an inline-code prefix
(`python -c`, `python3 -c`, `sh -c`, `bash -c`, `perl -e`,
`ruby -e`, `node -e`, `deno eval`), the right recommendation is
almost never "extract to `~/.claude/tools/`" — it's the canonical
structured tool that already exists for the use case (jq, yq,
yamllint, actionlint, curl, etc.). Match the inline body against
`references/structured-alternatives.yaml`; the procedure is in
[`references/step-details.md`](references/step-details.md)
§ Step 3c-pre.

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

### Step 3d: Generalize the suggested rule shape (GH-597)

When the audit (Step 3b) or upstream path (Step 3c) lands on
proposing a **targeted allow-rule**, do not echo the harness's
suggested shape — it is over-broad, over-narrow or too literal.
Surface the shape from
`dev10x.skills.permission.generalize.generalize_rule_shape`. The
failure-mode table is in
[`references/step-details.md`](references/step-details.md)
§ Step 3d.

### Step 3e: Background-dispatch pre-seed over auto-mode (GH-610)

When the friction arose inside a **background subagent** (workflow /
monitor / loop / fanout child) — or the only "fix" on offer is the
harness's "switch to auto mode" / disable-prompts nudge (the GH-310
footgun) — do NOT recommend blanket `bypassPermissions`. Fix the
**dispatcher**: preamble, pre-seeded `allowed_tools`, and a
`dev10x:permission-grant` write when triage says `grant`. Surface it
as the primary recommendation; steps in
[`references/step-details.md`](references/step-details.md)
§ Step 3e.

### Step 3g: Check the recommended tool exists here (GH-1087)

Before recommending a `use-tool` compensation, confirm the named tool
is in this session's tool surface (listed, or loadable via
`ToolSearch`). If it is absent, recommend the compensation's
`fallback:` (for `find-search`, an `rg --files -g` shape), never the
offending command itself, and state the substitution you verified. See
[`references/tool-presence.md`](references/tool-presence.md).

### Step 3f: Approved in-session, denied by a rule (GH-972)

When an `AskUserQuestion` gate returned "yes" and the command was
STILL refused, the two authorities disagree by design: the gate
grants intent, a `deny` rule governs the shape. Do NOT search for
an alternative spelling — the nearest ones (`git restore`,
`git stash` for a denied `git checkout --`) defeat the rail's whole
purpose. Hand the exact command to the human to run, and continue
with what the denial does not block.

See
[`references/deny-rail-vs-approval-gate.md`](references/deny-rail-vs-approval-gate.md)
for the full procedure, the substitution anti-patterns, and the
unattended-run variant.

### Step 3h: Classify and fix (GH-1669)

**REQUIRED: triage before any grant.** Explaining the prompt is not
the goal; removing it is. Call, with the offending command verbatim
and every working directory as an absolute path:

1. `mcp__plugin_dev10x_cli__permission_triage(target=<command>, working_dirs=[...], cwd=<primary working dir>)`

Route on the verdict and the Step 3a outcome:

| Class | Signal | Fix |
|-------|--------|-----|
| Deliberate deny | `denied`, or Step 3f | Explain the rule; **never grant** (GH-972) |
| Propagation gap | Step 3a outcome (a) | Step 3a backfill gate |
| Source / normalize | `use-alternative`, `normalize`, `outside-workdir`, `too-broad`, `refuse-sensitive` | State the rewrite from `advice`; **no grant** |
| Real gap (plugin default or project-specific) | `grant` | `Skill(skill="dev10x:permission-grant", args="<command>")` |

When the shape can never match a rule (an env-var prefix plus a
redirect, as hooks emit: `VAR=… bash script.sh < payload.json`),
propose a wrapper script or an MCP tool instead of a rule.

`dev10x:permission-grant` owns the single gate that names every
target settings file and the fan-out write. Do not list files or
write settings here. See
[`references/fix-routing.md`](references/fix-routing.md) for the
full verdict table, the wrapper/MCP proposal, and the
background-dispatch variant.

### Step 4: Output reinforcement message

Output a firm, concise reinforcement message with seven sections:
command detected, use instead, why, how to invoke, fix applied
(from Step 3h: class, triage verdict, and what was rewritten or
granted), upstream issue (from Step 3c when friction is
structural), related skills.

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

### Step 6: Retry to verify the fix (REQUIRED when command was rejected)

The retry runs **after** Step 3h has written its fix, and it is the
verification of that fix, not a substitute for it. After a grant,
retry the original command; after a rewrite, retry via the new form
or skill. Settings are read at session start, so a grant may still
prompt in this session; say so rather than reporting failure. After
a deliberate deny there is no retry: the human runs the command.

If the triggering command was **rejected** by the user (denied
the Bash tool call), actively offer the retry. Plain text
offers ("Want me to invoke X?") do NOT block execution and break
the structured decision flow used across Dev10x skills.

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text).

1. `AskUserQuestion(questions=[{question: "Invoke <recommended-skill> now to complete the intended action?", header: "Retry", options: [{label: "Yes, invoke <skill> now (Recommended)", description: "Re-run the intended action via the correct skill"}, {label: "I'll invoke it manually later", description: "Skip for now — user will handle"}, {label: "Cancel — discard the attempted operation", description: "Do not retry"}], multiSelect: false}])`

Substitute `<recommended-skill>` with the skill identified in
Step 2 (e.g., `dev10x:gh-pr-monitor`, `dev10x:k8s`,
`dev10x:git`).

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

1. **kubectl usage** — direct CLI match (`dev10x:k8s`)
2. **direct git push** — bypassed safety skill (`dev10x:git`)
3. **friction from chaining** — Step 3b audit surfaces a
   pre-approved alternative
4. **no match found** — fallback to SKILLS.md scan
5. **structural friction** — no safe local rule fits, file an
   upstream issue
