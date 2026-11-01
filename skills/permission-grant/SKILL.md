---
name: dev10x:permission-grant
invocation-name: dev10x:permission-grant
description: >
  Use when a useful command keeps prompting and should be pre-approved
  everywhere at once — the global settings, every project and every
  worktree — so one decision ends the prompt in every session instead of
  one file at a time, and a command that a skill, a rewrite or a
  directory setting would fix better is never granted by accident.
  TRIGGER when: the supervisor says "pre-approve this", "allow this
  everywhere", or dev10x:diag-approval delegates a just-approved call.
  DO NOT TRIGGER when: the prompt came from a deny rule the supervisor
  chose (that is a decision, GH-972), or the goal is only to explain
  why a command prompted (use dev10x:diag-friction).
user-invocable: true
allowed-tools:
  - AskUserQuestion
  - mcp__plugin_dev10x_cli__permission_triage
  - mcp__plugin_dev10x_cli__permission_grant
  - Skill(dev10x:diag-approval)
  - Skill(dev10x:diag-friction)
---

# dev10x:permission-grant

**Announce:** "Using dev10x:permission-grant to triage `<target>` and
pre-approve it everywhere if nothing fixes it better."

## Orchestration

This skill follows `references/task-orchestration.md` patterns.

**REQUIRED: Create a task at invocation.** Execute at startup:

1. `TaskCreate(subject="Pre-approve <target> everywhere", activeForm="Pre-approving")`

Mark it `completed` on **every** terminal branch: each non-`grant`
verdict, Cancel, Dry run and a finished grant. End with a one-line
report naming the branch taken. A task left `in_progress` after an
early exit tells the supervisor work is still running when it is not.

## Why triage comes first

Granting is the last fix, not the first. The friction fix order is
*source > normalize > grant*. A grant that skips the order either
widens the allow list for a command that a skill already handles, or
writes a rule that can never match the command's shape. In the first
case the safer route goes unused; in the second the prompt survives
and the dead rule stays forever. `permission_grant` re-runs the triage
and refuses anything but a `grant` verdict, so the order holds even if
a step below is skipped.

## Workflow

### Step 1: Resolve the target

The target is the exact thing that prompted:

1. The skill argument, verbatim (`/dev10x:permission-grant rg -n foo ~/x`).
2. The value handed over by `dev10x:diag-approval`.
3. Neither present: delegate with
   `Skill(skill="dev10x:diag-approval")`, which owns picking the
   approved call from the conversation, and stop here. Do not guess a
   target; guessing grants the rule for the wrong call everywhere.

Pass a **Bash command as the full command string**, not as a rule you
built by hand. Triage needs the command's shape to spot chaining,
expansions and out-of-workdir reads. Pass an MCP tool by its full name
(`mcp__server__tool`) and a file read as `Read(<path>)`.

Collect the session's working directories as **absolute** paths: the
primary working directory plus every additional one the environment
lists. Pass them as `working_dirs`; relative entries are rejected.
Without them, a read inside an additional directory looks
out-of-workdir.

### Step 2: Triage

1. `mcp__plugin_dev10x_cli__permission_triage(target=<target>, working_dirs=[...], cwd=<primary working dir>)`

Act on `verdict`. Every branch except `grant` ends the skill without
writing anything:

| verdict | What to tell the supervisor |
|---------|-----------------------------|
| `refuse-sensitive` | DX014 keeps this prompt on purpose. Approve it case by case, or bless one exact probe in `sensitivity-exceptions.yaml` |
| `too-broad` | Quote `reason`. The rule would cover far more than the approved command; keep approving per use or name a narrower subcommand. A whole executable (`Bash(<exe>:*)`) is refused unless it is on the vetted list of read-only tools, so an unfamiliar one is offered as `Bash(<exe> <subcommand>:*)` instead (GH-1687). An interpreter (`lua`, `python3.12`, …) is refused at any depth, as is a command or rule naming an exec flag (`rg --pre`, `sort --compress-program`, `make --eval`/`-f`); advise a wrapper script or MCP tool (GH-1723) |
| `denied` | A deny rule names or sits inside this shape. Do not look for a spelling that dodges it (GH-972) |
| `use-alternative` | Name the route from `advice` (skill, MCP tool or alias) and use it from now on |
| `normalize` | Quote each `advice` line. The command needs rewriting; no rule can match its shape |
| `outside-workdir` | Offer the `additionalDirectories` entry or the `Read()` rule from `advice`. A Bash rule would not help |
| `already-allowed` | Every readable file covers it, so the prompt has another cause. Hand over with `Skill(skill="dev10x:diag-friction")`. When the supervisor only wants an earlier grant to reach new checkouts, run Step 3 with that one option: `remember=true` accepts this verdict and writes no settings file |
| `grant` | Continue to Step 3 |

