# Step 3b: Permission Friction Audit

Most rejections happen not because the command is wrong but because
the agent packed too much into a single Bash call and the resulting
prefix does not match any pre-approved allow-rule. Before producing
the final reinforcement, audit settings for a simpler, pre-approved
alternative.

## Sources

Read each; tolerate missing files:

- `.claude/settings.local.json` — project-local overrides
- `.claude/settings.json` — project shared
- `~/.claude/settings.json` — user global
- `~/.claude/settings.local.json` — user local

Parse `permissions.allow` from each.

## Allow-rule shapes to handle

- `Bash(<exact>)` — exact command match
- `Bash(<prefix>:*)` — prefix match
- `Read(<glob>)`, `Edit(<glob>)`, etc. — non-Bash tools

## Audit procedure

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
