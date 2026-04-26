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

## References

- [ADR-0003](../docs/adr/0003-allow-rules-as-hook-enablers.md) — decision record
- `hooks/scripts/bash_validators/skill_redirect.py` — the hook implementation
- `agents/permission-auditor.md` — audit agent with `HOOK_ENABLED` classification