On every verdict, also relay any "Repair or remove unreadable settings
file" line from `advice`: Claude Code cannot load those files either.

### Step 3: Confirm the grant

Reach this step on `verdict == "grant"`, which triage returns only
when `files_missing` is non-empty. That state is what makes granting
the recommended option.

The one exception is `already-allowed` when the supervisor asked for the
rule to reach new checkouts. Then offer only **Grant and remember for
new checkouts (Recommended)** and **Cancel**: there is no file to write,
and `remember=true` is the only call that accepts that verdict.

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text). Question:
"Pre-approve `<rule>` for `<target>` in <N> settings file(s)?
<reason>", followed by the `files_missing` paths. Options, in this
order:

1. **Grant everywhere (Recommended)**: write `<rule>` to every listed file.
2. **Grant and remember for new checkouts**: also record `<rule>` in
   `~/.config/Dev10x/granted-permissions.yaml`, which `ensure-base` and
   `seed-worktree` merge into the catalog, so worktrees and projects
   created later start with it (GH-1677).
3. **Dry run only**: show what would change and write nothing.
4. **Cancel**: leave every file as it is.

This gate does not go through `resolve_gate`. It guards a write outside
the repository that no gate toggle covers, so an auto-advance posture
must never skip it.

The `permission_grant` call that follows prompts once more, on purpose.
This gate is the decision: it shows the files and offers dry run and
cancel. The harness prompt is an independent backstop. It survives a
skipped gate, and because `rule` is a required argument, it shows the
exact rule being written. Do not remove either one as a duplicate.

### Step 4: Act on the choice

- **Cancel**: stop. Call no further tool.
- **Dry run only**: report `rule` and `files_missing` from the Step 2
  triage, then stop. Do not call `permission_grant`. It is unseeded, so
  calling it would prompt again for a call that writes nothing.
- **Grant everywhere**:
  1. `mcp__plugin_dev10x_cli__permission_grant(target=<target>, rule=<rule from Step 2>, working_dirs=[...], cwd=<primary working dir>)`
- **Grant and remember for new checkouts**: the same call with
  `remember=true`. Report `remembered.added`; `false` means the rule was
  already remembered.

  Report `granted`, `failed` and every line of `messages`, including
  the `REDIRECT (git-tracked)` lines. A git-tracked `settings.json` is
  never written; its rules go to the sibling `settings.local.json`. An
  `error` payload either carries the `triage` that refused the grant
  (report that verdict as in Step 2) or names the files that `failed`,
  in which case the rule landed everywhere else.

### Step 5: Verify (Grant everywhere only)

A write is a request, not a receipt. Re-run the triage:

1. `mcp__plugin_dev10x_cli__permission_triage(target=<target>, working_dirs=[...], cwd=<primary working dir>)`

Expect `already-allowed`. If any file is still listed in
`files_missing`, report it by path.

Then say plainly that the change reaches **future** sessions. Settings
files are read at session start, so the current session may keep
prompting until it is restarted.

## What this skill does not do

- It does not edit the plugin catalog. A rule that every Dev10x user
  should have belongs in `skills/upgrade-cleanup/projects.yaml` through
  a PR. File one with `dev10x:ticket-create`.
- It does not reach checkouts created after the grant unless the
  supervisor picks "remember". A new worktree is seeded from the catalog,
  not from sibling settings files (GH-1677). Remembered rules show as
  user-only in `dev10x permission catalog-diff`; remove one by editing
  `~/.config/Dev10x/granted-permissions.yaml`.
