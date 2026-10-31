# Step 4: Reinforcement Output Schema

Output a firm, concise reinforcement message with these sections.

## 1. Command detected

The CLI command that was identified in Step 1.

## 2. Use instead

Skill invocation name and one-line description (from Step 2 map
lookup or Step 3 SKILLS.md fallback).

## 3. Why

Reason from the map entry (if available).

## 4. How to invoke

`Skill("<skill-name>")` call syntax.

For MCP tools, add: "Call this as an MCP tool call, NOT as a
Bash command. MCP tool names are tool interface identifiers,
never shell executables. Example:
`mcp__plugin_dev10x_cli__mktmp(namespace='git',
prefix='commit-msg', ext='.txt')` — not
`mcp__plugin_dev10x_cli__mktmp git commit-msg .txt`."

## 5. Fix applied

From Step 3b audit and Step 3h. If a simpler form of the command
matches an existing allow-rule, show that form and the rule that
covers it. Otherwise name the friction class and the triage verdict,
then what was done:

- deliberate deny: the rule that holds, and that the human runs it;
- source / normalize: the rewrite, or the wrapper script / MCP tool
  proposed for a shape no rule can match;
- propagation gap: the backfill choice and its result;
- real gap: the rule `dev10x:permission-grant` wrote and the files
  it reported, or that the supervisor cancelled.

Never list a hand-picked settings file here; the grant skill computes
the targets. Omit this section when the audit found no friction (the
command was already simple and pre-approved, or no Bash command was
involved).

## 6. Upstream issue (optional)

From Step 3c. When the friction looks structural (no skill, no
safe local rule, or the hook itself is over-aggressive), include
a short problem statement plus a ready-to-run `gh issue create`
invocation targeting `Dev10x-Guru/Dev10x-Claude`. The user
approves before the issue is filed.

## 7. Related skills

From the map entry (if available).

## Ranking

If multiple skills could apply, list all of them ranked by
relevance.
