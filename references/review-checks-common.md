# Review Checks — Cross-Cutting Concerns

Universal review checks regardless of domain-specific agent. For
workflow rules, see `review-guidelines.md`.

## Enforcement Levels

- **CRITICAL/WARNING** or **REQUIRED**: Enforced by CI/merge protection or code review; blocks merge
- **INFO** or **RECOMMENDED**: Advisory only; does not block merge
- Do not flag as REQUIRED unless enforcement mechanism exists (CI/merge protection/code review gate)
- When guidance could be misunderstood as always-mandatory, clarify in docs (pattern: "Hook-Blocked Patterns (enforced)" vs "Permission-Friction Anti-Patterns (advisory)" in `hooks/scripts/session-guidance.md`)

## False Positive Prevention Gate

Before posting **any** inline comment:

0. **Diff scope** — is this file changed in the current PR diff?
   Run `gh pr diff --name-only` to confirm. If not in diff, mark
   pre-existing and skip.
1. Does this violate a documented CLAUDE.md rule? (No rule = preference)
2. Does this contradict an established codebase pattern? (5+ uses)
3. Does referenced documentation file exist? (Verify with Read tool)
4. Quality improvement or just preference?

**If any answer fails, DO NOT post.**

## Code Verification Protocol

1. Read actual code file — never rely on diff snippets alone
2. Verify exact line numbers and values
3. Check for fixes in later commits
4. Quote exact code when making claims

## Known False-Positive Traps

Before raising any of these, **verify actual code**:

1. **Formatting already correct**: read current code, not diff context
2. **Code that no longer exists**: verify line exists after force-push
3. **Return type already present**: read the actual signature
4. **YAGNI**: accept author's "defer" judgment
5. **Rule file paths**: verify path exists with Glob before citing;
   correct paths listed in `.claude/rules/INDEX.md`
6. **Intentional behavior removal**: when PR title/ticket states
   removal is intentional, external bots flagging it as a bug are
   false positives
7. **Re-raise after side-effect**: `except E: side_effect(); raise`
   is NOT swallowing — caller still receives the error
8. **Shell script style**: different scripts use different shells
   (bash, sh, fish) — check the shebang before flagging syntax
9. **Skill SKILL.md format**: `name:` and `description:` are YAML
   front matter, not arbitrary fields — don't suggest restructuring
10. **External user-level skill names**: before flagging invocation names not
    in this repo (e.g., `ticket:branch`), check if the author confirmed they
    are external skills at `~/.claude/skills/`. If confirmed, do NOT re-raise.
11. **`~/.claude/` in `allowed-tools`**: skills delegating to user-installed
    tools (`~/.claude/tools/`, `~/.claude/skills/`) legitimately use these
    paths. Only flag if the path belongs to a plugin-distributed script.
12. **`/pull/new/` commit links**: pre-creation artifacts generated before the
    PR number is assigned — flag as RECOMMENDED to update to
    `/pull/<number>/commits/<sha>`, not REQUIRED.
13. **Plugin-vs-user skill path conversions**: when a PR converts
    `~/.claude/skills/<name>/` to `${CLAUDE_PLUGIN_ROOT}/skills/<name>/`,
    verify each `<name>` directory actually exists in `skills/`. Use Glob:
    `skills/<name>/SKILL.md`. Non-existent directories are user-level skills
    — the `~/.claude/` prefix must be preserved.
14. **`invocation-name` with non-`Dev10x:` prefix**: `invocation-name: ticket:foo`
    alongside `name: Dev10x:ticket-foo` is valid. The `Dev10x:` prefix requirement
    applies to `name:` only — do NOT flag `invocation-name:` as a naming
    violation when `name:` is already correct.
15. **Write-path namespace coverage** — when a `Write(/tmp/Dev10x/<ns>/**)`
    entry is renamed, verify the new namespace matches the first argument of
    every `mktmp.sh` invocation in that SKILL.md. A mismatch causes a
    write-permission rejection at runtime.
15b. **Bulk path migrations** — when a PR bulk-renames paths (e.g.,
    `/tmp/claude/` → `/tmp/Dev10x/` across multiple files), verify:
    (a) All `Bash()` path declarations match the renamed paths,
    (b) All `Read()` and `Write()` declarations are updated consistently,
    (c) Documentation files and code comments reference the new paths.
    Spot-check 3-5 random files in the changed set to catch inconsistent
    edits. Bulk migrations that miss doc updates are RECOMMENDED fixes.
16. **Ticket-ID when self-motivated** — if PR body contains
    `Fixes: none — self-motivated`, do not flag missing ticket ID in
    PR title or commit messages. No issue exists to reference.
