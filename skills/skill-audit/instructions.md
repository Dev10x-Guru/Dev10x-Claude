# Skill Audit (Instructions)

Analyze a Claude Code session transcript for skill compliance, missed invocations,
user corrections, and process improvements worth persisting into skill definitions.

## Orchestration

This skill follows `references/task-orchestration.md` patterns.

**Auto-advance:** Complete each phase, immediately start the next — no checkpoints under adaptive friction.
Never pause between phases.

### Deferral (GH-219)

To **defer** an audit until later without interrupting current
work, invoke `Dev10x:skill-audit-queue` instead. That skill
appends a tracker task at the end of the current task list with
a TODO to invoke `Dev10x:skill-audit`. When the supervisor
reaches the queued task, they invoke this skill directly.

Invoking `Dev10x:skill-audit` (this skill) is a declaration that
the audit should run **now** — proceed directly to Strategy Selection.

### Important Rules

**When asked about this skill's behavior, re-Read
`instructions.md` before answering (GH-219).** Do not rely on
summarized recall from earlier in the session. Questions about
phase semantics, deferral, gates, or task-list behavior must be
answered against the current source — agents that answer from
prior context routinely contradict the live instructions.

---

## Strategy Selection (GH-436)

The audit runs in one of two strategies. **Lightweight is the
default.** The forensic strategy is reserved for explicit opt-in
or auto-escalation.

| Strategy | When | What runs |
|----------|------|-----------|
| **Lightweight** (default) | No `--full` flag; supervisor knows the incident | Inline analysis of visible context; structured disposition gate; Phase 7 when upstream-relevant |
| **Forensic** | `--full` flag passed, OR early-insight escalation | Full transcript extraction + Wave 1/2 subagents + all phases |

**Auto-escalation to forensic:** If lightweight analysis cannot
answer the question (no specific incident visible in context,
or the supervisor requests transcript-level evidence), escalate
to forensic. Present a one-line explanation and proceed to
Step 0 (initialize forensic task tracking).

**Never default to forensic.** The Wave 1/2 subagent fan-out is
expensive. Use it only when the lightweight path genuinely cannot
answer.

---

## Lightweight Strategy (default)

### Phase 0: Inline Analysis and Disposition

**This is the default entry point for all audits.**

The supervisor invokes the skill with a description of what they
observed (or no argument for a generic session review). The agent
works from the **current conversation context** — no transcript
extraction, no subagent dispatch.

#### Step 0a: Determine scope

From the invocation argument and recent conversation context:

1. **Specific incident**: Argument names a PR URL, a session
   event, or a single observed behavior.
2. **Generic session review**: Argument is empty, a directory, or
   a JSONL path with no narrow question.
3. **`--full` flag**: Explicit forensic request → skip lightweight,
   go to Step 0 (forensic).

For cases 1 and 2, continue in lightweight mode.

#### Step 0b: Inline findings

Present 1–5 bullets covering:

- The incident or pattern observed
- The root cause (skill gap, missed invocation, compliance
  deviation, or correct behavior)
- The persistable lesson — what should change in a skill,
  memory file, or upstream issue

Cite turn numbers or quoted evidence when available.
Do NOT modify any files at this point.

**Small friction/skill notes:** If a small permission-friction
note or skill-improvement observation surfaces during the
inline analysis, include it as a bullet with classification
`friction-note` or `skill-note`. These do not trigger a full
Phase 4 analysis. Queue them in the disposition below instead
of expanding to a full forensic wave.

#### Step 0c: Disposition gate

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text,
call spec: [`tool-calls/ask-early-insight.md`](tool-calls/ask-early-insight.md)).
Options:

- **Select & file now (Recommended)** — present a structured
  selection step, then delegate to Phase 7 with inline findings.
- **Run forensic audit** — escalate to full transcript
  extraction and Wave 1/2 analysis (fall through to Step 0).
- **Discard — no action needed** — exit without filing.

**Adaptive friction behavior:** This gate is **ALWAYS_ASK** —
fires at every friction level, including `adaptive`. The
disposition decision (file, escalate, discard) must be explicit.

#### Step 0d: Disposition handling

| User choice | Next action |
|-------------|-------------|
| Select & file now | Create minimal task list: `TaskCreate(subject="Phase 0: Inline findings", activeForm="Presenting findings")` followed by `TaskCreate(subject="Phase 7: Upstream reporting", activeForm="Reporting upstream")`. Jump directly to Phase 7 using the inline findings. Phase 7 sub-steps A–D still run. |
| Run forensic audit | Fall through to Step 0 (forensic). Create the full task list and proceed with Wave 1 + Wave 2 orchestration. |
| Discard | Exit without creating wave tasks and without invoking `Dev10x:audit-file`. |

#### Why lightweight is the default (GH-436)

- **Avoids expensive subagent fan-out** when the question is
  already answered by the visible transcript. Wave 1/2 are
  multiple haiku/sonnet calls; they add cost with no benefit
  when the supervisor already knows the incident.
- **Inline analysis enables the audit to run in the current
  session** — no separate terminal required. The self-session
  guard and terminal-redirect block apply only to forensic
  (which replays the full transcript).
- **Preserves the supervisor selection gate**, which is the
  part of the skill with the most procedural value. The
  structured disposition step ensures findings get filed
  upstream rather than answered conversationally and forgotten.
- **Small friction/skill notes are captured at the right
  granularity.** A one-bullet friction observation does not
  warrant a Phase 4a–4g forensic wave. Notes are captured
  inline and queued to Phase 7 for lightweight filing.

---

## Forensic Strategy (`--full` or escalation)

The forensic strategy runs the full transcript extraction and
Wave 1/2 subagent fan-out. Use it when the lightweight path
cannot answer, or when the supervisor explicitly requests
deep analysis.

**Run from a separate terminal** — the transcript replay
dominates the context window. See the self-session guard below.

### Step 0: Initialize task tracking (MANDATORY)

**Applies when Phase 0 escalated to forensic, or when `--full`
was passed.** If lightweight ended in "Select & file now" or
"Discard", the lightweight task list is authoritative — do NOT
create the forensic task list.

**REQUIRED: Create all tasks before ANY other work.**
Do NOT skip task creation or improvise an ad-hoc workflow.
Do NOT provide an inline audit summary — the audit MUST use
the subagent orchestration defined below. Inline summaries
bypass traceability and produce shallow analysis.
If you find yourself reading files or analyzing the transcript
without having created tasks first, STOP and create them now.

Execute these exact `TaskCreate` calls at startup:

**Setup (sequential):**

1. `TaskCreate(subject="Resolve session file", description="Find and validate the session JSONL file from the provided path or most recent session", activeForm="Resolving session")`
2. `TaskCreate(subject="Extract and read transcript", description="Run extract-session.sh to parse the JSONL file into a readable transcript", activeForm="Extracting transcript")`
3. `TaskCreate(subject="Detect project context", description="Identify project directory, loaded skills, and CLAUDE.md rules from the transcript", activeForm="Detecting context")`

**Wave 1 — parallel analysis (independent phases):**

