# reviewer-skill — Checklist Detail

Depth for the checklist items in
[`.claude/agents/reviewer-skill.md`](../../../.claude/agents/reviewer-skill.md).
The spec carries the numbered items; this file carries what each means
in practice. Extracted under GH-1197: the spec's full body loads into
the dispatched session's system prompt on **every** dispatch, which is
what the 50-line budget in `.claude/rules/INDEX.md` bounds. This is the
spec's second split — it was cut at 187 lines into `reviewer-skill.md`
and `reviewer-skill-behavior.md`, then grew back to 145. Route new
depth here, not into the spec.

## 1. SKILL.md exists

Every skill directory must contain a `SKILL.md` with valid YAML front
matter. Required: `name:`, `description:`, `invocation-name:`.
Optional: `allowed-tools:`, `user-invocable:`.

## 2. Naming convention

Directory uses the plain name (no `dx-` prefix). `name:` MUST use the
`Dev10x:<feature>` format. `invocation-name:` MUST match `name:`
exactly — no shortened aliases, cross-family variants, or non-`Dev10x:`
prefixes. Both fields require the prefix; see
`.claude/rules/skill-naming.md` § `invocation-name` field.

## 3. Description quality

`description:` must explain *when* to trigger the skill — vague
descriptions reduce discoverability. **Required trigger suffix:** every
description ends with `TRIGGER when: [conditions]` and
`DO NOT TRIGGER when: [conditions]` lines. Flag a missing suffix as
WARNING (it degrades auto-discovery).

## 4. Script references

*Script-based skills only — skip for orchestration-based.*

SKILL.md-referenced scripts must exist in the directory. Check both
`allowed-tools` entries AND inline code blocks.

**Pattern detection**: see `.claude/rules/skill-patterns.md`. If the
skill directory contains NO `scripts/` subdirectory AND the SKILL.md
references no local paths (only `~/.claude/tools/` or external
binaries), it is orchestration-based and this item does not apply.

## 5. Executable permissions

Directly-invoked scripts must be executable.
`git ls-files --stage <path>` reporting mode `100644` means not
executable.

## 7. No hardcoded paths

Scripts use relative paths or environment variables, never absolute
user-specific paths. For external binaries (`yq`, `jq`, `gh`, …) the
preferred resolution pattern is
`TOOL="${TOOL:-$(command -v tool 2>/dev/null || echo "/fallback/path/tool")}"`.

## 8. `allowed-tools` coverage

If SKILL.md calls external scripts, front matter must declare matching
`Bash(...)` entries — missing entries cause per-invocation approval
prompts.

**Built-in tools** (`AskUserQuestion`, `TaskCreate`, `TaskUpdate`,
`Skill()`, `Read`, `Write`, `Edit`, `Glob`, `Grep`) are implicitly
available — do NOT flag them as missing. Only **MCP tools** and **Bash
script paths** require declaration.

### 8b. `allowed-tools` sync

When a PR adds `mktmp.sh <ns> ...` calls, verify BOTH entries:
`Bash(/tmp/Dev10x/bin/mktmp.sh:*)` AND `Write(/tmp/Dev10x/<ns>/**)`.
Missing either is a WARNING.

### 8b-ii. `allowed-tools` is not a grant (GH-1153)

Declaring an MCP tool here only *scopes* the skill; it pre-approves
nothing. When a PR adds a `mcp__plugin_Dev10x_*` entry, verify the tool
is also in `base_permissions`
(`skills/upgrade-cleanup/projects.yaml`) — otherwise the skill prompts
on every invocation. `triage_roster` shipped declared-but-un-catalogued
and prompted until GH-1153.

### 8c. Plugin directory existence

For every `${CLAUDE_PLUGIN_ROOT}/skills/<name>/` entry in
`allowed-tools`, verify `skills/<name>/` exists via
`Glob(skills/<name>/SKILL.md)`.

### 8d. Skill porting pattern

When a PR converts `~/.claude/skills/<name>/` to
`${CLAUDE_PLUGIN_ROOT}/skills/<name>/`, verify: (a) all scripts have
mode `100755`; (b) `allowed-tools:` covers every script invocation;
(c) no hardcoded absolute paths.

