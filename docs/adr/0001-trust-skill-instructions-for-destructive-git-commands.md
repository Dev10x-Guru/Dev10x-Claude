# 1. Trust skill instructions for destructive git commands

Date: 2026-03-18

## Status

Accepted

## Context

A permission audit of Claude Code `settings.local.json` revealed that
the `dev10x:git-groom` and `dev10x:git-commit-split` skills use
destructive git commands (`git rebase -i`, `git reset --soft/--hard`,
`git restore`) that could be wrapped in scripts and blocked at the
hook/deny-rule level for all other contexts.

### Current State

Broad allow rules permit destructive git commands for any context,
not just the skills that need them.

### Problems

1. Destructive git commands are available to all skill contexts
2. No wrapper scripts enforce skill-specific guardrails
3. Potential for agent misuse outside supervised skill invocations

## Decision

We will trust skill instructions for safety of locally-destructive
git commands rather than wrapping them in scripts with deny rules.

### What was considered

**Option A — Block + Wrap:** Deny `git rebase -i`, `git reset`,
`git restore` in `settings.local.json`. Create wrapper scripts for
each command. Allow only the script paths in permissions.

**Option B — Trust skill instructions (chosen):** Keep the current
broad allow rules. Rely on the skill's documented workflow context
(reflog checkpoints, abort guidance, `GIT_EDITOR=true`) for safety.

### Why Option B

1. **Force-push is already wrapped.** The highest-risk operation
   (`git push --force`) is handled by `git-push-safe.sh`, which
   blocks bare `--force`/`-f` and only allows `--force-with-lease`.
   This is the only truly irreversible destructive git operation.

2. **Local destructive commands are recoverable.** `git reset`,
   `git rebase -i`, and `git restore` all operate on local state.
   Recovery is always possible via `git reflog` + `git reset --hard
   HEAD@{n}`. The groom skill already documents this recovery path.

3. **Wrapper coupling creates maintenance burden.** Each new
   destructive command used by the skill would need a corresponding
   wrapper script + deny rule + allow rule for the script path. When
   the skill evolves (e.g., adding a new strategy that uses
   `git cherry-pick --abort`), the permissions must be updated in
   sync. This coupling is fragile.

4. **The groom skill is user-initiated.** It's invoked deliberately
   via `/dev10x:git-groom`, not autonomously by an agent. The user
   is already in a supervised context when these commands run.

5. **The skill already has safety mechanisms:**
   - `GIT_SEQUENCE_EDITOR=true` suppresses interactive prompts
   - `mass-rewrite.py` validates SHAs before executing rewrites
   - Recovery guidance (reflog, `rebase --abort`) is built into
     the skill's instructions
   - The `git-rebase-groom.sh` wrapper validates the base ref

### Commands covered by this decision

| Command | Used by | Purpose |
|---------|---------|---------|
| `git rebase -i` | git-groom (strategies A, C, D) | Commit restructuring |
| `git reset --soft` | git-groom (strategy B) | Full branch restructure |
| `git reset HEAD` | git-groom | Unstaging during splits |
| `git reset HEAD^` | git-groom | Undoing commits during splits |
| `git reset --hard HEAD@{n}` | git-groom | Recovery after failed rewrite |
| `git restore` | Not used by groom | Kept allowed for manual use |
| `git push --force-with-lease` | git (push-safe wrapper) | Already wrapped and guarded |

### What IS blocked

These deny rules remain active and are not affected by this decision:

- `git reset --hard` (broad) — only recovery via `HEAD@{n}` is used
- `git checkout .` / `git checkout --` — bulk discard
- `git restore .` / `git restore --staged .` — bulk discard
- `git clean` — untracked file deletion
- `git branch -D` / `git branch -d` — branch deletion

## Alternatives Considered

### Alternative 1: Block + Wrap (Option A)

Deny destructive git commands globally. Create wrapper scripts that
enforce skill-specific guardrails. Allow only script paths.

**Pros:**
- Eliminates all use of destructive commands outside wrappers
- Defense-in-depth: skill misuse blocked at permission layer

**Cons:**
- High maintenance burden: each new command needs wrapper + rules
- Fragile coupling between skill evolution and permission config
- Local operations are already recoverable via reflog
- Adds complexity without addressing the only irreversible
  operation (force-push, which is already wrapped)

**Verdict:** Rejected — maintenance cost exceeds security benefit
for locally-recoverable operations.

### Alternative 2: Trust skill instructions (Option B)

Keep broad allow rules. Rely on skill documentation, reflog
checkpoints, and existing wrapper for force-push.

**Pros:**
- Zero maintenance overhead for new skill commands
- Force-push (only irreversible op) already guarded
- Skills have built-in safety mechanisms
- User-initiated context provides supervision

**Cons:**
- Relies on agent following skill instructions correctly
- No defense-in-depth for local destructive commands

**Verdict:** Selected

## Consequences

### What Becomes Easier

1. Skills can evolve freely without permission config changes
2. No wrapper scripts to maintain in sync with skill commands

### What Becomes More Difficult

1. Auditing which contexts use destructive commands requires
   reading skill definitions rather than permission config

### Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Agent misuses allowed destructive command | Low | Low (recoverable via reflog) | Skill instructions + user supervision |
| New skill needs destructive commands | Medium | None | Allow rules already cover common commands |

### When to revisit

- If agents start invoking groom-style commands autonomously
  (outside user-initiated skill invocations)
- If a new skill needs destructive git commands in an unattended
  context (e.g., CI pipeline, background agent)
- If a security incident traces back to an agent misusing an
  allowed destructive command

## References

### Related fixes from same audit session

- **Critical:** Added deny rules for `Write/Edit` on `CLAUDE.md`,
  `SKILLS.md`, and `plugins/**` to prevent agent self-modification
  of instructions and security hooks
- **Medium:** Removed `Bash(fish:*)` allow rule (shell escape that
  bypasses all Bash-level hooks)
- **Medium:** Removed 4x dead `python3 ~/.claude/skills` allow rules
  (redundant with hook enforcement)

### Internal References

- [GH-269](https://github.com/Dev10x-Guru/dev10x-claude/issues/269)
- `skills/git-groom/` — primary consumer of destructive git commands
- `skills/git-commit-split/` — secondary consumer
- `skills/git/scripts/git-push-safe.sh` — force-push wrapper
