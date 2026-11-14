# Deny Rule Gap Analysis: Destructive Operations Matrix

Reference material for the `permission-auditor` agent — Phase 5.
The agent spec links here for the inventory of hook/skill
coverage, the per-operation classification matrix, and the
classification key.

## Step 1: Inventory hook and skill coverage

Read the plugin's hook files — `hooks/hooks.json` plus every file
`plugin.json` lists under `"hooks"` (such as `hooks/hooks.d/*.json`) —
and each hook script to build a coverage map. Also inventory skills that legitimately need
dangerous-looking operations (e.g., `dev10x:git` needs
force-push, `update-config` needs settings writes,
`dev10x:gh-pr-monitor` needs `gh pr merge`).

## Step 2: Classify each destructive operation

| Operation | Recommendation | Rationale |
|-----------|---------------|-----------|
| `git reset --hard` | **skip** | Skills use for rebase recovery in worktrees (SKILL_REQUIRED) |
| `git checkout .` / `git restore .` | **ask** | Dangerous but not never-legitimate |
| `git clean` | **ask** | Rarely legitimate, but not never |
| `git push --force` (bare) | **skip** | `push_safe` (GH-1031) rails protected branches at the wrapper layer; an ask rule duplicates that guard and prompts on every routine groom (GH-1053) |
| `git push --force-with-lease` | **skip** | Legitimately used by skills |
| `git branch -D` / `-d` / `--delete` | **skip** | Removes a ref, not history — reflog restores the tip. Unattended cleanup must never wedge on a prompt (GH-1067) |
| `git checkout` / `git stash drop` | **skip** | Routine branch and stash handling; the supervisor keeps them allowed (GH-1868) |
| Settings file writes | **skip** | `update-config`/`upgrade-cleanup` need this |
| Hook/plugin file writes | **skip** | `update-config` needs this |
| `rm -rf` on non-temp paths (incl. `/`, `~`) | **ask** | No skill needs it, but the supervisor wants to be able to run it with a question, not be blocked (GH-1868) |
| `helmfile apply` / `sync` / `destroy` / `delete` | **ask** | Infra changes a human may approve in the moment (GH-1868) |
| `sudo apt remove` / `purge` / `autoremove` | **ask** | Package removal is re-installable (GH-1868) |
| `gh repo delete` | **deny** | Irreversible and never part of a session's work |
| Direct database writes | **deny** if not hook-protected | Check if `sql_safety.py` covers it |
| `gh pr merge/close` | **skip** | Skills handle with safety gates |

## Step 3: Copying global rules into a project file

Claude Code does not reliably merge `~/.claude/settings.json` into a
project that has its own `settings.local.json` (GH-47), so a global
deny can be absent where it matters. When proposing to copy one:

1. Re-classify it with the matrix above — the global file's choice is
   not the recommendation. A global deny on an **ask** operation is
   copied as ask; one on a **skip** operation is not copied at all.
2. Never propose a deny or ask for `git push --force` / `-f` — the
   accepted-findings catalog (GH-1053) covers that family, and adding
   a gate is the same re-proposal as removing the allow.
3. Every copied rule is decided on its own: one finding per rule, or
   one `add` finding listing them all in `proposed_fix.rules` — never a
   family named only in `note` (`finding-schema.md` § Multi-rule
   findings).

## Step 4: Narrow-ask shapes for popular broad allows

Some broad allows are worth keeping because almost every use is safe.
Do not propose removing or narrowing them; propose keeping the allow and
adding an ask on the dangerous form only:

| Allow kept | Ask added | Dangerous form |
|------------|-----------|----------------|
| `Bash(awk:*)` | `Bash(awk *system*)`, `Bash(awk *getline*)`, `Bash(awk *\| "*)` | awk runs a shell command |
| `Bash(find:*)` | `Bash(find * -delete*)` | find deletes what it matched |

An ask rule wins over a matching allow, so the common forms keep
running unprompted. Over-matching (`system` inside a string literal)
costs one extra prompt, which is the right side to err on.

## Classification Key

- **deny** — Should NEVER succeed. No skill needs it, no hook
  covers it.
- **ask** — Dangerous but sometimes legitimate. User prompted
  each time.
- **hook-protected** — A PreToolUse hook validates contextually.
  Recommend keeping the hook, not adding a redundant rule.
- **skip** — Covered by skill safety logic. Do not recommend
  any rule.
