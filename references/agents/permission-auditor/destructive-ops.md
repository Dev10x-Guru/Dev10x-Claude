# Deny Rule Gap Analysis: Destructive Operations Matrix

Reference material for the `permission-auditor` agent — Phase 5.
The agent spec links here for the inventory of hook/skill
coverage, the per-operation classification matrix, and the
classification key.

## Step 1: Inventory hook and skill coverage

Read the plugin's `hooks.json` and each hook script to build a
coverage map. Also inventory skills that legitimately need
dangerous-looking operations (e.g., `Dev10x:git` needs
force-push, `update-config` needs settings writes,
`Dev10x:gh-pr-monitor` needs `gh pr merge`).

## Step 2: Classify each destructive operation

| Operation | Recommendation | Rationale |
|-----------|---------------|-----------|
| `git reset --hard` | **skip** | Skills use for rebase recovery in worktrees (SKILL_REQUIRED) |
| `git checkout .` / `git restore .` | **ask** | Dangerous but not never-legitimate |
| `git clean` | **ask** | Rarely legitimate, but not never |
| `git push --force` (bare) | **skip** | `push_safe` (GH-1031) rails protected branches at the wrapper layer; an ask rule duplicates that guard and prompts on every routine groom (GH-1053) |
| `git push --force-with-lease` | **skip** | Legitimately used by skills |
| `git branch -D` / `-d` / `--delete` | **skip** | Removes a ref, not history — reflog restores the tip. Unattended cleanup must never wedge on a prompt (GH-1067) |
| Settings file writes | **skip** | `update-config`/`upgrade-cleanup` need this |
| Hook/plugin file writes | **skip** | `update-config` needs this |
| `rm -rf` on non-temp paths | **deny** | No legitimate skill usage |
| Direct database writes | **deny** if not hook-protected | Check if `sql_safety.py` covers it |
| `gh pr merge/close` | **skip** | Skills handle with safety gates |

## Classification Key

- **deny** — Should NEVER succeed. No skill needs it, no hook
  covers it.
- **ask** — Dangerous but sometimes legitimate. User prompted
  each time.
- **hook-protected** — A PreToolUse hook validates contextually.
  Recommend keeping the hook, not adding a redundant rule.
- **skip** — Covered by skill safety logic. Do not recommend
  any rule.
