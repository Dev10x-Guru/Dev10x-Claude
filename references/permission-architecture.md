# Permission Architecture

How Claude Code evaluates tool requests, and how hooks interact
with the permission layer.

## Execution Order

When an agent requests a tool call (e.g., `Bash(git push origin)`),
Claude Code processes it in this order:

```
Agent requests tool call
  │
  ├─ 1. Deny rules  → if matched, BLOCKED (hooks never run)
  ├─ 2. Allow rules  → if matched, ALLOWED silently
  ├─ 3. Ask rules    → if matched, user prompted
  ├─ 4. No rule match → generic permission prompt
  │
  └─ 5. PreToolUse hooks run (only if steps 1-4 allowed)
         └─ Hook can BLOCK with systemMessage
         └─ Hook can ALLOW (or not respond)
```

**Key insight:** Hooks only execute after the permission layer
passes. A deny rule prevents both the tool call AND the hook.
An allow rule silences the permission prompt AND enables the hook.

## Hook-Enabled Allow Rules

Some allow rules exist not to permit the command, but to ensure
a PreToolUse hook can fire its redirect message. Without the
allow rule, step 4 fires a generic "approve?" prompt before the
hook runs at step 5.

### SkillRedirectValidator

The `SkillRedirectValidator` hook blocks raw CLI commands and
redirects to skill equivalents with educational messages:

| Allow rule | Hook blocks | Redirects to | Guardrails |
|-----------|-------------|-------------|------------|
| `Bash(gh pr create:*)` | `gh pr create` | `Dev10x:gh-pr-create` | Job Story, ticket linking |
| `Bash(git push:*)` | `git push` | `Dev10x:git` | Protected branches, force-push safety |
| `Bash(git rebase -i:*)` | `git rebase -i` | `Dev10x:git-groom` | Atomic commits, conventions |
| `Bash(git commit -m:*)` | `git commit -m` | `Dev10x:git-commit` | Gitmoji, JTBD title, 72-char |
| `Bash(gh pr checks:*)` | `gh pr checks --watch` | `Dev10x:gh-pr-monitor` | Failure detection, fixups |

These allow rules are classified as `HOOK_ENABLED` in permission
audits. Removing them degrades UX — the user sees a generic
permission prompt instead of an educational redirect.

### Adding New Hook-Enabled Rules

When adding a new SkillRedirectValidator entry:

1. Add the regex pattern to `skill_redirect.py`
2. Add the corresponding allow rule to `settings.json`
3. Add the pattern to `HOOK_ENABLED_PATTERNS` in
   `clean-project-files.py` so it isn't stripped as redundant
4. Verify the redirect message fires correctly

## Implications for Tooling

| Tool | Implication |
|------|------------|
| `permission-auditor` agent | Must classify hook-enabled rules as `HOOK_ENABLED`, not `DEAD_RULE` |
| `clean-project-files.py` | Must detect and skip hook-enabled rules during cleanup |
| `plugin-maintenance` skill (invoked directly or via `upgrade-cleanup`) | Must not strip hook-enabled rules from project settings |

## Proactive Safe-Command Allowlist (GH-310)

An unsupervised (adaptive / AFK) session treats every permission
prompt as a **hard stop** — there is no human to answer it, so the
session cannot complete. The same prompt is also the trigger for
Claude Code's option-2 "Yes, and don't ask again for…" feature,
which strips a command down to its broadest prefix and writes a
catch-all `Bash(<verb> *)` rule into the user's allow list.

### Why deny rules cannot fix the footgun

A natural instinct is to ship `deny` rules for the catch-all shapes
(`Bash(git *)`, `Bash(gh *)`, …). This **backfires**. Claude Code
evaluates rules in the order `deny → ask → allow`, and the first
match wins, so a deny always beats a more-specific allow. The space
in `Bash(git *)` is a trailing wildcard equivalent to `:*`, so the
pattern matches **every** `git <args>` command. A `deny: Bash(git *)`
would therefore also block `git status`, `git log`, and every other
git subcommand — for every plugin user — even with
`allow: Bash(git status:*)` present.

Source: [Claude Code permissions docs](https://code.claude.com/docs/en/permissions.md)
— "Rules are evaluated `deny → ask → allow`; the first matching rule
wins" and "`Bash(git *)` matches `git log --oneline --all`".

### The fix: pre-approve the safe surface

The only safe defense is to **enumerate the safe commands as `allow`
rules** so the prompt never fires and option-2 never gets the chance
to write a catch-all. The catalog lives in
`skills/upgrade-cleanup/projects.yaml` under `base_permissions:` and
is propagated into each project's `settings.local.json` by
`uvx dev10x permission ensure-base`.

What belongs in the catalog (safe to auto-approve):

- Read-only filesystem / text inspection (`ls`, `cat`, `grep`, `rg`,
  `stat`, `wc`, `diff`, …) — never mutate state.
- `--version` / `--help` info flags for execution-capable verbs.
- Read-only subcommands of rich verbs (`git show`, `git rev-parse`,
  `gh release view`, `gh workflow list`, `uv pip list`, …).

What is deliberately excluded (keeps prompting, routes to a skill,
or is forbidden by a hook):

- Arbitrary code execution — `python -c`, `sh -c`, `bash -c`,
  `eval`, and package runners (`npx <pkg>`, `pnpm dlx <pkg>`,
  `pipx run <pkg>`, `bunx <pkg>`).
- Network fetch-and-exec or exfiltration — `curl <url>`,
  `wget <url>` (only `--version` is allowed).
- Destructive filesystem operations.
- Env-prefixed commands (`env VAR=x cmd`) — tracked under GH-311.
- The bare-verb catch-alls themselves (`Bash(git *)`, etc.).

The upstream UI defect that generates the catch-all is tracked
separately (GH-312); this allowlist is the defense-in-depth that
keeps unattended sessions moving without it.

## References

- [ADR-0003](../docs/adr/0003-allow-rules-as-hook-enablers.md) — decision record
- `hooks/scripts/bash_validators/skill_redirect.py` — the hook implementation
- `agents/permission-auditor.md` — audit agent with `HOOK_ENABLED` classification