17. **Branch name convention** — flag branch name violations
    INFORMATIONAL in Round 1 only. Do not re-raise in subsequent rounds
    as the branch name is immutable while the PR is open.
18. **RECOMMENDED items after author acknowledgment** — once an author
    has acknowledged a RECOMMENDED suggestion but not acted on it, do
    not re-raise it in later rounds. Repeating optional feedback the
    author consciously skipped is noise. Only REQUIRED issues block merge.
19. **PR body header position** — when a PR body contains Markdown headers
    (e.g., `## Summary`, `## Details`), verify the JTBD Job Story appears
    BEFORE all headers. A header before the JTBD breaks release notes parsing.
    Do not flag headers that appear AFTER the JTBD as violations.
20. **Hook changes without documentation** — if a PR adds a new security
    hook pattern (regex check, blocked command), verify that session-guidance.md
    or a rule file is updated with the same pattern, explanation, and
    alternative. A hook without documentation is incomplete — the user sees
    the block message but not the Why or How to recover. Do NOT skip the
    docs check.
21. **JTBD voice violations** — when a PR body, commit message, or issue
    title contains a Job Story using first-person ("I want to") or a
    faceless actor ("the user wants to"), flag as REQUIRED. Third-person
    domain-actor voice with a concrete role and beneficiary
    ("the service writer wants to … so the dealer can …") is required.
    Malformed voice breaks release notes parsing; see
    `references/git-jtbd.md` § Voice Requirement and § Choosing the Actor.
22. **Story language violations** — when a PR body, ticket, or acceptance
    criterion writes Job Stories, user stories, or BDD scenarios in the
    wrong project/ticket language, flag as REQUIRED. For BDD and
    Gherkin-derived keywords, verify translations against Cucumber's
    official language reference:
    https://cucumber.io/docs/gherkin/languages/
23. **SKILL.md table/implementation skew** — when a PR modifies an
    executable construct (alias, script command, option, environment variable)
    documented in a SKILL.md reference table, cross-check that the table is
    updated. If the table quotes the command being changed and the PR updates
    that command, the table row is now stale. Assess **functional risk**:
    will users copying the old example fail their own commands? Functional
    risk (users copy stale alias → command fails) → CRITICAL/REQUIRED. Pure
    cosmetic drift (table describes intent, example text outdated) →
    RECOMMENDED. Confirm intent via commit message when unclear.
24. **MCP tool enumeration consistency** — when a PR adds MCP tool support via
    new `mcp__plugin_*` declarations in `allowed-tools:`: (a) verify all MCP
    tools are declared in `.claude-plugin/plugin.json`, (b) verify the tool
    naming follows `mcp__plugin_Dev10x_<server>__<function>`, (c) when a tool
    is used in multiple skills, verify each skill's `allowed-tools` includes
    the full tool name (not a wildcard pattern unless intentional). Spot-check
    one skill per MCP server. See `.claude/rules/mcp-tools.md` for naming.

## Architecture Checklist (GH-916)

Structural checks for new or substantially modified files. These
catch violations that surface-level bug hunting misses.

1. **Service layer presence** — new endpoints/views MUST delegate
   business logic to a service class (View→Service→Repository).
   Direct repository calls from views are a WARNING.
2. **Function size** — functions/methods exceeding 50 lines likely
   violate SRP. Flag as WARNING with extraction suggestion.
3. **DTO usage** — inline dicts with 4+ keys crossing module
   boundaries should be DTOs (pydantic dataclasses). Flag as INFO.
4. **Input validation** — manual `request.data["key"]` parsing
   without serializer/DTO validation is a WARNING. Validate early.
5. **God function detection** — a single function performing
   validation + business logic + persistence + response formatting
   is a structural violation regardless of line count.

**When to apply:** On every PR that adds or significantly modifies
endpoint/view/service code. Skip for docs-only, config-only, or
test-only PRs.

**Independence rule:** Evaluate architecture independently of
prior review comments. Previous surface-bug fixes do not validate
structural compliance.

## Cross-Consumer Behavioural Reuse (GH-290)

When a PR reuses an existing data relation (DB row, FK, OneToOne)
for a new purpose, a sibling repository may already treat row
presence as an implicit feature flag — populating the relation
silently activates an unrelated feature. The check fires only
when the diff dereferences a relation the PR did NOT introduce
(no sibling `migrations/*.py` in the same PR), then greps
project-configured sibling repos for boolean/length gating on
the relation. Severity ladders from INFO (test fixture) →
WARNING (component visibility) → CRITICAL (route/menu guard).