4. `TaskCreate(subject="Phase 1: Action inventory [subagent]", description="Dispatch subagent to catalogue all tool calls, skill invocations, and agent dispatches", activeForm="Inventorying actions")`

**Wave 2 — parallel analysis (depends on Phase 1 output):**

5. `TaskCreate(subject="Phase 2: Skill coverage [subagent]", description="Dispatch subagent to check which skills should have been invoked but were missed", activeForm="Analyzing coverage")`
6. `TaskCreate(subject="Phase 3: Compliance check [subagent]", description="Dispatch subagent to verify skill execution matched documented orchestration steps", activeForm="Checking compliance")`
7. `TaskCreate(subject="Phase 5: Lessons learned [subagent]", description="Dispatch subagent to extract corrections, confirmations, and process improvements", activeForm="Extracting lessons")`

**Synthesis (sequential, main agent):**

8. `TaskCreate(subject="Phase 6: Propose changes", description="Synthesize findings into concrete SKILL.md edits, memory updates, and process improvements", activeForm="Proposing changes")`
9. `TaskCreate(subject="Phase 7: Upstream reporting", description="File findings as GitHub issues at the Dev10x plugin repo via Dev10x:audit-file", activeForm="Reporting upstream")`

**Note:** Phase 4 (Permission Friction) is not in the default
forensic task list. Add it only when the invocation explicitly
requests friction analysis, OR when the action inventory
(Phase 1) reveals 5+ permission prompts or structural toxicity
patterns. See "Permission Friction (Secondary)" below.

Set dependencies:
- Tasks 1→2→3 sequential (setup chain)
- Task 4 blocked by task 3 (Wave 1)
- Tasks 5, 6, 7 all blocked by task 4 (Wave 2 — run in parallel after Phase 1)
- Task 8 blocked by tasks 4, 5, 6, 7 (all analysis complete)
- Task 9 blocked by task 8

Update each task to `in_progress` before starting it and
`completed` when done.

### Batched decision queue (Phase 6)

As earlier phases discover findings that need user decisions
(skill updates, memory changes, allow rules), queue them in
task metadata rather than interrupting. Use `TaskUpdate` with
`metadata.decisions_queued` to record each finding, then collect
all queued decisions into a single `AskUserQuestion` batch in
Phase 6 so the user approves or rejects all changes at once.

## Arguments

The skill accepts one optional argument, resolved in this order:

1. **`--full`** — force forensic strategy regardless of context
2. **JSONL path** — if arg ends in `.jsonl`, use it directly
   (implies forensic)
3. **Worktree path** — if arg is a directory, encode it and find
   the latest JSONL in it (implies forensic)
4. **Specific incident description** — free text describing what
   happened; use lightweight strategy
5. **`latest`** (or no arg) — lightweight strategy using visible
   context; escalate to forensic only if context is insufficient

**Path encoding**: `/work/myproject/my-repo` → `-work-myproject-my-repo` (replace leading `/` then
all `/` with `-`).

**Project directory**: `~/.claude/projects/<encoded-path>/`

## Proactive Triggers

**MUST suggest this skill when ANY trigger below is detected.**
For triggers 1–5 (lightweight-compatible), suggest an inline
invocation. For triggers 6–8 (require transcript analysis),
suggest a separate terminal.

A 2nd hook-blocked retry in a session is a mandatory trigger
(see trigger 7).

1. **Raw scripts instead of tools** — You wrote 3+ raw `gh api`, shell pipelines,
   or other manual commands when a dedicated tool exists. The audit captures which
   tools were missed so memory/skills can be updated.

2. **Repeated user corrections** — The user corrected your approach 3+ times
   in the same session (wrong triage verdict, wrong tone, wrong implementation
   choice). The audit extracts patterns from corrections and proposes skill updates.

3. **Skill deviation pattern** — You skipped documented steps in a skill 2+ times
   (e.g., forgot to resolve threads after replying, forgot one-fixup-per-comment rule).

4. **Permission friction** — The user had to approve 3+ safe, repetitive commands
   (e.g., `pytest`, `uv run`, `psql ... SELECT`) that should be pre-approved.
   Capture as a small friction note via lightweight strategy; escalate to forensic
   Phase 4 only if 5+ distinct patterns are observed.

5. **Inline shell scripts** — A skill (SKILL.md) contains 3+ Bash lines written
   inline, OR a session used a multi-step shell pipeline/heredoc that would need
   repeated approval.

6. **Structural command friction** — You used `$()` subshells, `&&` chains,
   `git -C`, env var prefixes, or leading `#` comments that broke allow-rule
   prefix matching, AND the user had to reject/correct the approach. Suggest
   forensic (`--full`) for root-cause tracing.

7. **Hook-blocked retries** — A PreToolUse hook rejected a command but you
   attempted the same pattern again in the same session. Mandatory trigger;
   suggest `--full`.

8. **Redundant `uv run --script` prefixes** — A skill or shell script invokes
   a Python script with the redundant prefix. Suggest `--full` for a full script
   audit.

When a trigger is detected, find the current session's JSONL path and suggest.

For lightweight-compatible triggers (1–5):

> "I've noticed [trigger description]. You can audit this now:
> ```
> /Dev10x:skill-audit <description of what happened>
> ```
> or queue it for later with `/Dev10x:skill-audit-queue`."

For forensic triggers (6–8):

> "I've noticed [trigger description]. Open a new terminal and run:
> ```
> claude '/Dev10x:skill-audit --full <jsonl-path>'
> ```
> to capture these as improvements."

To find the current session's JSONL path, use:
```bash
ls -t ~/.claude/projects/<encoded-cwd>/*.jsonl | head -1
```

---

## Forensic Workflow

### Step 1: Resolve session file

```python
import os, glob

arg = "$SKILL_ARG"  # from the invocation
claude_dir = os.path.expanduser("~/.claude")

if arg.endswith(".jsonl"):
    session_file = arg
elif arg and os.path.isdir(arg):
    encoded = arg.replace("/", "-")
    if encoded.startswith("-"):
        pass  # already correct
    project_dir = f"{claude_dir}/projects/{encoded}"
    jsonls = sorted(glob.glob(f"{project_dir}/*.jsonl"), key=os.path.getmtime, reverse=True)
    session_file = jsonls[0]  # latest
else:
    cwd = os.getcwd()
    encoded = cwd.replace("/", "-")
    project_dir = f"{claude_dir}/projects/{encoded}"
    jsonls = sorted(glob.glob(f"{project_dir}/*.jsonl"), key=os.path.getmtime, reverse=True)
    session_file = jsonls[0]  # latest
```

Implement this logic using Bash (ls -t + head) rather than running Python inline.
If resolution fails, ask the user to provide the JSONL path explicitly.

**Do NOT silently fall back to alternate path encodings.** If the
primary encoded CWD has no JSONL files, STOP and ask the user for
the path. Do not try other encodings (e.g., parent directory,
worktree main repo) — falling back silently can resolve to a
completely different project's session (GH-805).

### Step 1.1: Confirm auto-resolved session (ALWAYS_ASK)

**Skip this gate when the user provided an explicit JSONL path.**
An explicit path means the user deliberately chose the session.

