# Vault Layout and Note Templates

The vault's own conventions (`rules_note` from config) win over these
templates. Every `[text](path)` in the templates below stands for the
output of `uvx dev10x skill kb link <from> <to> [text]` — never type a
relative path by hand; an unencoded space breaks it.

**Shared notes change under you.** The daily note, people notes, topic
pages and folder indexes are edited by every harvest and by the user.
Read each one immediately before its Edit, make the Edit one inserted
or replaced block, and never carry a note's text from an earlier Read
into a later Edit. The one exception is the `kb.hub` table note: only
`uvx dev10x skill kb index` writes it. The topic hub (in `kb.topics`)
and the strategy hub (`kb.strategy_hub`) are ordinary notes, edited by
the rule above.

Look notes up with `obsidian search query="<term>"` (scoped to the
folder in question) before creating one; a search hit is updated, not
duplicated.

## Daily note

1. `obsidian daily:path` returns a vault-relative path; the root comes
   from `obsidian eval code="app.vault.adapter.basePath"`. The reported
   path may be a template that does not match today's file — confirm
   the note exists before deriving its attachment folder from it.
2. The attachment folder is the vault's setting
   (`obsidian eval code="app.vault.config.attachmentFolderPath"`);
   `./Attachments` means a sibling of the note.
3. Persist each source, then Read the note and append with Edit.

Frontmatter: if the note has none, add `type`, `title`,
`description`, `tags`, `status: draft`, `generated: { by: claude/<model>,
at: <ISO datetime> }` and a `sources:` list. If it has frontmatter,
keep every key, bump `generated.at`, append to `sources`, and set
`status: draft` only when it is missing.

```yaml
sources:
  - id: <source-id>            # from fetch, e.g. yt-abc123, sp-…, web-…
    resource: <canonical url>
    title: <Speaker - Title>
    author: human:<speaker-slug>
  - id: <check-slug>           # one per Phase 3 verification source
    resource: <url>
    title: <page title>
```

Section template:

```markdown
## Harvested lessons — N sources

> [!note] Fact-check legend
> ✅ verified · 🟡 directionally supported · ⚠️ real but overclaimed ·
> ❌ false. Only concrete empirical claims were checked.

### [Speaker](<link to person note>) — hook of the source[^<source-id>]
<kind> · <duration or site> · <reach line> (snapshot <measured_at>)
- lesson bullets (verbatim quotes where they earn it)
- 🟡 *Checkable claim:* … (verdict + one-line reasoning)[^<check-slug>]
- [Transcript](<link>) · [Meta](<link>)

[^<source-id>]: [<Speaker - Title>](<canonical url>)
[^<check-slug>]: [<page title>](<url>)
```

Every verdict carries a footnote whose label is a `sources[].id`, so
the note stays cited after the chat is gone. A web article links its
`article.md` copy instead of a transcript.

## People

Only when `people` is set. One note per speaker or author — not for
people merely mentioned. Run `obsidian search query="<name>"` first
(the people folder with its subfolders, and the hub): a returning
speaker's note is updated, never duplicated.

- Facts only: this skill never writes an assessment of a person.
- Date the facts (`as of YYYY-MM-DD`); reach and credentials go stale.
- Credentials from a description are *self-reported*; carry over any
  Phase 3 verdict that bears on them.
- A speaker known only by channel or site gets a note under that name,
  saying so.

```markdown
---
type: Person
title: <Name>
description: <what they do or are known for (self-reported)>
tags: [person, source-author]
resource: <channel, show or site URL>
status: draft
generated: { by: claude/<model>, at: <ISO datetime> }
sources:
  - id: <source-id>
    resource: <canonical url>
    title: <Speaker - Title>
---

# <Name>

## Facts

As of <YYYY-MM-DD>. Self-reported in the source unless marked.

- what they do[^<source-id>]

## Saved sources

- <YYYY-MM-DD> [<day>](<link to daily note>) — [Title](<url>)

[^<source-id>]: [<Speaker - Title>](<canonical url>)
```

## Topics

Only when `topics` is set. The folder holds `index.md`, a hub note
listing the controlled topics with their status (`page` or
`candidate`), and one page per topic.

1. Read the topic hub; map each source's lessons to 1–3 existing
   topics before coining one.
2. Existing page → add one bullet per lesson under `## Lessons by
   source`, newest first:
   `- YYYY-MM-DD [<Name>](<person>) — <lesson> <verdict> · [MM-DD](<daily note>)[^<source-id>]`.
   Add the source to `sources`, bump `generated.at`, then re-read
   `## Current guidance` and rewrite it when the lesson refines or
   extends it. A contradiction goes to the gate in SKILL.md.
3. No page yet → create it once ≥2 saved sources share the topic: find
   the earlier source with `obsidian search query="<topic>"` across the
   hub and daily notes, seed the page with
   both, mark the topic `page` in the topic hub, and add it to the
   folder's `index.md`. One source keeps the topic a `candidate` row.

```markdown
---
type: Topic
title: <Topic>
description: <the question this page answers>
tags: [kb-topic]
status: draft
generated: { by: claude/<model>, at: <ISO datetime> }
sources: [...]
---

# <Topic>

## Current guidance

- 3–7 bullets: what to do, each pointing at the lessons below

## Lessons by source

## Contradictions

## See also
```

`status: verified` only after the user confirms the guidance.

## Strategy lens

Only when `strategy_hub` is set. Topics the topic hub flags `strategy`
are linked from that hub note. When a new lesson on such a topic
changes how the user's own work should be made, add one dated entry to
the log next to the strategy hub linking the topic page. Link the
topic page; never copy the lesson into the strategy hub.
