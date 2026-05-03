# Create Commit (Instructions)

## Overview

This skill creates properly formatted git commits following project conventions:
- Gitmoji prefix based on change type
- Ticket reference extracted from branch name
- 72 character title limit
- Structured body with solution points
- Proper footer with ticket reference

## Guiding Principle: User-Facing Outcomes

**Shift the perspective from what changed in the code to what it enables for the user.** The same principle drives Job Stories — the "so I can" clause captures the outcome, not the mechanism. This applies to commit titles, PR titles, ticket titles, and branch grooming.

- Bad: `Add DEVICES_READ to Square OAuth scopes` (implementation)
- Good: `Enable automatic terminal discovery` (outcome)
- Bad: `Add Square location ID GraphQL query` (implementation)
- Good: `Enable multi-location payment routing` (outcome)
- Bad: `Add customer_id column to invoices table` (implementation)
- Good: `Link invoices to customer records` (outcome)

## Orchestration

This skill follows `references/task-orchestration.md` patterns
(Tier: Standard).

**Auto-advance:** Complete each step and immediately start the next.
Never pause between steps to ask "should I continue?".

**REQUIRED: Create tasks before ANY work.** Execute these
`TaskCreate` calls at startup:

1. `TaskCreate(subject="Gather commit context", activeForm="Gathering context")`
2. `TaskCreate(subject="Draft commit message", activeForm="Drafting message")`
3. `TaskCreate(subject="Review and approve", activeForm="Reviewing message")`
4. `TaskCreate(subject="Create commit", activeForm="Creating commit")`

Set sequential dependencies: draft blocked by gather, review blocked
by draft, create blocked by review.

**Nested-mode exemption:** When invoked as a nested skill within
a parent orchestrator (e.g., via `Skill()` from `Dev10x:work-on`),
the four startup tasks above are condensed into **exactly one**
summary task — not zero. The parent's task list provides phase
visibility; the nested summary task makes the commit step itself
visible. See `references/task-orchestration.md` § Delegated
Invocation Exception.

Required nested-mode startup call:

1. `TaskCreate(subject="Commit outstanding changes", activeForm="Committing")`

Mark this task `in_progress` on entry and `completed` after the
commit succeeds (or `deleted` if the run aborts). Skipping the
task entirely is a compliance violation — it leaves the parent
orchestrator with no record that the commit step ran.

**Decision gates in nested mode:** ALL `AskUserQuestion` gates
documented below are skipped only when **both** unattended-mode
conditions in the next paragraph are met (invoked via
`Skill(Dev10x:git-commit)` AND the parent has an active task
list). When in doubt — for example, when called from a script
or one-off invocation with no parent task list — default to
**attended mode** and fire all gates. "Nested" alone does not
imply "unattended"; the active-task-list signal is what
authorizes auto-advance.

**Task creation in unattended mode (top-level only):** All 4
startup tasks MUST be created when running as a top-level
invocation. When a task's work is auto-skipped (e.g., "Review
and approve" in unattended mode), still create the task via
`TaskCreate` and immediately mark it `completed` with description
"Auto-skipped: unattended mode". This preserves supervisor
visibility into the full workflow.

**Unattended mode:** When this skill is invoked by an
orchestrating skill (e.g., `Dev10x:work-on`, `test:fix-flaky`,
`Dev10x:git-promote`) and the orchestrator has already approved
the work plan, all interactive decision gates are bypassed:
- Staging → auto-stage all changes
- Commit type → auto-select from context
- Problem/solution → auto-generate from session context
- Preview → skip (orchestrator already approved the plan)
- Next steps → return control to orchestrator immediately

Detection: unattended mode activates when **both** conditions
are met:
1. The skill is invoked via `Skill(Dev10x:git-commit)` (not
   directly by the user via `/Dev10x:git-commit`)
2. The caller is executing a plan step with an active task
   list (i.e., an orchestrating skill like `work-on`)

When either condition is absent, default to **attended mode**
with all interactive gates. When in doubt, default to attended.

