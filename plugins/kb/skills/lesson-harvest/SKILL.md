---
name: dev10x-kb:lesson-harvest
invocation-name: dev10x-kb:lesson-harvest
user-invocable: true
description: >
  Turn pasted YouTube videos, web articles and Spotify podcast episodes
  into fact-checked lessons filed in the Obsidian vault, so what a
  developer learned from a talk or an episode can be found and reused
  instead of dying in the browser history.
  TRIGGER when: the user pastes one or many video, article or Spotify
  episode links (batches of 5-15 are normal) and wants lessons, quotes,
  a summary or a daily-note entry; when a source's claims need checking
  against published evidence; or when the user asks what their saved
  sources say about a topic, or which saved sources traveled.
  DO NOT TRIGGER when: the user wants this session's own lessons filed
  (use dev10x-tasks:reflect), or only wants a page's raw text.
allowed-tools:
  - AskUserQuestion
  - Bash(uvx dev10x skill kb:*)
  - Bash(dev10x skill kb:*)
  - Bash(obsidian daily:*)
  - Bash(obsidian search:*)
  - WebSearch
---

# dev10x-kb:lesson-harvest — Lessons From Any Source Into the Vault

**Announce:** "Using dev10x-kb:lesson-harvest to harvest lessons from
[N] source(s)."

Agent prompts and the verify rules: [`references/phases.md`](references/phases.md).
Note templates (daily section, people, topics, strategy lens):
[`references/vault-layout.md`](references/vault-layout.md).
Config keys and prerequisites: [`references/configuration.md`](references/configuration.md).

## Orchestration

**REQUIRED: Track the phases as tasks.** Run Phase 0 first — it only
reads config — then execute at startup:

1. `TaskList` — when a plan already holds these subjects, reuse them;
   never create a second copy beside a play's task.
2. For each subject still missing, `TaskCreate`:
   `Fetch sources`, `Extract insights`, `Verify checkable claims`,
   `Synthesize the note section`, `Persist into the vault`,
   `Index, people and topics`, `Apply the strategy lens`.
3. `TaskUpdate` each task to `in_progress` when its phase starts and to
   `completed` when it ends — a phase that skips (no vault, no place)
   is completed with its skip line in the description.

**REQUIRED: Keep the list non-empty (GH-149).** Before completing the
last open harvest task:

1. `TaskList` — when `Verify acceptance criteria` is already open (a
   play created it), leave it alone.
2. Otherwise `TaskCreate(subject="Verify acceptance criteria")` with a
   description listing the vault files written, every skip line and
   the claims left unchecked — a harvest has no PR, CI or review
   threads to report. Never mark it completed yourself.

Auto-advance between phases. The main session orchestrates and never
reads a transcript itself — a 20-minute video is ~600 lines and lands in
an insight agent's context, not yours.

| Phase | Who | Model | Why |
|---|---|---|---|
| 1 Fetch | one agent per URL, waves of ≤5 | `haiku` | mechanical: run fetch, report metadata |
| 2 Insight | one per long source; short ones grouped 4–6 | `opus` | judgment: lessons, quotes, checkable claims |
| 3 Verify | main session | — | WebSearch across the batch |
| 4 Synthesize | main session if Opus-class, else one `opus` agent | `opus` | one voice for the note |
| 5 Persist, 6–8 Index/People/Topics, strategy lens | main session | — | locked CLI writes + note edits |

**Single-source exception:** one link is cheaper inline than three
agents, so an Opus-class main session runs fetch, reads that one
record and does Phases 2 and 4 itself — the only case it reads a
transcript. Any other session keeps the `opus` agents. Phase 3 and
Phases 5–8 run as usual.

## Phase 0: Prerequisites and places

```bash
uvx dev10x skill kb config
```

1. An `error` key → print it and stop; the config has a typo.
2. `tools.obsidian.path` is null → stop and print its `install` text.
   Obsidian is required: the daily-note path and vault root come from it.
3. A tool needed by the batch's link kinds is null (`yt-dlp` for
   YouTube, `defuddle` for web, `whisper-ctranslate2` for Spotify) →
   print its install command and drop those links. Never `pip install`
   around it.
4. `configured: false` → harvest into the reply only (Phases 1–4) and
   print `Skipped vault phases: <reason>`.
5. Keep `hub`, `topics`, `people`, `strategy_hub`, `rules_note`. For
   each null place print one line when its phase is reached:
   `Skipped <Index|People|Topics|Strategy lens>: kb.<key> not configured`.
   When `rules_note` is set, Read it first: the vault's conventions win
   over the templates.

