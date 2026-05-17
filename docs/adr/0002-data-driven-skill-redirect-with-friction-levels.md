# 2. Data-driven skill redirect with friction levels

Date: 2026-03-24

## Status

Proposed

## Context

The project has two overlapping mechanisms for redirecting agents from
raw CLI commands to skill wrappers:

1. **`skill_redirect.py`** — a PreToolUse:Bash hook validator that hard-blocks
   5 command patterns (`git commit -m`, `gh pr create`, `git push`,
   `git rebase -i`, `gh pr checks --watch`) and emits a systemMessage
   pointing to the correct skill.

2. **`Dev10x:diag-friction`** — a manually-invoked skill that reads
   `command-skill-map.yaml` (12 command families) and outputs a
   reinforcement message when the user notices the agent used CLI
   instead of a skill.

### Current State

- The hook uses hardcoded Python regexes for 5 patterns
- The skill reads a YAML map with 12 patterns
- 7 command families in the YAML map have no hook enforcement
  (kubectl, psql redirect, aws-vault, slack curl, playwright, pytest, sentry curl)
- The hook has a single enforcement mode: hard deny (exit 2)
- No way to configure enforcement strictness per-project or per-session

### Problems

1. **Drift between hook and skill** — the YAML map knows about more
   command-to-skill mappings than the hook enforces
2. **Single enforcement level** — hard-deny is too strict for some use
   cases (exploration, skill gaps, legitimate deviation) and users must
   Ctrl+C to bypass
3. **No graceful degradation** — when a skill wrapper fails (argument
   gap, MCP server down), the agent has no approved fallback path
4. **No learning loop** — when agents discover better command patterns,
   there's no mechanism to surface these for inclusion

## Decision

We will consolidate the hook validator and the skill reinforcement map
into a single data-driven system with three friction levels:
**strict**, **guided**, and **adaptive**.

### Architecture

The `command-skill-map.yaml` becomes the single source of truth for
both the PreToolUse hook and the diag-friction skill.

```
command-skill-map.yaml (single source of truth)
       │
       ├── skill_redirect.py (PreToolUse hook)
       │   └── reads YAML at import time, caches in module scope
       │       └── enforcement depends on friction_level config
       │
       └── Dev10x:diag-friction (manual skill)
           └── reads same YAML for pattern matching + message formatting
```

### Friction Levels

| Level | Hook behavior | Agent experience | User interruption |
|-------|--------------|------------------|-------------------|
| **strict** | `exit 2` (hard deny) | Must find approved path. No fallback. | Never — agent resolves autonomously |
| **guided** | `exit 2` + fallback instructions in systemMessage | Blocked, but given manual guardrails to apply if skill fails | Only when skill fails repeatedly |
| **adaptive** | `exit 0` + warning in additionalContext | Allowed, but pattern logged and flagged for learning | When agent proposes adding a new pattern |

Configuration is per-project via the YAML file's `config` section:

```yaml
config:
  friction_level: guided  # strict | guided | adaptive
```

Default: `guided` (balances enforcement with practical flexibility).

### YAML Schema

```yaml
config:
  friction_level: guided

mappings:
  - skill: Dev10x:git-commit
    description: Properly formatted git commit with gitmoji and ticket reference
    patterns:
      - "git commit"
    hook_block: true
    hook_except:
      - "--fixup"
      - "--amend"
      - "-F "
    reason: >
      Direct git commit bypasses gitmoji prefix, ticket ID
      extraction, and 72-char line limit enforcement.
    guardrails: gitmoji prefix, JTBD outcome title, 72-char limit
    fallback_instructions: >
      If Skill(Dev10x:git-commit) fails, apply these guardrails
      manually: (1) use gitmoji prefix, (2) include ticket ID from
      branch name, (3) keep title under 72 chars, (4) use -F flag
      with temp file, not -m.
    related:
      - Dev10x:git-groom
```

New fields vs current `command-skill-map.yaml`:
- `hook_block` — whether the hook should enforce this pattern (default: false)
- `hook_except` — substrings that exempt a command from blocking
- `guardrails` — what the skill enforces (shown in block message)
- `fallback_instructions` — manual workaround when skill fails (guided mode only)

### Key Flows

#### Flow 1: Strict mode — agent uses raw git commit

1. Agent calls `Bash(git commit -m "Add feature")`
2. PreToolUse hook fires, `skill_redirect.py` loads YAML
3. Pattern matches `git commit`, `hook_block: true`
4. Friction level = `strict` → hard deny (exit 2)
5. systemMessage: "Use Skill(Dev10x:git-commit) instead"
6. Agent retries with `Skill(Dev10x:git-commit)`

#### Flow 2: Guided mode — skill fails

1. Agent calls `Bash(git commit -m "Add feature")`
2. Hook blocks → agent tries `Skill(Dev10x:git-commit)`
3. Skill fails (e.g., MCP server timeout)
4. Agent retries raw command → hook blocks again
5. This time systemMessage includes `fallback_instructions`
6. Agent applies manual guardrails: gitmoji, ticket ID, -F flag
7. Raw command with -F flag passes (matches `hook_except`)

#### Flow 3: Adaptive mode — new pattern discovered