**Decision gates (attended mode) — REQUIRED: Call
`AskUserQuestion`** (do NOT use plain text) at each of these
points. In unattended mode, these gates are skipped:

- **Staging approval** (when unstaged changes exist):
  **REQUIRED: Call `AskUserQuestion`** (do NOT use plain text,
  call spec: [ask-staging.md](./tool-calls/ask-staging.md)).
  Options:
  - Stage all (Recommended) — git add -A
  - Stage specific files — user specifies which files
  - Abort — cancel commit

- **Commit type selection** (gitmoji):
  **REQUIRED: Call `AskUserQuestion`** (do NOT use plain text,
  call spec: [ask-commit-type.md](./tool-calls/ask-commit-type.md)).
  Options:
  - Feature — new functionality
  - Fix — bug fix
  - Refactor — code restructuring
  - Test — adding or updating tests

- **Message preview approval**:
  **REQUIRED: Call `AskUserQuestion`** (do NOT use plain text,
  call spec: [ask-message-preview.md](./tool-calls/ask-message-preview.md)).
  Options:
  - Commit (Recommended) — create the commit as shown
  - Edit message — revise before creating
  - Abort — cancel commit

## Prerequisites Check

**IMPORTANT:** Verify git state before committing:

1. Check if we're in a git repository
2. Check if there are staged or unstaged changes
3. Check current branch (should not be develop/main/master)
4. Verify branch follows naming convention (username/TICKET-ID/[worktree/]description)

## When to Use This Skill

Use this skill when:
- Ready to commit changes with proper formatting
- Want to ensure commit follows project conventions
- Need help formatting commit message
- Want ticket reference auto-extracted from branch

## Workflow

### Step 1: Verify Git State

**CWD safety check — resolve worktree root first:**

Before any git commands, verify CWD is the repository/worktree
root. Prior commands in the session (e.g., `pnpm test`) may
have left CWD in a subdirectory, causing `git add` to interpret
repo-root-relative paths as CWD-relative — producing broken
double-nested paths like `apps/web/apps/web/src/...`.

```bash
git rev-parse --show-prefix
```

If the output is non-empty, CWD is a subdirectory. Get the
repo root and reset CWD in two separate steps (never chain
with `&&`):

```bash
git rev-parse --show-toplevel
```

Then use the returned path directly:

```bash
cd /absolute/path/to/repo/root
```

This avoids the `cd "$(git rev-parse ...)" && ...` pattern
which hooks block due to subshell + chaining friction.

**Never `git -C <path>`:** `git -C` breaks allow-rule matching
in `settings.local.json`. Always use `cd` to the repo root
first (above), then run git commands without `-C`.

**Check repository status:**
```bash
# Verify in git repo
git rev-parse --git-dir

# Get current branch
BRANCH=$(git symbolic-ref --short HEAD)

# Check for changes
git status --porcelain
```

**Validations:**
- ❌ If not in git repo → Error: "Not in a git repository"
- ❌ If on develop/main/master → Error: "Cannot commit directly to develop/main/master"
- ❌ If no changes → Error: "No changes to commit"
- ✅ If staged changes exist → Continue
- ⚠️ If only unstaged changes → Ask: "Stage all changes? (y/n)"

### Step 2: Extract Ticket ID from Branch

**Branch naming convention:** `username/TICKET-ID/[worktree-name/]description`

**Examples:**
- `janusz/PAY-133/fix-motor-timeout` → `PAY-133`
- `janusz/ENG-42/add-retry-mechanism` → `ENG-42`
- `janusz/PAY-133/app-pos-7/fix-motor-timeout` → `PAY-133` (worktree)

**Extraction:**
```bash
# Extract ticket ID (second segment)
TICKET_ID=$(git branch --show-current | cut -d'/' -f2)

# Validate format (TEAM-NUMBER)
if [[ ! $TICKET_ID =~ ^[A-Z]+-[0-9]+$ ]]; then
  echo "⚠️  Warning: Could not extract ticket ID from branch name"
  echo "Branch: $(git branch --show-current)"
  echo "Expected format: username/TICKET-ID/[worktree/]description"
fi
```

