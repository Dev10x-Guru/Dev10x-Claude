---
name: dev10x-qa:review-pack
description: >
  Build the review pack a human reviewer opens before the diff — the
  change shown in screenshots, video or before/after API evidence, a
  60-second test recipe, what is already verified, and the open
  judgment calls — so a reviewer understands, sees and can test the
  change without checking out the branch.
  TRIGGER when: requesting human review, flipping a PR out of draft,
  or asked to make a change "easy to review".
  DO NOT TRIGGER when: capturing a QA run (use dev10x-qa:qa-self),
  publishing a QA verdict to a ticket (use dev10x-qa:qa-publish), or
  assigning reviewers and notifying chat (use dev10x:request-review).
user-invocable: true
invocation-name: dev10x-qa:review-pack
allowed-tools:
  - Read
  - Write
  - AskUserQuestion
  - Skill(dev10x-qa:qa-self)
  - Skill(dev10x-qa:tts)
  - Skill(dev10x-qa:yt-upload)
  - Skill(dev10x-qa:qa-publish)
  - Skill(dev10x-qa:playwright)
  - Skill(dev10x:request-review)
  - Bash(gh repo view:*)
  - Bash(gh repo clone:*)
  - Bash(gh api repos/:*)
  - Bash(git add:*)
  - Bash(git commit:*)
  - mcp__plugin_dev10x_cli__pr_detect
  - mcp__plugin_dev10x_cli__pr_get
  - mcp__plugin_dev10x_cli__update_pr
  - mcp__plugin_dev10x_cli__push_safe
  - mcp__plugin_dev10x_cli__mktmp
  - mcp__plugin_dev10x_cli__resolve_gate
---

# dev10x-qa:review-pack — make reviewing effortless

**Announce:** "Using dev10x-qa:review-pack to build the review pack for [PR]."

The bar: a reviewer understands what changed, sees it, and knows how to
test it — **without checking out the branch**.
If they must clone, install, seed data and click around just to see the
change, the pack has failed.

This skill owns **what the pack says and where it lives**.
It owns no capture, narration or upload mechanics:

| Concern | Owner |
|---|---|
| Browser capture, cursor overlay, captions | `dev10x-qa:qa-self` (+ `dev10x-qa:playwright`) |
| Voice narration | `dev10x-qa:tts` |
| Video → unlisted link + per-destination embed | `dev10x-qa:yt-upload` |
| QA verdict to ticket and PR | `dev10x-qa:qa-publish` |
| Reviewer assignment + chat ping | `dev10x:request-review` |
| Pack content, hosting, PR link, pre-send gate | **this skill** |

## Configuration

Read `<Dev10x config>/review-pack.yaml` (the core `dev10x` plugin's
`references/config-resolution.md` gives the root per platform).
Repo-addressed, first matching `projects[].match_repo` wins, then
`defaults`:

```yaml
# ~/.config/Dev10x/review-pack.yaml
defaults:
  evidence_repo: example-org/review-evidence   # PRIVATE, reviewers can read
  evidence_branch: main
  pack_path: "packs/{ticket}.md"
  evidence_dir: "evidence/{ticket}/"
  ticket_links:                                 # same shape as release-notes
    GH: "https://github.com/example-org/app/issues/{number}"
    PAY: "https://linear.app/example-team/issue/{id}"
projects:
  - match_repo: "example-org/*"
    evidence_repo: example-org/review-evidence
```

There is **no built-in evidence repo** — a wrong default would publish
screenshots somewhere nobody chose.
Reviewer names are not configured here; `dev10x:request-review` reads
`github-reviewers-config.yaml`.

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text) when no
`evidence_repo` resolves and the pack carries images or video.
Options:

- **Name a private evidence repo and pin it (Recommended)** — write it
  to `review-pack.yaml` so the question is asked once.
- **Text-only pack in the PR body** — only when the evidence is text
  (API pairs, tables, mermaid); no images to host.
- **Stop** — hand back the local pack draft path.

## Workflow

1. **Resolve the PR** with `pr_detect` / `pr_get`.
   Confirm the repo — several repos share a number range, and a pack on
   the wrong PR is worse than none.
2. **Write the five sections** from
   [`references/template.md`](references/template.md), in order:
   1. *What changed, in one pair* — before/after, same route, same data,
      same viewport.
   2. *Every changed surface* — one shot per state touched, including
      empty, loading, error and permission-denied.
   3. *Test it yourself in 60 seconds* — exact URL, account, clicks.
      "Set up the local stack" fails this section.
   4. *Already verified — don't redo this* — what tests **prove**, not
      how many ("deleting the fix turns 9 red"), plus named gaps.
   5. *Where I need your judgment* — the 1–3 real questions.
3. **Produce the evidence** per
   [`references/evidence.md`](references/evidence.md): screenshots,
   backend forms (API pairs, data tables, mermaid, query plans, caller
   code), and a **video whenever the change happens in time** — a
   redirect, a reload, a timer, a drag.
4. **Commit each artefact as it is written** to the evidence repo (push
   with `push_safe`), not at the end. A file in `/tmp` is a draft.
5. **Link the pack at the top of the PR body** with `update_pr`, above
   the commit list.
   Link every PR, ticket and pack the pack names — never a bare
   identifier.
