# Producing review-pack evidence

Loaded by `dev10x:review-pack` step 3.
Each rule here was learned from a pack that failed without it.

## Screenshots

- Drive the real UI with `dev10x:playwright` / `dev10x:qa-self`,
  full-page, at a sane viewport.
  Never mock a screenshot; never crop away the context that makes it
  readable.
- Before and after must be the **same route, same data, same viewport** —
  otherwise it is two pictures, not a comparison.
- Annotate the changed region (box or arrow) when the diff is subtle.
- A static shot cannot show an interaction.
  Drag, reorder, live preview and anything that unfolds over time need a
  video (below).
- A state you changed but did not screenshot is a state nobody reviewed.
  If a state is unreachable, say so and why.

## Backend PRs get packs too

No pixels is not an exemption.
The five sections stay; the evidence changes form:

| Change | Evidence |
|---|---|
| API behaviour | The actual request and response, verbatim, before and after, against seeded data. The error that used to escape vs the one now returned is a screenshot in text form. |
| Persistence | Rows before, rows after, ids visible, seeded account named. A six-row markdown table beats three paragraphs. |
| Flow or ordering | A mermaid `sequenceDiagram` / `flowchart` of old vs new order. GitHub renders mermaid inline, like an image. |
| Performance claim | `EXPLAIN ANALYZE` (or the profiler's equivalent) before and after, trimmed to the lines that changed. |
| Caller-facing API | A caller before and after, not a description of the difference. |

Test-it-yourself for backend = an exact `curl` or GraphQL query the
reviewer can paste against staging, with the seeded account named — the
same 60-second bar.

## Video mechanics

Capture through `dev10x:qa-self`; its `instructions.md` owns the
overlay, captions, narration hook and evidence verification.
The pack-specific rules:

- **Assert the change is on the wire before filming.**
  Grep the served bundle (or hit the endpoint) for the thing you changed.
  A video of a stale build looks exactly like evidence.
- **Assert your locator matches the real control.**
  An icon-only button whose accessible name lives in a tooltip will not
  match a locator written from its visible label — and the resulting
  false negative reads as "the feature is broken".
- **`context.close()` before `browser.close()`**, or the video file is
  never finalised.
- **Commit each take as it is written.**
  A finished recording that lived only in `/tmp` does not survive a
  reboot; committed artefacts do.
- **Caption with what it shows and how long** — *"Two scenarios, ~1:40"*
  beats *"video"*.
  The reviewer is deciding whether to spend two minutes.
- **Cut, then contact-sheet.** Trim dead time, then sample frames and
  check every caption against the frame it plays over.
  A caption that renders perfectly and asserts something false passes
  every automated check — only watching catches it.
- **State in the video description that it is a staging capture.**

### The fallback rule, in detail

The three pieces are cursor, captions and narration.
A piece may be dropped only when it fails for a reason **outside the
recording**:

| Drop allowed | Drop NOT allowed |
|---|---|
| TTS provider out of balance or quota | Narration script has a syntax error |
| Voice model will not load on this host | Wrong voice name typed |
| Cursor overlay errors in this browser build | Clicks bypass the annotator (`locator.click()` instead of `anno.click()`) |

Procedure: try the failing piece once; if it fails again for the same
external reason, record without it; put the reason in the video
description and the pack caption (*"No cursor overlay: overlay script
fails on this browser build"*).
The second column is a bug — fix it and re-record.

## Embeds, per destination

`dev10x:yt-upload` returns both forms; use the one for where you paste.
See [`../../yt-upload/references/destinations.md`](../../yt-upload/references/destinations.md).

- **GitHub** (PR body, pack) — the linked poster frame
  (`github_markdown`). GitHub strips iframes.
- **Linear** — the bare watch URL (`linear_markdown`). Its editor builds
  the player at paste time.

The poster frame 404s for the first minutes after upload; probe it, and
post a plain link first if it is not ready.

## Hosting, in detail

- The pack's images are relative paths
  (`![row shows Auto](../evidence/GH-42/02-row.png)`), committed beside
  the pack in the evidence repo.
- The PR body carries **one** link to the pack's blob URL.
  A picture *inside* the PR body works only when the image lives in the
  **PR's own repo**; a cross-repo private image renders broken, because
  the raw host needs a token the reviewer's browser does not send.
- Check the evidence repo's visibility with
  `gh repo view <owner>/<repo> --json visibility` before the first
  commit.
  A public evidence repo is a public screenshot host.
- Link-check what you wrote: every PR, ticket and pack reference is a
  URL, built from `ticket_links` for tickets.
  Confirm a PR link's repo with `pr_get` before writing it.