**If extraction fails:**
- Ask user: "What is the ticket ID? (e.g., PAY-133)"
- Use provided ticket ID

**If no ticket (technical branch):**
- Commits without ticket reference are allowed
- Skip ticket prompts

### Step 2.5: Optional JTBD Title Derivation

This step activates when **any** of these conditions are met:
- **Explicit request:** User passes "use Dev10x:jtbd" (or similar) in `/Dev10x:git-commit` args
- **First commit:** Ticket ID extracted, zero commits ahead of develop, and
  commit type is Feature (✨) or Bug (🐛)

**Flow:**
1. Invoke the `Dev10x:jtbd` base skill in **unattended** mode with `ticket_id`
2. Extract the "so I can" clause from the returned story
3. Transform it to an imperative title (e.g., "so I can track Zelle transactions" → "Enable Zelle transaction tracking")
4. Present as a suggestion:
   ```
   Suggested title: Enable Zelle transaction tracking
   Accept? (Enter = yes, or type your own)
   ```
5. If user accepts → use as the commit title description (Step 4 is pre-filled)
6. If user types their own → use that instead

**Skip entirely** when not explicitly requested AND it's a subsequent commit,
refactor, test, docs, or config change — keeping those fast. Also skip when a
Job Story was already sourced from the Linear ticket earlier in this session
(e.g., during `ticket:work-on`) — invoking the `jtbd` skill again is redundant.

### Step 3: Determine Commit Type

**Project override check:** Before presenting the type menu,
check for a strategy override:

1. Read `~/.claude/memory/Dev10x/gitmoji.yaml`
2. Get repo origin: `git remote get-url origin`
3. Walk the `projects` list — first `match` glob that fits
   the origin URL selects the named `strategy`
4. If no match, check `default-strategy`
5. If still no match, check for a semantic-release config in
   the project root (see `references/semantic-release.md`).
   Search for `release.config.mjs`, `.releaserc.json`,
   `.releaserc.yaml`, or `package.json` with a `"release"` key.
   If found, extract `releaseRules` from the
   `@semantic-release/commit-analyzer` plugin config and enrich
   the defaults with `release` tags. This adds release impact
   metadata without replacing the type menu.
6. If no config found, load `references/gitmoji-defaults.yaml`

If the user config or semantic-release config is invalid or
unreadable, log a warning and fall back to the defaults file —
never block the commit.

When a strategy is resolved (from manual override, semantic-release
auto-detection, or defaults), use its `gitmoji-mapping` list.
Each entry has `emoji`, `label`, `description`, and optional
`release` (patch/minor/major/none). When `release` is present,
append it as a badge: `"Bug fixes [patch]"`.

See `references/project-override.md` for manual override schema.
See `references/semantic-release.md` for auto-detection details.

**Unattended mode:** Auto-select the commit type from context
(e.g., changed file types, session history, orchestrator hints).
Skip the interactive prompt entirely. Use `label` matching
against detected change type. If a project override is loaded,
match against its entries.

**Attended mode — ask user to select commit type:**

Build the `AskUserQuestion` options from the loaded mapping
(project override or defaults). Present the first 4 entries
as options. If more exist, mention them in the question text
as additional choices available via "Other".

**Default gitmoji mapping:** Loaded from
`references/gitmoji-defaults.yaml` (ships with the plugin).
The "Other" option is always appended to allow custom gitmoji.

### Step 4: Get Commit Description

**Unattended mode:** Auto-generate the description from session
context (ticket title, changed files, commit type). Apply JTBD
self-check automatically and proceed without prompting.

**Attended mode — ask user:**
```
Short description (will be title line):
[User types description]
```

**Validate:**
- Calculate total length: `gitmoji + space + TICKET-ID + space + description`
- If > 72 chars → Ask: "Title is {X} characters (max 72). Please shorten the description."
- Iterate until ≤ 72 chars

**JTBD self-check (mandatory):** Before accepting the description, verify it
describes the **user-facing outcome**, not the implementation action. A
PreToolUse hook will block implementation-focused verbs at commit time, but
catch them earlier here to avoid the round-trip.