6. **Run the pre-send gate** below, then hand off to
   `dev10x:request-review`.
   With `--no-request-review` (pack only), the gate resolves as
   described below; stop after it and return the pack link: the
   caller requests review itself. The work-on self-QA step uses this,
   so its play's own review-request step stays the only one.

## Video — a full qa-self capture, never a silent screen recording

Every review video is a `dev10x-qa:qa-self` capture with **all three**:
a visible cursor (the qa-self overlay), an on-screen caption per step,
and `dev10x-qa:tts` voice narration muxed over it.
Publish through `dev10x-qa:yt-upload` (or `dev10x-qa:qa-publish` when a ticket
write-up is wanted too) — no hand-rolled upload or embed code.

**Fallback — external failures only.** When a piece fails for a reason
outside the recording — TTS balance or quota exhausted, a voice model
that will not load, a cursor overlay that errors in this environment —
try that piece **once**, then ship without it.
State the reason in the video description **and** in the pack's video
caption, e.g. *"No narration: TTS quota exhausted"*, so it is never
silently missing.
Never use this for a failure you caused: a broken script or a wrong
locator is a bug to fix, not a piece to drop.

**Staging footage only, never production** (`dev10x-qa:yt-upload` gates
this). Anything else in frame is your organisation's disclosure policy.

**Evidence expires with the UI.** When a later commit changes UI the
video shows — review fixes, redesign, copy — re-record before asking for
(re-)review.

## Where the pack lives

The requirement is **reviewer access, not public hosting**.

- Pack = one markdown file in the evidence repo, **beside its images**,
  referenced by **relative path** — GitHub renders those inline for
  anyone with repo access, private repos included.
- Inline rendering is **same-repo only**, so the PR body gets **one link
  to the pack**, never N cross-repo image links (they render broken).
- **Never** gists, public image hosts, or any public URL for a private
  product's screenshots.
- **Verify before sending:** open the pack, confirm every image loads,
  and check the reviewer can open the repo
  (`gh api repos/<owner>/<repo>/collaborators/<login>`). A 404 is worse
  than no link.

## Pre-send gate

A run that requests review does not do so until **all** hold (a
pack-only run hands the gaps on instead, as described below):

- [ ] Self-review loop (`dev10x:review`) reached a clean round on HEAD.
- [ ] E2E actually **executed** — name the scenarios and the environment.
- [ ] You drove it yourself and would call the experience great, not
      merely correct.
- [ ] Pack exists, is linked at the top of the PR body, renders, and the
      reviewer can open it.
- [ ] Every video post-dates the last UI-changing commit.
- [ ] Screenshots and footage are staging/seed data only.

On a run that requests review, **REQUIRED: Call `AskUserQuestion`**
(do NOT use plain text) when any box is unchecked. A pack-only run
follows the block below instead.
Options:

- **Fix the gap first (Recommended)** — finish the missing item, then
  re-run this gate.
- **Send with the gap stated** — the pack's section 4 names what is
  unverified and why.
- **Hold** — do not request review.

**With `--no-request-review`, open boxes are handed on — except the
staging box (GH-1878).** This run requests nothing — the caller's own
review step does that — so a hard-coded prompt here only stalls a
walk-away session. The self-QA step runs after the review loop, yet
fixups and grooming still move HEAD, so the first box is often
unchecked at that point. A gap handed on reaches the reviewer through
section 4 and the caller through its Verify-AC summary; the caller's
own review step decides whether to send.

1. **The staging box always asks.** When "Screenshots and footage are
   staging/seed data only" is unchecked — including when you cannot
   say where a frame came from — skip the resolver: a frame that may
   hold real data is a disclosure question no policy may wave
   through, even when nobody is watching. **REQUIRED: Call
   `AskUserQuestion`** with these options; sending such a frame with a
   stated gap is not offered:
   - **Fix the gap first (Recommended)** — re-capture on staging or
     seed data, then re-run this gate.
   - **Hold** — return without the pack link.
2. Otherwise call
   `mcp__plugin_dev10x_cli__resolve_gate(gate="artifact_preview", context={})`
   and branch on `effect`:
   - `ask` — **REQUIRED: Call `AskUserQuestion`**.
     Say in the question that handing gaps on is this mode's default,
     not a judgment of these boxes, and list **Send with the gap
     stated (Recommended)**, **Fix the gap first**, **Hold**.
   - an `error` key — **REQUIRED: Call `AskUserQuestion`** with the
     same three options in the same order. Say in the question that
     the resolver failed, so this mode's default could not be
     resolved; Send leads only because a pack-only run hands gaps on.
   - `auto-advance` — take **Send with the gap stated**, the option
     the resolver's `record` line calls "Recommended".
   - `skip` — take **Send with the gap stated** without a prompt.
     `skip` returns no `record` line, so there is none to cite.

   However it is chosen, *Send* writes each unchecked box into
   section 4 and prints the unchecked list, plus the `record` line on
   `auto-advance`; *Fix* finishes the item and re-runs this gate;
   *Hold* returns without the pack link.

## Anti-patterns

- **Screenshots scattered across the PR body** — N clicks, no narrative.
- **"All tests pass"** — says nothing about what the tests prove.
- **A video of a stale build** — assert the change is on the wire
  (grep the served bundle) before filming.
- **A caption that is false for the frame it plays over** — worse than
  no caption; check each one against its frame.
- **A silent, cursorless recording** shipped without a stated reason.
