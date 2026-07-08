---
name: reviewer-skill
description: >
  Review skill definitions (skills/**) for structure, naming
  convention, tool declarations, and completeness. Read-only —
  returns findings, never edits or posts.
tools: Glob, Grep, Read
model: haiku
---

# Skill Reviewer — Structure & Tools

Review skill definitions for structure, naming convention, and
completeness. For behavioral and orchestration checks, see
`reviewer-skill-behavior.md`.

## Trigger

Files matching: `skills/**`

## Required Reading

- `.claude/rules/skill-naming.md` — naming convention
- `.claude/rules/skill-patterns.md` — skill architecture patterns (script vs orchestration)

## Checklist

1. **SKILL.md exists** — every skill directory must contain a SKILL.md with
   valid YAML front matter. Required: `name:`, `description:`, `invocation-name:`.
   Optional: `allowed-tools:`, `user-invocable:`.
2. **Naming convention** — directory uses plain name (no `dx-` prefix);
   `name:` MUST use `Dev10x:<feature>` format; `invocation-name:` MUST
   match `name:` exactly — no shortened aliases, cross-family variants, or
   non-`Dev10x:` prefixes permitted. Both fields require the `Dev10x:`
   prefix (see `.claude/rules/skill-naming.md` lines 86-97)
3. **Description quality** — `description:` must explain when to
   trigger the skill; vague descriptions reduce discoverability.
   **Required trigger suffix**: every description must end with
   `TRIGGER when: [conditions]` and `DO NOT TRIGGER when: [conditions]`
   lines. Flag missing suffix as WARNING (degrades auto-discovery).
4. **Script references** — (Script-based skills only; skip for orchestration-based)
   SKILL.md-referenced scripts must exist in the directory. Check both
   `allowed-tools` entries AND inline code blocks.

   **Pattern detection**: See `.claude/rules/skill-patterns.md`. If the skill
   directory contains NO `scripts/` subdirectory AND the SKILL.md references
   no local paths (only `~/.claude/tools/` or external binaries), it's
   orchestration-based — Item 4 does not apply.
5. **Executable permissions** — directly-invoked scripts must be
   executable; `git ls-files --stage <path>` mode `100644` = not executable.
6. **Error handling** — scripts use `set -e`; handle missing dependencies
7. **No hardcoded paths** — scripts should use relative paths or
   environment variables, not absolute user-specific paths.
   For external binaries (yq, jq, gh, etc.) the preferred resolution
   pattern is: `TOOL="${TOOL:-$(command -v tool 2>/dev/null || echo "/fallback/path/tool")}"`.
8. **`allowed-tools` coverage** — if SKILL.md calls external scripts,
   front matter must declare matching `Bash(...)` entries (missing entries
   cause per-invocation approval prompts).
   **Built-in tools** (`AskUserQuestion`, `TaskCreate`, `TaskUpdate`,
   `Skill()`, `Read`, `Write`, `Edit`, `Glob`, `Grep`) are implicitly
   available — do NOT flag them as missing from `allowed-tools`.
   Only **MCP tools** and **Bash script paths** require declaration.
8b. **`allowed-tools` sync** — when a PR adds `mktmp.sh <ns> ...` calls,
    verify BOTH entries: `Bash(/tmp/Dev10x/bin/mktmp.sh:*)` AND
    `Write(/tmp/Dev10x/<ns>/**)`. Missing either causes WARNING.
8c. **Plugin directory existence** — for every `${CLAUDE_PLUGIN_ROOT}/skills/<name>/`
    entry in `allowed-tools`, verify `skills/<name>/` exists using
    Glob(`skills/<name>/SKILL.md`).
8d. **Skill porting pattern** — when a PR converts `~/.claude/skills/<name>/`
    to `${CLAUDE_PLUGIN_ROOT}/skills/<name>/`, verify:
    (a) all scripts have mode `100755`
    (b) all `allowed-tools:` entries cover every script invocation
    (c) no hardcoded absolute paths
8e. **Shared helper propagation** — when a PR propagates a `bin/` helper,
    enumerate ALL changed SKILL.md files and verify each has a matching
    `Bash(${CLAUDE_PLUGIN_ROOT}/bin/<script>:*)` entry.
8f. **Memory file Write coverage** — when a skill writes to
    `~/.claude/memory/Dev10x/<file>`, verify `allowed-tools:`
    includes a matching `Write(~/.claude/memory/Dev10x/**)` entry.
8g. **Cross-skill delegation** — when a skill delegates via `Skill()`:
    (a) delegated skill's `allowed-tools` includes `Read()` for findings
    (b) both skills declare compatible temp namespace
    (c) findings file path is deterministic (no session-unique uuids)
9. **Template consistency** — YAML code blocks containing a `name:` field
   must follow `skill-naming.md`, not ad-hoc examples.
9a. **Skill tool invocation syntax** — `Skill()` calls must use named
    parameters: `Skill(skill="Dev10x:target-name", args="...")`.
    See `references/skill-invocation.md`.
10. **Reference doc consistency** — cross-check `references/` documents
    against any matching `.claude/rules/` file.
10b. **Inline table consistency** — cross-check SKILL.md reference tables
     against script implementations; mismatches are bug signals.
11. **Embedded shell templates** — POSIX-compatible, no silent `|| true`,
    `<>` placeholder markers for user-replaceable values.
11b. **Embedded Python templates** — must pass ruff checks (F811, F541),
     use `os.environ[...]` for credentials, never hardcoded values.
12. **Self-contained content** — no ephemeral references ("see Memory note",
    "as discussed"); all constraints documented inline.
13. **Bundled binaries** — if `skills/<name>/bin/` contains a non-script
    binary, verify license compatibility and flag size > 1 MB (INFO).
14. **SKILL.md size budget** — run `wc -l skills/<name>/SKILL.md`. Flag:
    - > 200 lines: WARNING — plan extraction of examples/schemas to
      `references/` or `tool-calls/` subdirectory
    - > 400 lines: CRITICAL — extract now; agent comprehension degrades
    Exemptions (document in checklist response):
    - Orchestration hubs (`work-on`, `fanout`, `skill-audit`) may
      exceed 400 lines if they contain multiple complete sub-workflows
    - Each exemption must have a one-line justification

14b. **Instruction density budget** (GH-882) — run
    `dev10x skill count-instructions skills/<name>/SKILL.md`. Flag:
    - ≥ 100 actionable instructions: WARNING — review for compaction
    - ≥ 150 actionable instructions: CRITICAL — split or extract;
      frontier LLMs silently drop steps past this budget (QRSPI)
    Counts ordered lists, bulleted imperatives, enforcement markers
    (`REQUIRED:`, `MUST`, `DO NOT`), and bare tool-call specs.
    Exemptions follow the same rule as 14: orchestration hubs may
    exceed the budget with a one-line justification.

15. **CLI-friction scanner** (GH-5) — run
    `bin/check-skill-cli-friction.py <changed-skill-files>` and flag any
    output as CRITICAL. Common findings the scanner detects:
    - Raw `gh pr|issue|api|repo` in bash fences → must use
      `mcp__plugin_Dev10x_cli__*` tools
    - Raw `git commit|push|rebase|checkout -b` → must delegate to the
      matching `Skill(Dev10x:git-*)` / `Skill(Dev10x:ticket-branch)`
      wrapper
    - Raw `pytest` invocation → must use `Skill(Dev10x:py-test)`
    - `--no-verify` anywhere → CLAUDE.md global rule, no exemption
    Skills that *implement* a wrapper are exempt automatically (see
    `SKILL_EXEMPTIONS` in `src/dev10x/skills/audit/cli_friction.py`).
    For one-off legitimate cases, suggest the inline marker
    `# cli-friction: allow <rule-id> — reason` rather than adding a
    skill-wide exemption.

## Output Format

Apply to ALL `skills/**` files in the diff, including same-PR additions.
For each issue: **File** · **Severity** (CRITICAL/WARNING/INFO) · **Issue**