| Blocked verb | Example bad title | JTBD rewrite |
|---|---|---|
| Add | "Add retry logic" | "Enable automatic retry on failure" |
| Update | "Update OAuth scopes" | "Enable terminal discovery" |
| Remove | "Remove dead code" | "Simplify payment flow" |
| Refactor | "Refactor repository" | "Simplify repository hierarchy" |
| Move/Rename | "Move factory to utils" | "Enable shared factory access" |
| Synchronize | "Sync skill with source" | "Enable dual-mode workflow" |

If the description starts with an implementation verb, rewrite it before
proceeding. Use outcome verbs: **Enable, Allow, Support, Prevent, Ensure,
Simplify, Improve, Resolve, Streamline, Protect, Stabilize, Automate**.

**Example titles:**
- `✅ PAY-310 Stabilize tax amount tests` (38 chars)
- `🐛 PAY-133 Resolve motor timeout in payments` (46 chars)
- `♻️ PAY-200 Simplify payment repository hierarchy` (50 chars)

### Step 5: Get Problem Explanation

**If the problem and solution are already known from prior context** in the
session (e.g., from a preceding scope, code review, or ticket investigation),
auto-generate Steps 5-6 rather than asking redundant questions.

**Attended mode:** Present the pre-filled content in the preview
(Step 9) for user review.

**Unattended mode:** Auto-generate and proceed directly to
staging and commit — no preview gate.

**Otherwise, ask user:**
```
Detailed explanation of the problem being solved:
(What was wrong? Why did it need fixing? Context?)

[User provides explanation - can be multiple lines]
```

**Guidance:**
- Explain WHAT was wrong
- Explain WHY it needed fixing
- Provide context
- 2-4 sentences typically sufficient

**Example:**
```
Tests in TestAddTireServiceIndividual and TestAddTireServiceMultiple
were marked as flaky because they randomly failed when tax amounts
or percentages were generated as zero by Faker.
```

### Step 6: Get Solution Points

**Unattended mode:** Auto-generate solution points from the
staged diff and session context. Summarize what changed in
2-4 bullet points without prompting.

**Attended mode — ask user:**
```
Solution points (what did you change?):
Enter each point on a new line. Type 'done' when finished.

1: [User enters first point]
2: [User enters second point]
3: [User enters third point]
done
```

**Format each point:**
- Start with `-` (bullet point)
- Be specific about what changed
- Include file names if relevant

**Example:**
```
- Added non_zero trait to MoneyFaker with min_value=Decimal('0.01')
- Updated test fixtures to ensure tax amounts and percentages >= 0.01
- Removed @pytest.mark.flaky decorators
```

### Step 7: Generate Complete Commit Message

**Title format:** If a project override defines `title-format`,
use it to assemble the title line. Supported placeholders:
- `<gitmoji>` — emoji from selected type
- `<ticket>` — extracted ticket ID
- `<description>` — user-provided description
- `<conventional-type>` — label from mapping, lowercased

Default format: `<gitmoji> <ticket> <description>`

**Assemble message:**
```
<title per format>

<problem explanation>

Solution:
<solution points>

Fixes: <TICKET-ID>
```

**Example:**
```
✅ PAY-310 Fix flaky tests with non-zero tax amounts

Tests in TestAddTireServiceIndividual and TestAddTireServiceMultiple
were marked as flaky because they randomly failed when tax amounts
or percentages were generated as zero by Faker.

Solution:
- Added non_zero trait to MoneyFaker with min_value=Decimal('0.01')
- Updated test fixtures to ensure tax amounts and percentages >= 0.01
- Removed @pytest.mark.flaky decorators

Fixes: PAY-310
```

### Step 8: Validate Line Lengths (72 char limit)

**IMPORTANT:** Before showing preview, validate ALL lines are ≤ 72 characters.

**Validation command:**
```bash
# Check each line of the commit message
echo "$COMMIT_MESSAGE" | awk '
  length > 72 {
    print "❌ Line " NR " too long (" length " chars): " $0
    fail = 1
  }
  END { exit fail }
'
```

