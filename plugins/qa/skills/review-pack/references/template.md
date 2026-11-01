<!--
Copy-paste template for a review pack.

Where this file goes: the configured evidence repo (review-pack.yaml),
at pack_path, e.g. packs/<TICKET>.md, with images beside it under
evidence_dir, e.g. evidence/<TICKET>/*.png.

Images MUST be relative links (../evidence/<TICKET>/shot.png). GitHub
renders those inline in the blob view for anyone with repo access,
private repos included.

Link THIS file's blob URL at the top of the PR body and in the review
request. Delete every instruction comment before publishing.
-->

# <TICKET> — <one line a non-engineer understands>

**PR:** <link> · **Ticket:** <link> · **Branch:** `<branch>`
**What this changes for the user, in one sentence:** <plain language>

---

## 1 · What changed

<!-- Same route, same data, same viewport. If a reviewer reads nothing
     else, this. -->

| Before | After |
|---|---|
| ![before](../evidence/<TICKET>/before.png) | ![after](../evidence/<TICKET>/after.png) |

<!-- One sentence on what to look at. Annotate the region if subtle. -->

**Video (<what it shows>, ~<m:ss>):**
<!-- Paste yt-upload's github_markdown here. If a piece was dropped under
     the fallback rule, say which and why, e.g.
     "No narration: TTS quota exhausted". -->

## 2 · Every surface I touched

<!-- One screenshot per state you changed, INCLUDING empty / loading /
     error / permission-denied. Backend: request/response pairs, data
     tables, mermaid diagrams, query plans. Say if a state is
     unreachable and why. -->

**<Surface name>**
![<what it shows>](../evidence/<TICKET>/<file>.png)

**Error state — <trigger>**
![<what it shows>](../evidence/<TICKET>/<file>.png)

## 3 · Test it yourself in 60 seconds

<!-- If this needs "set up the local stack", it has FAILED. Give a
     preview or staging URL. Name the exact seeded account. -->

1. Open <exact URL — preview deploy or staging>
2. Log in as `<seeded account>`
3. Go to <exact navigation path>
4. <exact click, then what you should see>
5. **Expected:** <the observable result>

**To see the bug this fixes:** <same steps against the base branch, and
what goes wrong>

## 4 · Already verified — please don't redo this

<!-- What tests PROVE, not how many there are.
     "72/72, and deleting the fix turns 9 red" >> "all tests pass". -->

- **Unit:** <n>/<n>. Mutation-checked: <what you broke, which tests caught it>
- **E2E:** <scenario names> — executed against <environment>, <n> runs, <flakes>
- **Browser QA:** <paths driven by hand, on what data>
- **Not verified / known gaps:** <name them — an honest gap beats
  confident silence>

## 5 · Where I need your judgement

<!-- The 1-3 real questions: product calls, trade-offs taken, things
     deliberately not done. Everything above exists so the reviewer can
     answer these quickly. -->

1. **<Question>** — <the trade-off, and what you'd do absent an answer>
2. **<Question>** — <ditto>

**Deliberately NOT in this PR:** <scope cut, and the ticket it went to>

---

<!-- Pre-send checklist — delete before publishing:
     [ ] Every image loads (open each one)
     [ ] The reviewer can open this repo (check, don't assume)
     [ ] Screenshots and footage are staging / seed data only
     [ ] Every video post-dates the last UI-changing commit
     [ ] Self-review loop clean on HEAD; E2E actually executed
     [ ] You drove it yourself and would call it great, not merely correct
-->
