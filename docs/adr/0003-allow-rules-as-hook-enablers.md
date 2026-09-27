# 3. Allow rules as hook enablers for SkillRedirectValidator commands

Date: 2026-03-24

## Status

Accepted

## Context

During a permission audit (2026-03-24), the `permission-auditor` agent
classified allow rules for hook-blocked commands as `DEAD_RULE` (MEDIUM
severity) and recommended removal. These rules include:

| Allow rule | Hook | Redirects to |
|-----------|------|-------------|
| `Bash(gh pr create:*)` | SkillRedirectValidator | `dev10x:gh-pr-create` |
| `Bash(git push:*)` | SkillRedirectValidator | `dev10x:git` |
| `Bash(git rebase -i:*)` | SkillRedirectValidator | `dev10x:git-groom` |
| `Bash(git commit -m:*)` | SkillRedirectValidator | `dev10x:git-commit` |

The auditor's reasoning: if a hook blocks the command, the allow rule
is dead code. This reasoning is incorrect because it ignores the
execution order of the permission layer.

### Permission Layer Execution Order

```
Agent requests Bash(command)
  │
  ├─ 1. Deny rules evaluated → if matched, BLOCKED (no hook runs)
  ├─ 2. Allow rules evaluated → if matched, ALLOWED silently
  ├─ 3. Ask rules evaluated   → if matched, user prompted
  ├─ 4. No rule matched       → generic permission prompt
  │
  └─ 5. PreToolUse hooks run  → can BLOCK with systemMessage
```

Hooks only execute AFTER the permission layer passes. Without an
allow rule, step 4 fires a generic permission prompt before the
hook ever runs. With the allow rule, step 2 passes silently, the
hook fires at step 5, and the user sees a contextual redirect
message explaining which skill to use and why.

## Decision

Keep allow rules for all SkillRedirectValidator-blocked commands.
Classify them as `HOOK_ENABLED`, not `DEAD_RULE`.

## Rationale

1. **Allow rules are hook enablers.** The permission layer runs
   before hooks. Without the allow rule, a generic "approve?"
   prompt fires first and the hook's educational redirect message
   never reaches the user.

2. **The redirect message has educational value.** It names the
   correct skill, explains which guardrails it enforces, and links
   to the issue tracker for bugs. A generic permission prompt
   provides none of this context.

3. **Removing the rule degrades UX.** The user sees "Allow
   `git push`?" instead of "Use `Skill(dev10x:git)` — it enforces
   protected branch checks and force-push safety." The former
   invites approval; the latter teaches the correct workflow.

4. **The pattern is intentional and documented.** The memory file
   `feedback_allow_rules_as_hook_enablers.md` already captures this
   as a user preference. This ADR formalizes it as architecture.

## Consequences

### Tools and processes that must be updated

| Component | Change |
|-----------|--------|
| `agents/permission-auditor.md` | Add `HOOK_ENABLED` classification to Phase 3 |
| `clean-project-files.py` | Detect hook-enabled rules and skip removal |
| `references/permission-architecture.md` | Document permission → hook execution order |

### Rules for future changes

- New SkillRedirectValidator entries require corresponding allow
  rules in `settings.json`
- Permission audits must classify hook-redirected allow rules as
  `HOOK_ENABLED`, not `DEAD_RULE`
- The `upgrade-cleanup` skill must not strip these rules

### When to revisit

- If Claude Code changes the permission → hook execution order
- If a new mechanism provides hook-like feedback at the permission
  layer (making the allow rule truly unnecessary)
- If SkillRedirectValidator is replaced with a different mechanism

## References

- [GH-419](https://github.com/Dev10x-Guru/dev10x-claude/issues/419)
- `hooks/scripts/bash_validators/skill_redirect.py` — the hook
- `feedback_allow_rules_as_hook_enablers.md` — original user feedback
- [ADR-0001](0001-trust-skill-instructions-for-destructive-git-commands.md) — related permission decision
