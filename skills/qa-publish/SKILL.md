---
name: Dev10x:qa-publish
description: >
  Publish a finished QA run to the ticket and the PR as a readable verdict
  with a watchable video and inline screenshots — instead of raw files left
  in a temp directory, a ticket comment that never reaches Jira watchers, or
  evidence that silently claims coverage the run never had.
  TRIGGER when: a QA run has produced screenshots and a screen recording and
  the results need to reach a ticket and a PR.
  DO NOT TRIGGER when: executing the QA test cases (use Dev10x:qa-self),
  analyzing a PR for QA needs (use Dev10x:qa-scope), or publishing a single
  video with no ticket write-up (use Dev10x:yt-upload directly).
user-invocable: true
invocation-name: Dev10x:qa-publish
allowed-tools:
  - Bash(${CLAUDE_PLUGIN_ROOT}/skills/qa-self/scripts/:*)
  - Bash(${CLAUDE_PLUGIN_ROOT}/skills/yt-upload/scripts/upload-video.py:*)
  - AskUserQuestion
  - mcp__plugin_Dev10x_cli__pr_issue_comment
  - mcp__plugin_Dev10x_cli__issue_comment_edit
  - mcp__plugin_Dev10x_cli__pr_get
  - mcp__linear-server__list_comments
  - mcp__linear-server__save_comment
---

# Dev10x:qa-publish — QA evidence to the ticket and the PR

The composition layer over the pieces that already exist. This skill owns
**where evidence goes and what the write-up says**; it owns no conversion,
no upload mechanics, and no capture.

| Concern | Owner |
|---|---|
| Capture, convert, verify, local review gate | `Dev10x:qa-self` + its `scripts/` |
| Narration audio | `Dev10x:tts` |
| Video → shareable link | `Dev10x:yt-upload` |
| Screenshots → Linear assets | `qa-self/scripts/upload-screenshots.py` |
| Verdict, destinations, threading | **this skill** |

Do not re-implement any row you do not own. In particular there is no
evidence-normalization script here: `qa-self/scripts/convert-evidence.sh`
already converts PNGs to JPGs and `.webm` to `.mp4`, and a second converter
would drift from it.

## Read the results before writing anything

**Never write a verdict from an exit code alone.** Open the run's results and
read what actually happened, per test case.

If any case FAILED or was BLOCKED, say so plainly and **do not publish a
pass**. A QA comment that overstates coverage is worse than no comment: it
retires a question that was never answered.

Honesty rules for the write-up:

- Never report a pass for a path the run did not exercise.
- Name fixture mismatches — what the run used vs. what production has.
- List the paths the run did **not** cover, rather than leaving their absence
  to be inferred.
- State that a robot ran it, unattended, so a reader can weight it.
- Flag any irreversible side effect the run caused.

## Workflow

### 1. Confirm the local review gate already passed

This skill publishes to **external, append-only destinations**. It must not
be the first thing to look at the artifacts.

`Dev10x:qa-self` Phase 4.4 is that gate. When this skill is invoked without it
having run in the current session — a direct invocation on an old run
directory, say — run the review here instead: report each artifact's path,
size and duration, and read the sampled frames.

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text) before anything
leaves the machine. This blocks until the supervisor responds. Options:

- **Approve — publish to the ticket and PR (Recommended)** — the artifacts
  show what the test cases claim.
- **Re-capture** — something is missing, blank or unfollowable; run
  `Dev10x:qa-self` again rather than publishing a bad take.
- **Abort** — stop without publishing anything.

Never publish first and ask after. Note this gate covers *this* skill's
destinations; `Dev10x:yt-upload` still fires its own provenance gate, because
approving that the footage is good is a different decision from approving that
it may become world-readable.

### 2. Resolve the one video to publish

```bash
${CLAUDE_PLUGIN_ROOT}/skills/yt-upload/scripts/upload-video.py \
  resolve-video --run-dir <RUN_DIR>
```

Returns the chosen artifact, whether it is the narrated take, and
`narration_defects`. A narrated run writes `-narrated.mp4` beside the silent
take and deletes nothing — publish one or the other, never both.

Surface any `narration_defects` before publishing. Captions that played with
no audio, or an `install` anchor offsetting every cue, matter more here than
on a ticket: an unlisted URL is readable by whoever holds it.

### 3. Publish the video