**Vault writes prompt.** The vault path is configuration, so no
`allowed-tools` entry can pre-approve reading or editing notes there:
the first Read/Edit asks unless the user allows `Edit(<vault>/**)` in
their own settings. `obsidian eval` (vault root, attachment folder) is
left unapproved on purpose — it runs arbitrary code in Obsidian.

## Phases 1–4: Fetch, insight, verify, synthesize

Follow `references/phases.md`. Fetch writes `<id>.txt` and
`<id>.meta.txt` per link through `dev10x skill kb fetch`; Spotify audio
is transcribed locally and can take minutes per episode. A Spotify
episode whose show has no public feed is reported unreachable — never
summarize it from its description as if it were heard.

Verification is part of the flow: at most 3 waves of ≤2 parallel
WebSearch queries for the whole batch, verdicts ✅ 🟡 ⚠️ ❌, and every
verdict keeps its source link.

## Phase 5: Persist

When the user wants the lessons saved (or a vault is configured and
they did not say otherwise), follow `references/vault-layout.md`
§ Daily note:

1. `obsidian daily:path` and the vault root; confirm today's note
   exists there before using it.
2. One call per source, in parallel:
   `uvx dev10x skill kb persist --id <id> --dest "<abs attachments dir>" --name "<Speaker - Title>"`
3. Read the daily note, then append the section with Edit. Never Write
   over it; keep every existing frontmatter key.
4. Build every link with `uvx dev10x skill kb link <from> <to> [text]`.

## Phases 6–8: Index, people, topics, strategy lens

Each runs only when its place is set, and every time Phase 5 ran:

- **Index** (`hub`): `uvx dev10x skill kb index --id <id> --name "<Speaker - Title>" --structure "<beats>" --note "<abs daily note>"`.
  Never edit the hub table by hand — the CLI keys rows by URL and locks.
- **People** (`people`): one note per speaker or author, facts only,
  self-reported claims marked as such (§ People). Find an existing
  note with `obsidian search query="<name>"` before creating one.
- **Topics** (`topics`): update or create topic pages and rewrite their
  `Current guidance` (§ Topics). A topic with one source stays a
  candidate.
- **Strategy lens** (`strategy_hub`): link changed `strategy` topics
  and log the change (§ Strategy lens).

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text) when a new
lesson contradicts a topic page's `Current guidance`. The page's
frontmatter `status` orders the options; draft guidance is this skill's
own synthesis, so a newer source may replace it:
- `verified`, missing or unknown: Record under Contradictions
  (Recommended) — keep both sources visible; Rewrite the guidance; Skip
  this lesson for the topic page. When `status` is missing or unknown,
  say so in the question.
- `draft`: Rewrite the guidance (Recommended) — the new source replaces
  the old advice; Record under Contradictions; Skip this lesson.

Either way every lesson stays under `Lessons by source`.

**Unattended mode** takes the recommended option without asking, and
only when **both** hold:

1. The skill was invoked via `Skill(dev10x-kb:lesson-harvest)` by
   another skill, not typed by the user.
2. The caller's plan holds an `in_progress` task that delegates to this
   skill — the tasks this skill created for itself do not count.

When either is absent, or you cannot tell, ask. Neither recommended
option drops a lesson, so taking it unattended loses no source.

## Corpus questions

"What did I save about X" / "which ones traveled": run Phase 0 to
locate the hub and topic pages, read them, and do not re-fetch. Re-run
fetch + index only when the question needs current reach numbers, and
say the old numbers were a snapshot.

## Report

Per source: title, kind, lesson count, verdicts. Then every vault file
written (vault-relative path), every skip line, topic pages created or
updated and whether any guidance changed, and the claims left
unchecked.

## Common mistakes

| Mistake | What the user loses |
|---|---|
| Reading transcripts in the main session (batch) | Context for the rest of the batch |
| More than 5 parallel fetch agents | YouTube throttling and captchas |
| Inverted tiers (opus fetch, haiku insight) | Opus prices for mechanical work, shallow lessons |
| A research workflow per source | Hours spent; 3 waves cover a daily batch |
| Skipping verification for "motivational" content | The 2–5 real claims in a batch go unchecked |
| Linking `/tmp` from a note | Dead links after the next reboot |
| Hand-typed links or `[[wikilinks]]` | Broken links where the name has spaces |
| Writing over the daily note | The day's earlier entries |
| Editing the hub table by hand | Duplicate rows and lost locking |
| A silent skip of an unconfigured place | The user never learns why a phase did nothing |
| A new Structure label or topic per source | A vocabulary that indexes nothing |
| Summarizing an unreachable Spotify episode from its blurb | Lessons nobody actually heard |