### 8e. Shared helper propagation

When a PR propagates a `bin/` helper, enumerate ALL changed SKILL.md
files and verify each has a matching
`Bash(${CLAUDE_PLUGIN_ROOT}/bin/<script>:*)` entry.

### 8f. Durable-pref write coverage

A skill that persists durable preferences must not use the Write tool
at all. Tier-2 config moved to `~/.config/Dev10x/` (GH-941) and the
per-repo `.claude/Dev10x/*.yaml` are retired (ADR-0018) — a Write under
a repo's `.claude/` also trips the self-settings consent gate no allow
rule suppresses. Flag a grant for either retired path; route the write
through the CLI/MCP writers (`dev10x session set-friction`,
`pin_gate_preset`, `pin_tracker`), which lock and write atomically. For
non-pref data under the config home, verify `allowed-tools:` carries
`Write(~/.config/Dev10x/**)`.

### 8g. Cross-skill delegation

When a skill delegates via `Skill()`: (a) the delegated skill's
`allowed-tools` includes `Read()` for findings; (b) both skills declare
a compatible temp namespace; (c) the findings file path is
deterministic (no session-unique UUIDs).

## 9. Template consistency

YAML code blocks containing a `name:` field must follow
`skill-naming.md`, not ad-hoc examples.

### 9a. Skill tool invocation syntax

`Skill()` calls must use named parameters:
`Skill(skill="Dev10x:target-name", args="...")`. See
`references/skill-invocation.md`.

## 10. Reference doc consistency

Cross-check `references/` documents against any matching
`.claude/rules/` file.

### 10b. Inline table consistency

Cross-check SKILL.md reference tables against the script
implementations; a mismatch is a bug signal.

## 11. Embedded templates

**Shell:** POSIX-compatible, no silent `|| true`, `<>` placeholder
markers for user-replaceable values. **11b Python:** must pass ruff
checks (F811, F541), use `os.environ[...]` for credentials, never
hardcoded values.

## 12. Self-contained content

No ephemeral references ("see Memory note", "as discussed") — all
constraints documented inline.

## 13. Bundled binaries

If `skills/<name>/bin/` contains a non-script binary, verify licence
compatibility and flag size > 1 MB (INFO).

## 14. SKILL.md size budget

Run `wc -l skills/<name>/SKILL.md`. Flag **> 200 lines** as WARNING
(plan extraction of examples/schemas to a `references/` or
`tool-calls/` subdirectory) and **> 400 lines** as CRITICAL (extract
now; agent comprehension degrades). Exemptions, documented in the
checklist response: orchestration hubs (`work-on`, `fanout`,
`skill-audit`) may exceed 400 lines when they contain multiple
complete sub-workflows, each with a one-line justification.

### 14b. Instruction density budget (GH-882)

Run `dev10x skill count-instructions skills/<name>/SKILL.md`. Flag:

- **≥ 100** actionable instructions: WARNING — review for compaction
- **≥ 150** actionable instructions: CRITICAL — split or extract;
  frontier LLMs silently drop steps past this budget (QRSPI)

Counts ordered lists, bulleted imperatives, enforcement markers
(`REQUIRED:`, `MUST`, `DO NOT`), and bare tool-call specs. Exemptions
follow the same rule as item 14.

## 15. CLI-friction scanner (GH-5)

Run `bin/check-skill-cli-friction.py <changed-skill-files>` and flag any
output as CRITICAL. Common findings:

- Raw `gh pr|issue|api|repo` in bash fences → must use
  `mcp__plugin_Dev10x_cli__*` tools
- Raw `git commit|push|rebase|checkout -b` → must delegate to the
  matching `Skill(Dev10x:git-*)` / `Skill(Dev10x:ticket-branch)` wrapper
- Raw `pytest` invocation → must use `Skill(Dev10x:py-test)`
- `--no-verify` anywhere → CLAUDE.md global rule, no exemption

Skills that *implement* a wrapper are exempt automatically (see
`SKILL_EXEMPTIONS` in `src/dev10x/skills/audit/cli_friction.py`). For a
one-off legitimate case, suggest the inline marker
`# cli-friction: allow <rule-id> — reason`, not a skill-wide exemption.