**Skip this gate when the invocation turn contains a clear
adaptive-friction affirmative (GH-127 #7).** When `friction_level
== adaptive` AND the same user message that invoked the skill
contains an unambiguous affirmative like `go`, `proceed`, `yes`,
`run it`, `audit it`, treat that as the confirmation and skip
the `AskUserQuestion`. Affirmatives must be in the **same turn**
as the invocation and unambiguous (mere "ok" or "k" does not
qualify).

**When the path was auto-resolved** (no arg, or arg is a
directory) AND no adaptive affirmative is present, extract the
session ID from the filename and the file's modification time,
then confirm with the user before proceeding.

**REQUIRED: Call `AskUserQuestion`** (ALWAYS_ASK — fires at
strict/guided friction levels, and at adaptive when no
affirmative is present; do NOT use plain text).

Display the resolved path, session ID, and mtime in the question
so the user can verify it's the correct session:

```
AskUserQuestion(questions=[{
    question: "Is this the session you want to audit?\n\n"
              "Session: <session-id>\n"
              "Path: <resolved-path>\n"
              "Last modified: <mtime>",
    header: "Session",
    options: [
        {label: "Yes, audit this session (Recommended)",
         description: "Proceed with the resolved session file"},
        {label: "No, let me provide the path",
         description: "I'll specify the correct JSONL path"}
    ],
    multiSelect: false
}])
```

If the user selects "No", ask for the correct path and restart
resolution from Step 1 with the provided path.

### Step 1.5: Self-session guard

**Forensic-only.** This guard does not apply to lightweight
audits — lightweight works from the visible conversation context,
not from a replayed transcript, so "audit dominates transcript"
is not a concern.

**Skip this guard when the user provided an explicit JSONL path
as the argument** (i.e., `arg.endswith(".jsonl")` was true in
Step 1). An explicit path means the user deliberately chose
which session to audit.

**Only apply this guard when the path was auto-resolved** via the
`latest` fallback (no arg, or arg is a directory). In that case,
the resolved file might be the current session's own JSONL.

When the guard applies, check if the resolved file was modified
within the last 60 seconds:

```bash
find "$SESSION_FILE" -mmin -1 -print
```

If the file matches (output is non-empty), this is likely the
current session. **STOP** and emit a redirect message:

> This audit targets the current session. Running it here will
> consume the context window before useful analysis begins.
> Open a **new terminal** and run:
> ```
> claude '/Dev10x:skill-audit --full <session-file-path>'
> ```

Do NOT proceed with extraction. Do NOT ask the user if they
want to continue anyway.

### Step 2: Extract transcript

Create a unique output file:
```bash
/tmp/Dev10x/bin/mktmp.sh skill-audit audit-transcript .md
```
Store the returned path, then run the extraction script:
```bash
${CLAUDE_PLUGIN_ROOT}/skills/skill-audit/scripts/extract-session.sh \
  "<session_file>" <unique-path>
```

> **Note:** Do NOT prefix this with `mkdir -p ... &&` — the `mktmp.sh` script
> creates the directory automatically. Prefixing with `mkdir &&` shifts
> the command prefix to `mkdir`, breaking the `Bash(~/.claude/skills:*)` allow rule.

### Step 3: Read the transcript

Use the Read tool to read the transcript at the unique path returned in Step 2.
This is the session you are auditing.

### Step 4: Detect project context

Locate the skills directory: `~/.claude/skills/`

**Read session friction context (GH-55 F9).** Look for
`.claude/Dev10x/session.yaml` in the project root and load
`friction_level` and `active_modes`. If the file is missing,
default to `friction_level: guided` and `active_modes: []`.

Persist both values for downstream use — pass them into the
Phase 3 (Compliance Check) subagent prompt in Step 7. Without
this, the Phase 3 subagent cannot tell which gates auto-select
at the active level and will produce false-positive
`SKIPPED_STEP` regressions for documented auto-advance behavior.

### Step 5: Create output files

Create a temp file for each analysis phase's output:

```bash
/tmp/Dev10x/bin/mktmp.sh skill-audit phase1-actions .md
/tmp/Dev10x/bin/mktmp.sh skill-audit phase2-coverage .md
/tmp/Dev10x/bin/mktmp.sh skill-audit phase3-compliance .md
/tmp/Dev10x/bin/mktmp.sh skill-audit phase5-lessons .md
```

Store the returned paths. Phase 1 script writes directly to its
output file. Wave 2 subagents (Phases 2, 3, 5) return findings
as their Agent result string — the main agent writes those to
the output files.

If Phase 4 was requested (see "Permission Friction (Secondary)"
below), also create:

```bash
/tmp/Dev10x/bin/mktmp.sh skill-audit phase4-permissions .md
```

**Subagent output strategy (Wave 2 only):** Subagents dispatched
via `Agent()` cannot reliably write to output files —
`bypassPermissions` does not propagate. Have each subagent
**return its findings as the Agent result string**, then write
from the main agent.

### Step 6: Wave 1 — Run deterministic scripts (Phase 1)

**Phase 1 uses a deterministic Python script** instead of an LLM
subagent. This prevents rogue subagent actions (GH-565) and
eliminates permission friction during analysis.

Run the script — it is stdlib-only, requires no user approval,
and produces structured markdown output:

1. **Phase 1 (Action Inventory):**
   ```bash
   ${CLAUDE_PLUGIN_ROOT}/skills/skill-audit/scripts/analyze-actions.sh \
     "<TRANSCRIPT_PATH>" "<PHASE1_OUTPUT>"
   ```

Mark task 4 as `completed` after the script finishes.
Read the output file to verify it contains valid markdown tables.

**If Phase 4 was requested**, also run:

2. **Phase 4 (Permission Friction):**
   ```bash
   ${CLAUDE_PLUGIN_ROOT}/skills/skill-audit/scripts/analyze-permissions.sh \
     "<TRANSCRIPT_PATH>" ~/.claude/settings.local.json "<PHASE4_OUTPUT>"
   ```

**Note:** The Phase Reference sections for Phase 1 and Phase 4
below remain as documentation of what the scripts produce. They
are no longer used as subagent prompts.

### Step 7: Wave 2 — dispatch dependent subagents

After Wave 1, Phase 1's output file contains the action inventory
that Phases 2, 3, and 5 need.

**REQUIRED: Launch all three subagents in a single message** so
they run concurrently. Include the full text of each phase's
instructions from the Phase Reference section in each prompt.

**Status protocol (GH-69):** Every Wave 2 prompt MUST append the
four-line status template from
`references/orchestration/subagent-status-protocol.md`. Each
subagent ends its output with one of:

- `DONE` — phase findings complete
- `DONE_WITH_CONCERNS: <text>` — findings complete but flagged
- `NEEDS_CONTEXT: <what>` — missing input the controller can provide
- `BLOCKED: <reason>` — permission wall, missing tool, or unrecoverable error

The main agent parses the trailing line of each Agent result
and branches per the protocol before writing the phase output
file.

1. `Agent(subagent_type="general-purpose", model="sonnet", description="Phase 2: Skill coverage", prompt="You are running Phase 2 (Skill Coverage Analysis). Return your complete findings as your response. Also attempt to write them to <PHASE2_OUTPUT> — if the write fails, the main agent will capture your findings from the returned result. Phase 1 action inventory: <PHASE1_OUTPUT>. Skills directory: <SKILLS_DIR>. Read the Phase 1 output, then [include full Phase 2: Skill Coverage Analysis instructions from the Phase Reference section]. Report your final status as the LAST line of your output, with exactly one of these prefixes: DONE / DONE_WITH_CONCERNS: <text> / NEEDS_CONTEXT: <what> / BLOCKED: <reason>. Do not write anything after the status line.")`

2. `Agent(subagent_type="general-purpose", model="sonnet", description="Phase 3: Compliance check", prompt="You are running Phase 3 (Compliance Check). Return your complete findings as your response. Also attempt to write them to <PHASE3_OUTPUT> — if the write fails, the main agent will capture your findings from the returned result. Phase 1 action inventory: <PHASE1_OUTPUT>. Session transcript: <TRANSCRIPT_PATH>. Skills directory: <SKILLS_DIR>. Session friction context: friction_level=<FRICTION_LEVEL>, active_modes=<ACTIVE_MODES>. When evaluating compliance, treat documented auto-select gates (e.g., `work-on` Phase 3 plan-approval at adaptive — GH-808) as COMPLIANT when the agent auto-selected the recommended option, NOT as SKIPPED_STEP. Read the Phase 1 output, then [include full Phase 3: Compliance Check instructions from the Phase Reference section]. Report your final status as the LAST line of your output, with exactly one of these prefixes: DONE / DONE_WITH_CONCERNS: <text> / NEEDS_CONTEXT: <what> / BLOCKED: <reason>. Do not write anything after the status line.")`

3. `Agent(subagent_type="general-purpose", model="sonnet", description="Phase 5: Lessons learned", prompt="You are running Phase 5 (Lessons Learned Extraction). Return your complete findings as your response. Also attempt to write them to <PHASE5_OUTPUT> — if the write fails, the main agent will capture your findings from the returned result. Phase 1 action inventory: <PHASE1_OUTPUT>. Session transcript: <TRANSCRIPT_PATH>. Memory directory: <MEMORY_DIR>. Read the Phase 1 output, then [include full Phase 5: Lessons Learned Extraction instructions from the Phase Reference section]. Report your final status as the LAST line of your output, with exactly one of these prefixes: DONE / DONE_WITH_CONCERNS: <text> / NEEDS_CONTEXT: <what> / BLOCKED: <reason>. Do not write anything after the status line.")`

Wait for all three subagents to complete. Mark tasks 5, 6, 7
as `completed` as each returns AND its status line is `DONE` or
`DONE_WITH_CONCERNS:`. For `NEEDS_CONTEXT:`, re-dispatch once
with the requested context inlined. For `BLOCKED:`, fall back
to running the phase's instructions in the main session and
surface the reason to the user.

### Step 8: Collect and synthesize

Read all phase output files. If any file is empty or missing
(subagent write failed), the main agent should already have the
findings from the subagent's returned result — write them now.
The main agent now has the complete findings from all analysis
phases and proceeds to Phase 6
(Propose Changes) and Phase 7 (Upstream Reporting) directly —
these require user interaction and cannot be delegated.

---

## Permission Friction (Secondary, GH-436)

Permission-friction analysis is a secondary signal, not a main
phase. It runs only under these conditions:

**Lightweight strategy:** Capture a brief `friction-note` bullet
inline in Phase 0 Step 0b when you observe small friction. Do
NOT dispatch a forensic wave for friction alone.

**Forensic strategy:** Add Phase 4 to the task list and run
`analyze-permissions.sh` when:
- The invocation explicitly requests friction analysis, OR
- Phase 1 action inventory reveals 5+ unmatched Bash/Read/Write
  calls, OR
- The supervisor adds Phase 4 after reviewing Phase 1 output

When Phase 4 does run (forensic), follow the full Phase 4
reference (steps 4a–4g) below. Its output is synthesized in
Phase 6 alongside the other phases.

**Queue time (skill-audit-queue):** Small friction/skill notes
observed at queue time can be captured as lightweight annotations
on the queued task. The `Dev10x:skill-audit-queue` skill accepts
a free-text description — use it to record the specific friction
pattern so the full audit has prior context.

---

## Phase Reference

The following phase descriptions are used both as inline reference
and as subagent prompt content. When dispatching a subagent, paste
the relevant phase section into the Agent prompt.

---

#### Phase 1: Action Inventory

Scan the transcript and catalog every significant action:

1. **Git operations**: commits, branch creation, rebases, pushes
2. **PR operations**: creation, review, comment responses, CI fixes
3. **Ticket operations**: creation, status changes, scoping
4. **Test operations**: running tests, fixing failures, coverage checks
5. **Code changes**: new files, refactoring, bug fixes
6. **Communication**: Slack messages, PR comments, Linear comments
7. **Process decisions**: user corrections, approach changes, manual overrides
8. **Configuration changes**: permissions, settings edits

For each action, note:
- What happened (brief description)
- Whether a skill was invoked (which one, or "none")
- Whether the user manually corrected the approach
- Look for `**[CORRECTION]**` markers in the transcript

Output a markdown table of actions.

---

#### Phase 2: Skill Coverage Analysis

For each action where NO skill was invoked:

1. Read SKILL.md files from `~/.claude/skills/*/SKILL.md`
2. Check "When to Use" / trigger sections
3. Classify as:
   - **MISSED**: A skill exists and should have been used
   - **CORRECT_SKIP**: No applicable skill, or action was too simple
   - **GAP**: A skill SHOULD exist but doesn't

---

#### Phase 3: Compliance Check

For each action where a skill WAS invoked:

1. Read the corresponding SKILL.md
2. Compare actual steps against documented workflow
3. Identify deviations:
   - **SKIPPED_STEP**: A documented step was skipped
   - **WRONG_ORDER**: Steps executed out of order
   - **EXTRA_STEP**: An undocumented step was added
   - **DEVIATED**: A step was done differently
   - **COMPLIANT**: Skill was followed correctly
   - **PLAYBOOK_SUBSTITUTION**: A REQUIRED delegation was
     replaced by a playbook override's inline `prompt:`.
     This is COMPLIANT — playbook overrides are valid
     substitutions for REQUIRED markers. Do NOT classify
     as SKIPPED_STEP when the playbook provides an
     equivalent inline implementation.

Assess each deviation: improvement, regression, or neutral?

**AskUserQuestion enforcement check:** When a SKILL.md documents
`AskUserQuestion` (or marks a step as `REQUIRED: AskUserQuestion`),
verify the session transcript contains an actual `AskUserQuestion`
tool call at that decision point — not a plain text question. If
the transcript shows the agent asked the question as inline text
instead of calling the tool, classify it as:
- **DEVIATED** with assessment **regression** — plain text
  questions don't block execution and lack structured options

**Orchestration formatting check:** For each invoked skill, scan its
SKILL.md for mandatory tool calls (`TaskCreate`, `TaskUpdate`,
`AskUserQuestion`, `Agent`, `Skill`) that appear inside fenced code
blocks in the Orchestration or decision gate sections. Per
`skill-orchestration-format.md`, code blocks are treated as examples
and agents may skip them. If the session shows missing task tracking
or bypassed decision gates, check whether the SKILL.md formatting is
the root cause. Classify as:
- **DEVIATED** with assessment **regression** if the code-block
  formatting caused the agent to skip a mandatory step
- **GAP** if the formatting is wrong but the agent happened to
  execute correctly anyway (lucky compliance, not guaranteed)

---

#### Phase 4: Permission Friction Analysis

**Forensic-only, secondary signal.** Runs when explicitly
requested or when Phase 1 reveals 5+ unmatched tool calls.
See "Permission Friction (Secondary)" above for when this phase
applies.

Identify tool calls that would have required user approval by comparing
them against the allow rules in `settings.local.json`. The JSONL format
does not explicitly tag permission prompts, so this phase uses pattern
matching: for every Bash, Read, Write, and Edit tool call in the
transcript, check whether it matches any existing allow rule.

**Step 4a: Inventory tool calls and match against allow rules**

Extract every Bash, Read, Write, and Edit tool call from the transcript.
For each, determine whether it matches any allow rule using the pattern
matching logic below.

**Allow rule format** (from `settings.local.json`):
```
"Bash(command-prefix:*)"   — matches if command starts with the prefix
"Read(/path/glob/**)"      — matches if file path matches the glob
"Write(/path/glob/**)"     — same for Write
"Edit(/path/glob/**)"      — same for Edit
```

**Matching algorithm**:
- `Bash(prefix:*)` matches if the command string starts with `prefix`
  (after stripping leading whitespace and env var assignments)
- `Read(/path/**)` matches if the file path starts with `/path/`
- Pipe chains: only the first command is matched against Bash rules

Record unmatched tool calls — these are the ones that would have
required a permission prompt.

Output a markdown table of all unmatched tool calls.

**Step 4b: Inline script detection**

Scan skills referenced during the session (`~/.claude/skills/*/SKILL.md`) for
inline shell content that should live in a `scripts/` file:

- Any `bash` or `sh` code block with 4+ lines, OR
- Any `python` code block used as a CLI one-liner (not as an example snippet), OR
- Any block that mixes curl/jq/awk/sed into a multi-step pipeline

For each candidate, note:

| Skill | Inline block (type + line count) | Suggested script path |
|-------|----------------------------------|-----------------------|
| `Dev10x:some-skill` | 12-line bash loop | already extracted ✓ |
| `some:skill` | 8-line curl + jq pipeline | `scripts/fetch-data.sh` |

Also scan the session transcript for Bash tool calls that were multi-step
(heredoc, `&&`-chained, or 5+ commands in one call) — these are candidates
for extraction to a skill's `scripts/` directory even if no skill currently
owns them.

Classification:
- **EXTRACT_TO_SKILL_SCRIPT**: Inline script is complex enough to warrant a
  `scripts/` file; the parent skill should be updated + a `Bash(...scripts/:*)`
  allow rule added
- **EXTRACT_TO_NEW_SKILL**: The script logic is reusable but no skill owns it
  yet; suggest creating a skill with a `scripts/` directory
- **ACCEPTABLE_INLINE**: Short utility snippet (≤3 lines) — leave as-is

**Step 4c: Command Pattern Toxicity Analysis**

For each unmatched tool call from Step 4a, check whether the friction is
**structural** (no allow rule can ever fix it) vs **missing** (just needs
a new rule). Structural friction needs skill updates and/or hooks.

**Toxicity categories:**

| Category | Pattern | Why Allow Rules Fail | Fix |
|---|---|---|---|
| `PREFIX_POISONED_SUBSHELL` | `VAR=$(cmd) && script "$VAR"` | Prefix becomes `VAR=`, not `script` | Pass args directly to script |
| `PREFIX_POISONED_CHAIN` | `mkdir -p /tmp && script` | Prefix becomes `mkdir`, not `script` | Let script create dirs, or Write tool first |
| `PREFIX_POISONED_ENVVAR` | `ENV=val command` | Prefix becomes `ENV=`, not `command` | Script sets env internally |
| `PREFIX_POISONED_GIT_C` | `git -C /path log` | `git -C` doesn't match `Bash(git log:*)` | Use CWD, avoid `-C` |
| `PREFIX_POISONED_COMMENT` | `# comment\ncommand` | `#` breaks all prefix matching | Use Bash `description` param |
| `HOOK_BLOCKED_RETRY` | `cat <<'EOF'...` or `echo >` | Hook rejects it; Claude retries anyway | Update skill to use Write + `-F` |
| `NUISANCE_APPROVE` | Safe command prompted 3+ times | Allow rule exists but pattern doesn't match | Widen existing rule or add new one |
| `UNNECESSARY_CD_WORKTREE` | `cd /worktree/path && command` | `cd` shifts prefix; CWD is already the worktree | Drop the `cd` — session is already there |
| `WORKTREE_CWD_NOT_SWITCHED` | Commands run in main repo after worktree creation | Worktree creation should switch CWD | Investigate `Dev10x:git-worktree` — CWD switch may have failed |

**Detection algorithm:**

1. **Subshell poisoning**: Scan for `$(...) &&`, `$(...);`, or
   variable assignments like `VAR=$(...) && ...` where the second
   command is a pre-approved script path.

2. **Chain poisoning**: Scan for `cmd1 && cmd2` where `cmd2` matches
   a skill script path but `cmd1` does not. The `&&` shifts the
   effective prefix to `cmd1`.

3. **Env var poisoning**: Scan for `KEY=value command` where `command`
   would match an allow rule but `KEY=` prevents matching. Exception:
   env var prefixes that ARE in the allow list (e.g.,
   `Bash(GIT_SEQUENCE_EDITOR=:*)`) are not toxic.

4. **`git -C` poisoning**: Scan for `git -C <path> <subcommand>`.
   The allow rule `Bash(git log:*)` won't match `git -C /foo log`.

5. **Comment prefix**: Scan for commands starting with `#` — breaks
   all allow-rule prefix matching.

6. **Hook-blocked retries**: Cross-reference unmatched commands against
   known hook rejection patterns from `~/.claude/settings.json`
   PreToolUse hooks and `~/.claude/hooks/*.py`. If a command matches
   a hook block regex, Claude should never have attempted it.
   Read the hook scripts to extract their block patterns:
   - `validate-bash-security.py` blocks: `cat >`, `cat <<`, `echo >`,
     `printf >`, shell command substitution inside eval
   - Other hooks: extract reject conditions from their source

7. **Nuisance approvals**: Commands that are safe, not structurally
   broken, but prompted because no allow rule covers them. Detected
   when the same command pattern appears 3+ times with no structural
   issue.

8. **Unnecessary `cd` in worktree**: Scan for `cd /path && command`
   where `/path` matches the session's CWD (from transcript header).
   If the session is in a worktree (`.git` is a file), `cd` into
   the worktree root is always redundant. Classification:
   `UNNECESSARY_CD_WORKTREE`. Fix: drop the `cd` prefix.

9. **Worktree CWD not switched**: After a `Dev10x:git-worktree`
   invocation in the transcript, check whether subsequent Bash
   commands target the new worktree path or still operate in the
   original repo. If commands use `cd <worktree>` or `git -C
   <worktree>` after creation, the CWD switch may have failed.
   Classification: `WORKTREE_CWD_NOT_SWITCHED`. Fix: investigate
   `Dev10x:git-worktree` skill.

**Output format:**

| # | Command (truncated) | Toxicity | Root Cause | Recommended Fix |
|---|---|---|---|---|
| 1 | `BASE=$(git merge...) && script` | PREFIX_POISONED_SUBSHELL | `$()` shifts prefix | Skill: pass `develop` directly |
| 2 | `cat <<'EOF'\n...\nEOF` | HOOK_BLOCKED_RETRY | hook blocks `cat <<` | Skill: Write + `git commit -F` |
| 3 | `mkdir -p /tmp && script` | PREFIX_POISONED_CHAIN | `&&` shifts prefix to `mkdir` | Skill: script creates own dirs |
| 4 | `git -C /work/myproject log` | PREFIX_POISONED_GIT_C | `-C` breaks `Bash(git log:*)` | Skill: use CWD |
| 5 | `pytest src/` (3x) | NUISANCE_APPROVE | No matching rule | Allow: `Bash(pytest:*)` |
| 6 | `cd /work/.worktrees/proj && pytest` | UNNECESSARY_CD_WORKTREE | CWD is already the worktree | Drop the `cd` |
| 7 | `git -C /work/.worktrees/proj log` after worktree create | WORKTREE_CWD_NOT_SWITCHED | CWD switch failed | Fix `Dev10x:git-worktree` skill |

**10. Wrapper discovery**: For each PREFIX_POISONED or chained
command finding, check whether a wrapper already exists that
encapsulates the toxic pattern:

| Wrapper source | How to check | Example |
|---|---|---|
| Git aliases | `git config --list \| grep alias\.` | `git develop-log` wraps `$(git merge-base develop HEAD)` |
| Fish functions | `ls ~/.config/fish/functions/` | `fish_func.fish` wrapping a pipeline |
| Claude tools | `ls ~/.claude/tools/` | `~/.claude/tools/helper.sh` |
| Skill scripts | `find ~/.claude/skills -name '*.sh'` | `scripts/fetch.sh` in a skill dir |

Classify each finding:

| Classification | Condition | Proposal |
|---|---|---|
| `USE_EXISTING_WRAPPER` | Wrapper found | MEMORY_UPDATE: document the wrapper invocation |
| `CREATE_WRAPPER_ALIAS` | No wrapper; git-related chain | Create git alias + MEMORY_UPDATE |
| `CREATE_WRAPPER_SCRIPT` | No wrapper; non-git chain | Create `~/.claude/tools/<name>.sh` + allow rule + MEMORY_UPDATE |

Add a **Wrapper Status** column to the output table:

| # | Command | Toxicity | Wrapper Status | Recommended Fix |
|---|---|---|---|---|
| 1 | `BASE=$(git merge-base develop HEAD) && git log` | PREFIX_POISONED_SUBSHELL | EXISTS: `git develop-log` | MEMORY_UPDATE: use `git develop-log` |
| 2 | `mkdir -p /tmp/out && ~/.claude/tools/export.sh` | PREFIX_POISONED_CHAIN | MISSING | CREATE_WRAPPER_SCRIPT: let script create dirs |
| 3 | `ENV=val ~/.claude/skills/foo/scripts/run.sh` | PREFIX_POISONED_ENVVAR | MISSING | CREATE_WRAPPER_SCRIPT: script sets env internally |

When wrapper exists, the primary recommendation is MEMORY_UPDATE
(not a new script or alias). The memory note should document:
- The toxic pattern that triggers it
- The correct invocation using the wrapper
- Where the wrapper lives (for reference)

When no wrapper exists, propose creating one AND a memory update
documenting it. For git aliases, reference `Dev10x:git-alias-setup`
as the canonical setup mechanism rather than proposing raw
`git config` commands.

**Recommendations per category:**

- **PREFIX_POISONED_***: First check wrapper discovery (step 8
  above). If a wrapper exists, propose MEMORY_UPDATE to use it
  and SKILL_UPDATE to teach the wrapper pattern. If no wrapper
  exists, propose creating one, then update the SKILL.md that
  teaches the broken pattern. Also propose a PreToolUse hook
  (via `/hookify`) to auto-reject the pattern with a helpful
  error message pointing to the wrapper.

- **HOOK_BLOCKED_RETRY**: Update the SKILL.md to use the correct
  pattern. No new hook needed (existing hook already blocks). Add a
  memory note so Claude stops attempting the blocked pattern.

- **NUISANCE_APPROVE**: Propose an allow rule (same as Step 4f).

**Hook proposal format** (for PREFIX_POISONED findings):

When proposing a new hookify rule, provide enough context for
`/hookify` to create it:

```
Proposed hook: prevent-subshell-in-script-calls
Trigger: PreToolUse (Bash)
Pattern: command contains $() && followed by a skill script path
Action: deny
Message: "Do not use $() before skill script calls — it breaks
  allow-rule prefix matching. Pass arguments directly to the script."
Source: TICKET-58 audit — 3 user corrections for this pattern
```

**Step 4d: Load existing permissions**

Read `~/.claude/settings.local.json` and any project-level
`~/.claude/projects/<encoded-path>/settings.local.json` to get the
current `permissions.allow` list.

**Step 4e: Match analysis**

For each permission prompt, determine why it wasn't pre-approved.
First check Step 4c toxicity results — toxic commands get a structural
classification. Non-toxic commands get a rule-based classification.

**Structural classifications** (from Step 4c — no allow rule can fix):

| Classification | Meaning | Example |
|---|---|---|
| **PREFIX_POISONED** | `$()`, `&&`, env vars, `git -C`, or `#` shifts the effective prefix | `BASE=$(...) && script` |
| **HOOK_BLOCKED** | An existing PreToolUse hook rejects this pattern | `cat <<'EOF'` blocked by validate-bash-security |
| **NUISANCE_PATTERN** | Safe command prompted 3+ times, structurally OK but tedious | Same `uv run` variant 4 times |

**Rule-based classifications** (fixable with allow rules):

| Classification | Meaning | Example |
|---|---|---|
| **MISSING_RULE** | No allow rule covers this command/path at all | `pytest` not in allow list |
| **PATTERN_TOO_NARROW** | A rule exists for similar commands but the glob pattern doesn't match this invocation | `Bash(git log:*)` exists but `git -C /other/path log` was used |
| **PREFIX_MISMATCH** | The command starts differently than the allow pattern expects | `uv run pytest` vs `pytest` |
| **PATH_NOT_COVERED** | A Read/Write/Edit rule exists but doesn't cover this path | `Read(/work/myproject/**)` missing |
| **CORRECTLY_PROMPTED** | The command is risky and SHOULD require approval | `git push --force`, `rm -rf` |

**Priority**: Structural classifications take precedence. If a command
is PREFIX_POISONED, do NOT also classify it as PATTERN_TOO_NARROW —
the root cause is the prefix, not the rule width.

**Step 4f: Generate recommendations**

Route each finding to the right fix type based on classification:

**1. NUISANCE_APPROVE / MISSING_RULE / PATTERN_TOO_NARROW / PREFIX_MISMATCH / PATH_NOT_COVERED → Allow rule**

Propose a specific allow rule:

```
Current: (none)
Proposed: Bash(pytest:*)
Reason: pytest is a safe read-only test runner, prompted 3 times
```

Group related proposals (e.g., all `uv run` variants) into a single
recommendation. Prefer broader patterns that cover foreseeable variants
over exact-match rules, but never propose patterns that would also
pre-approve destructive commands.

**Safety guardrails — never propose allow rules for:**
- `git push`, `git reset --hard`, `git clean`, `git checkout .`
- `rm -rf`, `rm -r` on non-temp paths
- Commands that write to production databases
- Commands that send messages (Slack, email) without review
- `--force`, `--no-verify`, `--hard` flags

**2. PREFIX_POISONED → Wrapper discovery + skill update + hook**

For each PREFIX_POISONED finding, run wrapper discovery (4c step 8)
first, then route based on result:

**2a. Wrapper exists (`USE_EXISTING_WRAPPER`):**
1. Propose MEMORY_UPDATE documenting the wrapper invocation
2. Propose SKILL_UPDATE replacing the toxic pattern with the wrapper
3. No new hook or script needed — the wrapper already solves it

**2b. No wrapper exists (`CREATE_WRAPPER_ALIAS` / `CREATE_WRAPPER_SCRIPT`):**
1. Propose creating the wrapper (alias via `Dev10x:git-alias-setup`
   or script in `~/.claude/tools/`)
2. Propose SKILL_UPDATE replacing the toxic pattern
3. Propose MEMORY_UPDATE documenting the new wrapper
4. If script: propose allow rule for the new path
5. Propose hookify rule to auto-reject the toxic pattern

**3. HOOK_BLOCKED → Skill update + memory note**

For each HOOK_BLOCKED finding:
1. Identify the skill that teaches the blocked pattern
2. Propose a skill edit using the correct alternative
3. Propose a memory note so Claude stops attempting the pattern
4. No new hook needed — the existing hook already blocks it

**4. CORRECTLY_PROMPTED → No action**

Risky commands should require approval. No recommendation needed.

**5. REDUNDANT_UV_PREFIX → Skill update**

For each REDUNDANT_UV_PREFIX finding:
1. Identify the skill or shell script that uses the prefix
2. Propose removing the `uv run --script` prefix
3. If the underlying Python script lacks the proper shebang or
   permissions, propose fixing those first

**Step 4g: Script Shebang and Invocation Audit**

Scan all Python scripts in `~/.claude/skills/` and `~/.claude/tools/`
for shebang and invocation hygiene. Also scan SKILL.md files and shell
scripts for redundant `uv run --script` prefixes.

**Convention**: Every Python script under `~/.claude/skills/` and
`~/.claude/tools/` MUST use the self-executing shebang pattern:

```python
#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["requests"]  # or [] for stdlib-only
# ///
```

**Detection algorithm:**

1. **Missing uv shebang**: Find Python scripts (`.py`) under
   `~/.claude/skills/` and `~/.claude/tools/` whose shebang is
   `#!/usr/bin/env python3` or `#!/usr/bin/python3` instead of
   `#!/usr/bin/env -S uv run --script`. Classification:
   `WRONG_SHEBANG`.

2. **Missing PEP 723 metadata**: Find scripts with the correct
   uv shebang but no `# /// script` block. Classification:
   `MISSING_PEP723`.

3. **Missing execute permission**: Find scripts that are not
   executable (`! -x`). Classification: `NOT_EXECUTABLE`.

4. **Redundant `uv run --script` prefix in SKILL.md**: Grep
   SKILL.md files for `uv run --script` invocations of scripts
   that already have the self-executing shebang. Classification:
   `REDUNDANT_UV_PREFIX`.

5. **Redundant `uv run --script` prefix in shell scripts**: Grep
   `scripts/*.sh` files for `uv run --script` invocations.
   Classification: `REDUNDANT_UV_PREFIX_SHELL`.

**Output format:**

| # | Script / Caller | Issue | Classification | Fix |
|---|---|---|---|---|
| 1 | `tools/some-script.py` | `#!/usr/bin/env python3` | WRONG_SHEBANG | Change to uv shebang + PEP 723 |
| 2 | `scripts/fernet-decrypt.py` | mode 644 | NOT_EXECUTABLE | `chmod +x` |
| 3 | `Dev10x:some-skill/SKILL.md` | `uv run --script ~/.claude/tools/...` | REDUNDANT_UV_PREFIX | Drop prefix |

**Recommendations:**

- **WRONG_SHEBANG**: Fix the shebang to `#!/usr/bin/env -S uv run --script` and add PEP 723 block.
- **MISSING_PEP723**: Add the `# /// script` block after the shebang.
- **NOT_EXECUTABLE**: Run `chmod +x <script>`.
- **REDUNDANT_UV_PREFIX**: Update the SKILL.md or shell script to call the Python script directly.
- **REDUNDANT_UV_PREFIX_SHELL**: Same as above but in `.sh` files.

---

#### Phase 5: Lessons Learned Extraction

Review user corrections and `[CORRECTION]` markers:

1. For each correction, determine:
   - What did Claude do wrong?
   - What did the user want instead?
   - One-off preference or repeatable pattern?
   - Which skill should encode this lesson?

2. Check memory directory for existing notes on the topic.

3. Classify each lesson:
   - **SKILL_UPDATE**: Add to an existing SKILL.md
   - **NEW_SKILL**: Warrants a new skill
   - **MEMORY_UPDATE**: Add to memory (not skill-specific)
   - **CLAUDE_MD_UPDATE**: Add to CLAUDE.md (global rule)
   - **NO_ACTION**: One-off, not worth persisting

---

#### Phase 6: Report Findings (REQUIRES USER CONFIRMATION)

**Forensic-only.** For lightweight audits, Phase 6 is replaced
by the inline disposition gate in Phase 0.

**Runs in main agent after Step 8 (collect and synthesize).**

Read all phase output files to gather the complete findings.
Merge them into a unified view before presenting the report.

**CRITICAL: Audit reports findings — it does NOT design solutions.**
The audit's job is to identify *what failed and why*. Proposing
SKILL.md edits, new MCP tools, or allow-rule strategies requires
project context that the auditor lacks. The implementor who picks
up the filed ticket designs the fix.

**Anti-pattern:** "Phase 6 recommends adding `Bash(gh:*)` to
allowed-tools" — this is a design decision, not a finding.
Instead report: "Skill X invoked `gh pr view` directly 3 times
(turns 12, 18, 24) because no MCP tool or allow-rule covered it."

**DO NOT:**
- Propose specific SKILL.md edits or diffs
- Recommend new MCP tools or allow-rule patterns
- Suggest architectural changes (e.g., "extract to a new skill")
- Modify any files (the audit is read-only)

**DO:**
- Report what happened (which skill, which step, which turn)
- Report what was expected (per SKILL.md orchestration)
- Report the gap (skipped, deviated, bypassed, missing)
- Include transcript evidence (turn numbers, tool calls)

1. Present each finding clearly:
   - Which skill and step failed or deviated
   - What happened vs what was expected
   - Evidence (transcript turn numbers, tool calls)
   - Classification (SKILL_UPDATE, GAP, SKIPPED_STEP, etc.)

2. Use AskUserQuestion to confirm filing issues (batch).

3. **REQUIRED: File a GitHub issue for every actionable finding.**
   After presenting the summary, iterate over all findings
   classified as SKILL_UPDATE, GAP, or SKIPPED_STEP. For each:
   - Invoke `Skill(Dev10x:ticket-create)` with:
     - Title: `[<classification>] <affected skill>: <short description>`
     - Body: finding classification, affected skill, description
       of the gap/deviation, and session evidence (turn numbers)
     - Do NOT include recommended fixes in the ticket body —
       the implementor designs the solution
   - Do NOT gate behind `AskUserQuestion` — filing is mandatory
   - Report all created issue URLs in the final summary

4. Generate a summary report:
   - Total actions reviewed
   - Skills invoked vs missed vs gaps
   - Compliance score (% of steps followed correctly)
   - Permission prompts: total, avoidable (count only, no rules)
   - Issues filed (with URLs)
   - Recommendations for future sessions (behavioral, not
     architectural — e.g., "invoke skill X before step Y")

---

#### Phase 7: Upstream Reporting (optional delegation)

**Runs in main agent after Phase 6 (forensic) or directly from
Phase 0 disposition (lightweight "Select & file now").**

Check whether any findings warrant reporting to the Dev10x
plugin maintainers.

**Sub-step A: Collect upstream-relevant findings**

Scan all findings from Phases 2–6 (forensic) or from the inline
Phase 0 analysis (lightweight) and select those that relate
to Dev10x plugin skills (under `~/.claude/plugins/`). Include:
- `SKILL_UPDATE`, `GAP`, `SKIPPED_STEP`
- `DEVIATED` with assessment `regression`
- `PREFIX_POISONED_*`, `HOOK_BLOCKED_RETRY`, `REDUNDANT_UV_PREFIX`

Exclude findings about user-local skills (`~/.claude/skills/`),
memory files, or `settings.local.json` — those are local-only.

If no upstream-relevant findings exist, mark Phase 7 completed.

**Sub-step B: Ask user whether to report**

**REQUIRED: invoke `AskUserQuestion` tool** (not a plain text
question) to ask whether to file upstream. Present the count
of upstream-relevant findings and two options: "File issue
(Recommended)" to delegate to `Dev10x:audit-file`, or
"Skip" to keep findings local only.

If the user selects **Skip**, mark Phase 7 completed and end.

**Sub-step C: Scrub findings before delegating**

**REQUIRED before writing the findings file.** The upstream
issue is public; the source session is treated as private by
default. Apply the replacement table, allow-list, and 5-step
algorithm in `Dev10x:audit-file` →
`references/privacy-scrub.md` to the findings text **before**
writing it to the temp file.

**Local-only sections** MUST be omitted from the findings file
entirely — they are private context, not signal for the
plugin maintainers.

If a finding cannot be reported without a private identifier,
mark it `[needs-user-decision]` in the findings file and let
`Dev10x:audit-file` Step 3 raise the `AskUserQuestion` gate.
Do NOT silently include unscrubbed text.

**Sub-step D: Delegate to Dev10x:audit-file**

Write the **scrubbed** findings summary to a temp file:

```bash
/tmp/Dev10x/bin/mktmp.sh skill-audit findings .md
```

Write the scrubbed upstream-relevant findings table and proposed
fixes to that file, then invoke:

```
Skill(skill="Dev10x:audit-file", args="<findings-file-path>")
```

The `Dev10x:audit-file` skill handles version detection,
issue body generation, and `gh issue create`. Mark Phase 7
completed after delegation returns.

---

## Important Rules

- **Read-only by default**: Only modify files after explicit user approval
- **Be specific**: Reference exact transcript turns and skill file lines
- **Prioritize impact**: Focus on deviations that caused real problems, not nitpicks
- **Respect intent**: If the user's correction was clearly better, update the skill.
  If it was situational, note it but don't change the default.
- **No duplicate memory**: Check existing memory/CLAUDE.md before proposing additions
- **Inline script extraction**: Phase 4b detects inline shell/python blocks in
  skill SKILL.md files and session Bash calls. For each `EXTRACT_TO_SKILL_SCRIPT`
  finding, propose: (1) moving the block to `~/.claude/skills/<skill>/scripts/`,
  (2) updating SKILL.md to call the script, (3) adding a
  `Bash(~/.claude/skills/<skill>/scripts/:*)` allow rule so future runs need zero
  approval prompts.
- **Structural before rule-based**: When analyzing permission friction, always
  check Step 4c toxicity first. A PREFIX_POISONED command should never get a
  "widen the allow rule" recommendation — the fix is the skill pattern, not
  the rule. Proposing allow rules for structurally broken commands is a false
  fix that will fail on the next invocation.
- **Hook proposals are skill-coupled**: Every hookify rule proposal must come
  with a corresponding skill update that teaches the correct pattern. A hook
  that blocks a bad pattern without showing the alternative just shifts the
  friction from "approve?" to "what now?".
- **Script shebang hygiene**: Phase 4g scans Python scripts for proper
  self-executing setup. All scripts under `~/.claude/skills/` and
  `~/.claude/tools/` must use `#!/usr/bin/env -S uv run --script` shebang
  + PEP 723 metadata + executable permission.
- **Prefer jq/yq over Python scripts**: When a hook or skill script
  only does JSON/YAML parsing, prefer `jq` or `yq` over inline
  `python3 -c "import json..."`. Flag Python one-liners that could be
  replaced with a single `jq`/`yq` invocation as `PREFER_JQ_YQ`.
- **Upstream reporting scope**: Phase 7 only considers findings
  about Dev10x plugin skills (under `~/.claude/plugins/`). User-
  local skills, memory updates, and permission rule changes are
  local-only and never filed upstream.
- **Delegation over embedding**: Phase 7 delegates issue filing to
  `Dev10x:audit-file` rather than implementing it inline. This
  keeps skill-audit focused on analysis and lets users who don't
  want upstream reporting skip the skill entirely.
- **Source session is private by default**: Audit reports MUST NOT
  disclose information about non-public repositories, projects,
  branches, ticket trackers, file paths, hostnames, or people.
  Scrub all such identifiers in Phase 7 sub-step C before they
  reach the upstream issue body.
- **Friction is secondary**: Do not expand a lightweight friction
  observation into a full Phase 4 forensic wave. Capture it as a
  `friction-note` bullet and queue for lightweight filing.