**If any line exceeds 72 characters:**

**Unattended mode:** Auto-wrap or shorten the offending lines
(split long bullets, abbreviate paths, use shorter synonyms).
Re-validate and proceed without prompting. If auto-fix is not
possible, surface the error back to the orchestrator.

**Attended mode:**
1. Show which line(s) are too long with character count
2. Ask user to shorten the offending line(s)
3. Re-validate until all lines pass

**Quick length check for a single line:**
```bash
echo "your line here" | awk '{print length " chars"}'
```

**Common fixes for long lines:**
- Split into multiple bullet points
- Use shorter synonyms
- Move details to next line
- Abbreviate file paths (just filename, not full path)

**Example validation output:**
```
❌ Line 7 too long (77 chars): - Rename stages: base-os → system-base, base-python → python-dependencies

Suggestion: Split into two lines or shorten:
- Rename stages for clarity (system-base, python-dependencies)
```

### Step 9: Show Preview and Confirm

**Unattended mode:** Skip this gate entirely. The orchestrator
has already approved the work plan, and the commit message was
auto-generated from session context. Proceed directly to
staging (Step 10) and commit creation (Step 11).

**Attended mode — this step is MANDATORY.** Never skip it when
invoked directly by the user, even when Steps 5-6 were
auto-generated from session context. **DO NOT proceed to
`git commit` without user approval — skipping this gate is a
compliance violation.**

**Display formatted message:**
```
Preview of commit message:
─────────────────────────────────
<formatted message>
─────────────────────────────────

Create this commit? (y/n/edit)
- y: Create commit
- n: Cancel
- edit: Modify the message
```

**If edit:**
- Ask which part to edit (title/explanation/solution)
- Re-prompt for that section
- Show new preview

### Step 10: Stage Files (if needed)

**Hard rule: NEVER stage individual files by name** (e.g.,
`git add file1.py file2.py`) to PICK files into a commit.
Selective staging bypasses the skill contract — all changes
in the working directory belong to this commit. Use
`git add -A` or `git add .` as the staging primitive.

**Escape valve — excluding unrelated paths.** When the working
tree contains changes that genuinely do not belong in this
commit (e.g., a session-scoped config touch in `.claude/`
captured incidentally while editing `skills/`), prefer **one of**
the following over selective `git add`:

1. **Commit the unrelated paths first.** Re-invoke
   `Skill(Dev10x:git-commit)` for the unrelated change with
   its own message, then return to this commit with a clean
   working tree. This is the default — keep commits atomic by
   *time*, not by `git add` argument lists.
2. **Pathspec exclusion.** When unrelated paths cannot be
   committed first (e.g., generated noise that should stay
   out of the commit altogether), pass an exclude pathspec
   to `git add` so the staging primitive remains the same:
   ```bash
   git add -A -- ':!path/to/excluded' ':!other/path'
   ```
   This is NOT selective staging — it stages everything except
   the named paths and is allowed by the contract.
3. **Post-add unstage** (last resort). After `git add -A`,
   remove specific paths from the index with
   `git restore --staged <pathspec>`. Document in the commit
   message body why those paths were excluded so the rationale
   is preserved.

Never use `git reset HEAD <path>` or `git rm --cached <path>`
as exclusion shortcuts — they create the same selective-staging
anti-pattern the hard rule prohibits.

**Unattended mode:** Auto-stage all changes (`git add -A`)
without prompting. The orchestrator's approved plan implies
all current changes are intended for this commit. If the
orchestrator wants to exclude paths, it MUST pass them via
the pathspec-exclusion form above — the unattended default
does not silently drop files.

**Attended mode — if unstaged changes exist:**

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text).
Options:
- Stage all (Recommended) — `git add -A`
- Only commit already staged files
- Abort

### Step 11: Create the Commit

**Use Write tool + `-F` to preserve formatting (hookify blocks heredocs):**

