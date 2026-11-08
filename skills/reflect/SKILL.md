---
name: dev10x:reflect
invocation-name: dev10x:reflect
user-invocable: true
description: >
  Collect what a finished stretch of work taught — about the solution,
  the platform it runs on and the way the team works — into the
  configured knowledge vault, so the next session finds it instead of
  losing it with the transcript.
  TRIGGER when: a play reaches its final reflect step after Verify
  acceptance criteria, or the user says "reflect", "lessons learned",
  "retro this session" or "store this in the vault".
  DO NOT TRIGGER when: work is still mid-flight (finish it first), or
  the user only wants open loops parked (use dev10x:session-wrap-up).
allowed-tools:
  - AskUserQuestion
  - Bash(uvx dev10x skill reflect:*)
  - Bash(dev10x skill reflect:*)
  - Bash(rg:*)
  - Bash(obsidian:*)
  - Edit(~/.claude/projects/**/memory/**)
---

# dev10x:reflect — Lessons Into the Knowledge Vault

**Announce:** "Using dev10x:reflect to collect this session's lessons
into the knowledge vault."

Reflection prompt, keep/drop filter, placement map and retro template:
[`references/guide.md`](references/guide.md). Config keys:
[`references/configuration.md`](references/configuration.md).

## Orchestration

**REQUIRED: Track exactly one reflect task.** Execute at startup:

1. `TaskList` — when a play created the step, an open task named
   `Reflect lessons into the knowledge vault` already exists.
2. If it exists, `TaskUpdate(taskId=<its id>, status="in_progress")`
   and use it. Otherwise (standalone invocation)
   `TaskCreate(subject="Reflect lessons into the knowledge vault", activeForm="Reflecting")`.

Never create a second reflect task beside the play's: the leftover
pending one would keep the Stop gate from seeing Verify AC as the only
open task. Mark the task `completed` on **every** exit — after Step 6,
after the Step 0 skip, and after a Step 0 config error.

**Never close Verify AC from here.** As a play's final step this skill
runs *after* `dev10x:verify-acc-dod` has reported, while the terminal
"Verify acceptance criteria" task stays open for the supervisor
(GH-149). Reflection is non-blocking: it finishes or skips within the
turn and never holds the plan open. If this task would be the last
open one (a play with no Verify AC, e.g. `investigation`), first create
`Verify acceptance criteria` (Task List Invariant, GH-149), then
complete this task — the task guard refuses to close the last open
task.

## Step 0: Resolve the vault

```bash
uvx dev10x skill reflect config
```

- `configured: false` → print exactly one line,
  `Reflection skipped: <reason>`, complete the task and stop. An
  unconfigured vault is a supported setup, not a failure.
- An `error` key → print `Reflection skipped: <error>` as one line,
  complete the task and stop; the config file has a typo the user
  should fix (`references/configuration.md`). A broken config must not
  hold the plan open.
- Otherwise keep `vault`, `folders`, `log_folders`, `index_note`,
  `log_note` and `rules_note`. When `rules_note` is set, Read it before writing: the
  vault's own conventions (front matter, naming) win over the template.

## Step 1: Answer the reflection prompt

Work through `references/guide.md` § Reflection prompt against the
transcript, not memory of it. Write the answers down before choosing a
file. Sort every answer into **durable lesson** (true next month for
someone else) or **session trivia** (drop it) using § Keep or drop.

## Step 2: Route each lesson

Map each lesson to a folder kind via § Placement map, then to a folder
through `folders` from Step 0. Before creating a note, search for an
existing one — Obsidian CLI when it is running, else `rg`:

```bash
obsidian search query="<key term>" format=json
rg -l -i "<key term>" "<vault>/<folder>"
```

An existing note on the topic gets an **update**, not a sibling.
Appending a dated finding needs no approval. Rewriting a claim someone
else wrote is a decision:

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text) when a
lesson contradicts an existing note. Options:
- Append a dated correction (Recommended) — keeps the original claim
  visible with the evidence that overturns it
- Rewrite the claim — replace it in place
- Leave the note — record the conflict in the retro only

**Unattended mode** skips this gate and takes the recommended option.
It applies only when **both** hold, the same test `dev10x:git-commit`
uses:

1. The skill was invoked via `Skill(dev10x:reflect)` by an
   orchestrator, not typed by the user as `/dev10x:reflect`.
2. The caller is executing a plan step with an active task list (the
   `Reflect lessons into the knowledge vault` task from a play).

When either is absent, or you cannot tell, ask. The recommended option
never deletes anything, so taking it unattended loses no information.

## Step 3: Write the retro

One `Session Retro` note in the `retro` folder, from § Retro template.
New file, unique name — use Write. The vault path is configuration, so
no `allowed-tools` entry can pre-approve it: the first write prompts
unless the user allows `Edit(<vault>/**)` in their own settings. Rules
the template does not enforce:

- Cite code as `repo path:line`, data as the query that proved it.
- Every claim not checked in this session carries `[Verify]`, and the
  note stays `status: draft` while any remain.
- Name people by role. No secrets, tokens, customer data or personal
  contact details — the vault is often synced and shared.

## Step 4: Spin out general patterns

A lesson that names a reusable technique, beyond this project, gets its
own note in the `patterns` folder, linked both ways with the retro.

## Step 5: Index and log — through the CLI only

Shared folder notes are edited by every session that reflects. Never
Write or Edit them directly; the CLI locks, re-reads and is idempotent:

```bash
uvx dev10x skill reflect index-add --folder "<folder>" --line "- [[<Note>]] — <one line>" --seed-listing
uvx dev10x skill reflect log-add --folder "<log folder>" --entry "<Retro|Pattern>: [[<Note>]] — <one line>"
```

`<log folder>` is `log_folders[<kind>]` from Step 0 — the note's own
folder unless the vault keeps one log higher up. Both commands reuse
the list marker the note already has, so pass `- ` regardless.
`log-add` reports `skipped` for a folder without a log note; pass
`--create` only when the vault's conventions call for one. A
symlinked index or log note is refused, not followed. Check every
link you wrote resolves to a real note.

## Step 5b: Agent memory

The vault is for people; agent memory is what the next session loads.
Behavior corrections the user made go to memory as feedback, never to
the vault. For each live state the session leaves behind (something
disabled, a deadline, a pending decision), add or update one project
memory with its "never do X" rule and the vault path of the retro. Do
not copy memory content into the vault.

## Step 6: Report

One line per file written or updated (vault-relative path + summary),
memory files included, then the open items the retro records.

## Common mistakes

| Mistake | What the next session loses |
|---|---|
| Only a pattern note | The platform map and gotchas — the part only this session has |
| New note when one on the topic exists | Two half-truths; search finds the stale one |
| Lesson written as narrative | "Then I tried X" is not reusable; write the rule and its evidence |
| Unverified claim without `[Verify]` | A guess read back as fact |
| Index or log edited with Write/Edit | A parallel session's line silently overwritten |
| Personal paths hardcoded in a note or skill | Config is the only place a vault path belongs |
| Closing Verify AC after reflecting | The supervisor's sign-off gate (GH-149) |