**REQUIRED: delegate to `Dev10x:yt-upload`.** It owns the
production-recording gate, the token handling, and the channel assertion — do
not shell out to `gog` or restate upload mechanics here.

Title it `<TICKET> — <what the viewer will see>`, not `<TICKET> QA video`. The
title is the only context a reader gets before pressing play.

Keep both returned forms. `linear_markdown` (bare watch URL) goes to the
ticket; `github_markdown` (linked poster) goes to the PR. They are not
interchangeable — see
[`../yt-upload/references/destinations.md`](../yt-upload/references/destinations.md).

### 4. Publish the screenshots, per destination

Screenshot hosts do not cross over, so each destination needs its own copy:

- **Ticket** — upload as Linear assets via
  `qa-self/scripts/upload-screenshots.py upload <files...>`, then inline the
  returned `uploads.linear.app` URLs. [Verify] These are reported to 401 for
  anyone on GitHub (field report, not verified here — see
  [`../yt-upload/references/destinations.md`](../yt-upload/references/destinations.md)).
- **PR** — do **not** link the Linear assets. Attach or link images GitHub can
  actually fetch, or reference the video instead and keep the PR comment
  short.

### 5. Post to the ticket — thread it when the issue is Jira-synced

A Linear issue synced to Jira carries a null-author anchor comment marking the
sync. A **top-level** comment on such an issue never reaches Jira watchers.

Check `list_comments` for that anchor first; when present, post with its id as
`parentId` so the write-up actually reaches the people watching in Jira.

### 6. Post to the PR — short, and linked rather than duplicated

Resolve the target PR with `pr_get` before posting — in a multi-worktree
setup the PR that matters is not reliably the one for the current branch, and
a QA verdict on the wrong PR is worse than a missing one.

The PR comment is not a second copy of the ticket write-up. It carries:

- **a fixture-vs-production caveat, when one applies — above the video**;
- the verdict, in one line;
- anything the PR flagged as unknown that this run answered;
- the video, as the linked poster frame;
- at most the two or three screenshots that carry the argument;
- a link to the ticket comment for everything else.

**REQUIRED when the fixture's flags, labels, or settings differ from
production: lead with the caveat.** A fixture is picked for convenience
and its flags are incidental, so a walkthrough can show UI no production
user will ever see — and no existing gate catches it: every one asks
whether the artifact is well-formed, never whether the configuration is
representative. Enumerate the flags in force on the fixture and compare
them to production before publishing.

Use a GitHub `> [!IMPORTANT]` alert callout, above the video — a
trailing note is what gets skimmed past. Name all three of: **what**
differs, **why** (the specific flag), and **what in the video is still
trustworthy**. A caveat that only casts doubt makes the artifact
unusable.

**One QA comment per PR.** A re-record produces a new YouTube id, and
`Dev10x:yt-upload` cannot delete the superseded upload (#1206). On a
re-record, edit the existing comment in place via
`mcp__plugin_Dev10x_cli__issue_comment_edit` with the new
`github_markdown` — never post a second comment, or the PR ends up
carrying poster frames that point at dead videos.

`Dev10x:yt-upload` returns `thumbnail_may_404: true`: YouTube needs a
minute or two to generate `maxresdefault.jpg`, so a comment posted
immediately shows a broken image. It resolves itself — do not "fix" a
correct embed.

Callout template, the dealer-label join the flag check needs, and the
reasoning: [`references/pr-comment.md`](references/pr-comment.md).

### 7. Do not change the ticket status

An open PR means the work is not done. Moving the ticket is the owner's call,
not the publisher's.

## Anti-patterns

- **Publishing before the review gate.** External destinations are
  append-only; a bad take can only be superseded, never withdrawn.
- **One markdown for both destinations.** There is no form that renders in
  both Linear and GitHub. Using one is how a poster ends up broken or a URL
  ends up unclickable.
- **Re-implementing conversion.** `convert-evidence.sh` owns it.
- **A caveat as a trailing note.** Below the video it reads as a footnote
  and gets skimmed; the reader has already drawn the wrong conclusion.
- **A second QA comment for a re-record.** The old comment's poster frame
  keeps pointing at a video that cannot be taken down. Edit in place.
- **Writing to a Linear comment after handing it to a human to embed.** A
  later API write silently overwrites their edit.
- **A verdict derived from the exit code.** Read the per-case results.