1. **REQUIRED:** Create a temp file via mktmp MCP tool:
   `mcp__plugin_Dev10x_cli__mktmp(namespace='git',
   prefix='commit-msg', ext='.txt')`
   Store the returned `path` value.
   **Fallback** (if MCP unavailable):
   ```bash
   /tmp/Dev10x/bin/mktmp.sh git commit-msg .txt
   ```
   **Do NOT use hardcoded paths** — hooks reject non-mktmp
   paths and the commit will fail.

2. **Read the empty file first** — the Write tool requires a prior Read
   on the same path. Call `Read(<unique-path>)` before writing. The file
   will be empty (mktmp creates it); this is expected.

3. Write the commit message to that file using the Write tool:
   ```
   Write <unique-path>:
   <gitmoji> <TICKET-ID> <description>

   <problem explanation>

   Solution:
   <solution point 1>
   <solution point 2>
   <solution point 3>

   Fixes: <TICKET-ID>
   ```

4. Create the commit from the file:
   ```bash
   git commit -F <unique-path>
   ```

**Verify success:**
```bash
if [ $? -eq 0 ]; then
  echo "✅ Commit created successfully"
  git log -1 --oneline
else
  echo "❌ Commit failed"
  # Show error
fi
```

**Error recovery:** If the hook blocks the commit, you are
likely using a non-mktmp path or running outside the skill
context. Restart via `Skill(Dev10x:git-commit)` with no args.
Do NOT attempt to bypass hooks with `python3 subprocess` or
`--no-verify`.

### Step 12: Next Steps

**Unattended mode:** Return control to the orchestrator
immediately after a successful commit. Do not show next-step
options or ask "what next?".

**Attended mode — ask user:**
```
Commit created successfully!

Next steps:
1. Continue working
2. Create another commit
3. Create PR (/Dev10x:gh-pr-create)

What would you like to do? (1/2/3/done)
```

**If 3 (Create PR):**
- Use `Dev10x:gh-pr-create` skill
- PR title will use this commit message

## Important Notes

- **No Co-Authoring:** Never add "Co-Authored-By: Claude" footer (per CLAUDE.md)
- **72 char limit:** ALL lines strictly enforced (title AND body)
- **Always validate:** Run `echo "line" | awk '{print length}'` before committing
- **Ticket extraction:** Automatic from branch name
- **Gitmoji format:** Use emoji character, not :code:
- **Footer:** Always include `Fixes: TICKET-ID`
- **Spacing:** One space after gitmoji, one space after ticket ID
- **Never `git -C <path>`**: See Step 1 — use `cd` to repo root instead.
- **Never `cd /path && git ...`**: The `&&` shifts the command prefix,
  breaking allow-rule matching. Use a standalone `cd` call or absolute
  paths. Each Bash call must contain exactly one command.
- **Never chain `git add && git commit`**: Use two separate Bash tool
  calls — one to stage, one to commit. Same rule applies to
  `git add && git rebase --continue`. Each call must stand alone.
- **Never stage individual files**: Use `git add -A` or `git add .`
  exclusively. Selective staging bypasses the skill contract.
- **Mandatory mktmp usage**: ALL temp files for commit messages
  MUST be created via mktmp (MCP tool or script fallback).
  Hardcoded paths are rejected by hooks and cause commit failure.

## Integration with Other Skills

```
Dev10x:git-commit
├── Used during development workflow
├── Output: Properly formatted commit
└── Can be followed by: Dev10x:gh-pr-create
```

## Example Usage

### Example 1: Create commit with auto-extracted ticket

**User request:**
```
/Dev10x:git-commit
```

**Current branch:** `janusz/PAY-310/fix-flaky-tests`

**Workflow execution:**
1. Check git status → Unstaged changes found
2. Ask: "Stage all changes?" → User: Yes
3. Stage files: `git add .`
4. Extract ticket ID → `PAY-310`
5. Ask commit type → User selects: 1 (Test)
6. Ask description → User: "Fix flaky tests with non-zero tax amounts"
7. Validate length → 51 chars ✓
8. Ask problem explanation → User provides
9. Ask solution points → User provides 3 points
10. Generate message
11. Show preview → User approves
12. Create commit with heredoc
13. Verify success → "✅ Commit created"
14. Show: `git log -1 --oneline`