See [`review-checks/cross-consumer-reuse.md`](review-checks/cross-consumer-reuse.md)
for trigger details, sibling-repo config schema
(`.claude/Dev10x/sibling-repos.yaml`), grep patterns, severity
matrix, reporting format, and silent-skip degradation rules.

## Parameter Change Analysis

When parameters are added/removed/made optional:
- Grep **all** call sites (not just the diff)
- Check if optional serves backward compatibility
- When suggesting required: list all call sites to confirm

## Dead Code Detection

For new classes/functions/constants in the PR:
- Grep for imports and references outside the definition file
- If no references found, flag as potential dead code
- Exclude test classes, abstract base classes, `__init__` exports

## Naming Convention Verification

Before suggesting naming changes:
1. Search codebase patterns first (5+ files = established convention)
2. Only suggest genuinely unclear/misleading names
3. Do NOT flag: established patterns, version suffixes, domain prefixes

## Module Architecture Awareness

Different skills and scripts may use different patterns intentionally.
Only flag security concerns, documented rule violations, or bugs —
not valid architectural choices.

## Documentation File & Command Verification

When docs reference CLI commands, files, or directories (e.g., install
instructions, code examples):
- **Commands**: Verify they appear in `CLAUDE.md` Development section or
  are known Claude Code CLI built-ins
- **Files and directories**: Use Glob to verify they exist in the current
  commit (e.g., `scripts/install-skill.py`)
- **Planned features**: If documenting future features not yet implemented,
  clearly mark as `[PLANNED]` or `[NOT YET IMPLEMENTED]` to prevent
  user confusion when they attempt to use non-existent functionality
- Unverified references in user-facing docs are WARNING severity

## Shell Anti-Patterns

- **Hardcoded temp paths**: skills must not hardcode `/tmp/Dev10x/<x>.txt`.
  All temp files must be created via
  `/tmp/Dev10x/bin/mktmp.sh <namespace> <prefix> [.ext]`.
  Hardcoded paths are WARNING; missing `allowed-tools` coverage is also WARNING
  (see rules 8b/8e in `reviewer-skill.md`).
- **Silent error swallowing**: `|| true` on setup steps and `2>/dev/null`
  on media-encoding commands (ffmpeg, convert, ImageMagick) hide failures;
  replace with a fallback action (`|| { cmd; }`) or remove the redirect.
  Also flag `2>/dev/null` on any command whose stdout is captured into a
  variable (`var=$(cmd 2>/dev/null)`) when that variable drives branching
  logic — an empty string from a silenced failure produces misleading errors
  downstream. **Also flag implicit defaults** (e.g., `jq '.field // ""'`)
  when the default value drives subsequent branching; validate explicitly
  instead: `[[ -z "$VAR" ]] && { error; exit 1; }`.
- **Pipe segment completeness in security hooks**: when a hook script
  parses a shell command to detect a pattern (e.g., `psql`, `python3 -c`),
  it must inspect ALL segments — both pipe-delimited (`|`) AND
  `&&`- or `;`-chained sub-commands. A detector that only splits on `|`
  will miss `echo done && psql -h host mydb "DELETE ..."`.
  Use a segment splitter that handles all shell control operators.

## GitHub API Polling Patterns

When skills call GitHub APIs that trigger async background jobs (check
suite registration, status computation):

- **Check suite registration delay**: After `git push` or when calling
  `gh pr checks`, verify the skill waits at least 60 seconds before
  the first poll. GitHub needs time to register new check suites after
  a push — polling immediately returns stale results from the previous
  commit.
- **Check count verification**: When checking for "all pass", verify the
  skill compares the current check count against a baseline from the
  first full run. A mismatch (fewer checks reported than baseline)
  indicates incomplete suite registration — the skill should wait 30
  seconds and re-poll.
- **Status caching**: Document any async behavior (GitHub status
  computation, check suite propagation) that affects polling logic.
  Without timing guidance, agents may poll too early and receive false
  negatives.

## Sequential Step Integrity

When SKILL.md defines ordered task lists, flag:
- **Inverted prerequisites**: step N requires step N+1 to have run first
  (e.g., "Request re-review" before "Self-review") — WARNING
- **Subsumed steps**: step N is a proper subset of step N+1 (both perform
  the same action) — WARNING; suggest removing the more specific step

## Python Linting Checks

- **f-strings without expressions**: `f"static string"` with no `{}`
  placeholders is ruff F541. Flag and suggest removing the `f` prefix.