1. Agent calls `Bash(gh api graphql -f query=...)`
2. Hook finds no matching pattern
3. Hook logs the command to `~/.claude/projects/_metrics/unmatched-commands.jsonl`
4. additionalContext: "New CLI pattern detected. No skill match.
   Consider whether a skill should cover this."
5. Agent continues — command is not blocked
6. End of session: skill-audit can review unmatched patterns

### New Components

| Component | Location | Responsibility |
|-----------|----------|----------------|
| `command-skill-map.yaml` (enriched) | `hooks/scripts/bash_validators/command-skill-map.yaml` | Single source of truth for all command-to-skill mappings |
| `skill_redirect.py` (refactored) | `hooks/scripts/bash_validators/skill_redirect.py` | Data-driven validator loading YAML instead of hardcoded regexes |

### Dependencies (Reused Components)

| Component | Location | How We Use It |
|-----------|----------|---------------|
| `Validator` protocol | `hooks/scripts/bash_validators/_base.py` | SkillRedirectValidator implements this |
| `HookInput`, `HookResult` | `hooks/scripts/bash_validators/_types.py` | Standard hook I/O types |
| `Dev10x:diag-friction` | `skills/diag-friction/` | Reads same YAML for manual reinforcement |

## Alternatives Considered

### Alternative 1: Keep hook and skill separate (status quo)

Maintain hardcoded Python regexes in the hook and separate YAML
map in the skill. Manually sync new patterns to both.

**Pros:**
- No migration effort
- Hook stays fast (no YAML parsing)

**Cons:**
- Drift is inevitable (already 7 patterns out of sync)
- Two places to update when adding patterns
- No friction level support

**Verdict:** Rejected — drift already exists and will worsen.

### Alternative 2: Hook generates YAML (hook-authoritative)

Hook stays hardcoded. Build script exports patterns to YAML
for the skill.

**Pros:**
- Hook stays fast
- Single direction of truth

**Cons:**
- Generated files go stale between builds
- Build step adds complexity
- Still no friction levels

**Verdict:** Rejected — adds build complexity without solving
the friction level problem.

### Alternative 3: Kill the skill, hook does everything

Hook outputs both blocking decision and reinforcement message.
Remove the skill entirely.

**Pros:**
- Simplest architecture
- No coordination needed

**Cons:**
- Loses manual "use the skills" use case
- Hook systemMessage is less rich than skill output
- No way to invoke reinforcement without triggering a block

**Verdict:** Rejected — the manual skill serves a different purpose.

### Alternative 4: Data-driven hook with friction levels (selected)

Consolidate into YAML with configurable enforcement levels.

**Pros:**
- Single source of truth — no drift
- Three friction levels for different contexts
- Graceful degradation via fallback instructions
- Learning loop via adaptive mode
- Users can add patterns without touching Python

**Cons:**
- YAML parsing adds ~5-10ms to hook startup (cached after first call)
- More complex YAML schema
- Need migration from hardcoded regexes

**Verdict:** Selected — solves all identified problems.

## Consequences

### What Becomes Easier

1. Adding new command-to-skill redirects (YAML edit, no Python)
2. Per-project enforcement tuning (change one config field)
3. Graceful handling of skill wrapper failures (guided mode)
4. Discovering useful new CLI patterns (adaptive mode)

### What Becomes More Difficult

1. Understanding hook behavior requires reading YAML + Python
2. YAML schema must be documented and validated
3. Testing requires YAML fixtures in addition to Python unit tests

### Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| YAML parsing slows hook | Low | Low (cached) | Module-level cache, lazy load |
| YAML schema drift | Medium | Medium | Schema validation in tests |
| Guided fallback used as excuse to skip skills | Low | Medium | Fallback instructions still require guardrails |
| Adaptive mode floods logs | Low | Low | Rate limit + daily rotation |

### When to revisit

- If YAML parsing latency exceeds 20ms in production
- If teams need per-mapping friction levels (not just global)
- If adaptive mode discovers patterns worth converting to skills

## Implementation Plan

### Phase 1: Consolidate YAML

1. Enrich `command-skill-map.yaml` with `hook_block`, `hook_except`,
   `guardrails`, `fallback_instructions` fields for all 12 mappings
2. Move YAML to `hooks/scripts/bash_validators/command-skill-map.yaml`
3. Add symlink or path constant for diag-friction to find it

### Phase 2: Refactor hook

1. Refactor `skill_redirect.py` to load YAML at module level
2. Replace hardcoded regexes with YAML pattern matching
3. Implement `strict` mode (equivalent to current behavior)
4. Add tests for YAML-driven pattern matching

### Phase 3: Add friction levels

1. Implement `guided` mode with fallback instructions
2. Implement `adaptive` mode with logging + warning
3. Add `config.friction_level` to YAML schema
4. Add per-project override support (user override YAML)

### Phase 4: Migration

1. Update `Dev10x:diag-friction` to read from new location
2. Remove hardcoded patterns from old skill YAML
3. Update documentation and rules files

## References

### Internal References

- [GH-417](https://github.com/Dev10x-Guru/dev10x-claude/issues/417) — Spike: investigate hooks usage
- `hooks/scripts/bash_validators/skill_redirect.py` — current hook
- `skills/diag-friction/references/command-skill-map.yaml` — current YAML map
- [ADR-0001](0001-trust-skill-instructions-for-destructive-git-commands.md) — related decision on hook enforcement scope