**Result:**
```
✅ PAY-310 Fix flaky tests with non-zero tax amounts
```

### Example 2: Bug fix commit

**User request:**
```
/Dev10x:git-commit
```

**Current branch:** `janusz/PAY-133/fix-motor-timeout`

**Workflow execution:**
1. Check status → Staged changes ready
2. Extract ticket → `PAY-133`
3. Ask type → User: 2 (Bug)
4. Ask description → "Fix motor timeout in payment processing"
5. Length check → 53 chars ✓
6. Problem explanation → "MotorTimeoutException occurs when Square API is slow..."
7. Solution points:
   - Increase timeout from 5s to 15s
   - Add retry with exponential backoff
   - Improve error logging
8. Preview → User approves
9. Create commit
10. Success!

**Result:**
```
🐛 PAY-133 Fix motor timeout in payment processing
```

### Example 3: Commit with manual ticket ID

**User request:**
```
/Dev10x:git-commit
```

**Current branch:** `feature/improve-search` (no ticket ID)

**Workflow execution:**
1. Check status → OK
2. Try extract ticket → Failed (no standard format)
3. Warn: "Could not extract ticket ID"
4. Ask: "Ticket ID?" → User: `PAY-200`
5. Ask type → User: 3 (Refactor)
6. Ask description → "Refactor search to use Elasticsearch"
7. Continue normally...

**Result:**
```
♻️ PAY-200 Refactor search to use Elasticsearch
```

### Example 4: Technical commit without ticket

**User request:**
```
/Dev10x:git-commit
```

**Current branch:** `fix-typo-in-readme`

**Workflow execution:**
1. Check status → OK
2. Try extract ticket → Failed
3. Ask: "Ticket ID?" → User: (press Enter for none)
4. Ask type → User: 5 (Docs)
5. Ask description → "Fix typo in README"
6. Length check → 25 chars ✓
7. Problem: "README had typo in installation section"
8. Solution: "Fixed typo: 'instal' → 'install'"
9. Generate WITHOUT ticket reference:
   ```
   📝 Fix typo in README

   README had typo in installation section

   Solution:
   - Fixed typo: 'instal' → 'install'
   ```
10. Create commit

**Result:**
```
📝 Fix typo in README
```

## Error Handling

### Common Scenarios

**"Not in a git repository":**
- Error and stop
- Suggest: Initialize git repo first

**"No changes to commit":**
- Show: `git status`
- Suggest: Make changes first

**"Cannot commit to develop/main/master":**
- Error and stop
- Suggest: Create feature branch first

**"Title too long":**
- Show character count
- Ask for shorter description
- Iterate until ≤ 72

**"Pre-commit hook failed":**
- Show hook error
- Ask: "Fix issues and retry? (y/n)"
- If yes: Return to Step 9 (stage files)

**"Commit failed":**
- Show git error
- Suggest common fixes (conflicts, permissions, etc.)

## Resources

### references/gitmoji-guide.md

Complete gitmoji reference with usage guidelines.

### references/commit-examples.md

Real commit message examples from the project.

### references/gitmoji-defaults.yaml

Default gitmoji-to-type mapping shipped with the plugin.

### references/project-override.md

Project-level gitmoji strategy overrides — schema, resolution
order, and examples for `~/.claude/memory/Dev10x/gitmoji.yaml`.

### references/semantic-release.md

Auto-detection of gitmoji-to-release mappings from a project's
semantic-release config (`release.config.mjs`, `.releaserc`, etc.).

## Success Criteria

A successful commit should:
- ✅ Follow gitmoji convention
- ✅ Include ticket reference (if applicable)
- ✅ Have title ≤ 72 characters
- ✅ Include problem explanation
- ✅ List solution points
- ✅ Include `Fixes:` footer (if ticket)
- ✅ No co-authoring attribution
- ✅ Be properly formatted for git log viewing
