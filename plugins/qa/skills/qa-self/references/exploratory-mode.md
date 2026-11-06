# Exploratory Mode — QA a Pull Request Without a QA Ticket

The default qa-self run executes test cases written on a QA ticket.
Exploratory mode is the entry the work-on shipping pipeline uses
(GH-1827): a pull request that changes user-facing behavior gets one
self-QA pass and one narrated video before review is requested, even
when nobody wrote a QA ticket for it.

Invoke it as `Skill(dev10x-qa:qa-self, args="--exploratory <PR>")`.
The PR may be a number, a URL, or omitted to use the current branch's
PR.

## What changes from the ticket-driven run

| Phase | Ticket-driven run | Exploratory run |
|-------|-------------------|-----------------|
| 1.1 Read the QA ticket | Test cases from the ticket | Cases derived from the `dev10x:qa-scope` report and the PR diff |
| 1.2 Verify deployment | Staging image or deployed branch | Same check, or a local stack running the PR head |
| 2–3 Script and execute | One test per ticket case | One walkthrough per changed surface, plus one unscripted probe of edge states |
| 4 Prepare evidence | Screenshots and video | Same, and the video is **narrated** (see the external-failure fallback below) |
| 4.4 Evidence review gate | Blocking `AskUserQuestion` | Kept — "Approve" hands the evidence to the caller instead of uploading it |
| 4.5 Upload the evidence | Upload to Linear | **Skipped** — there is no ticket; the evidence stays local |
| 5 Post results | Comment on the ticket | **Skipped** — `dev10x-qa:review-pack` publishes on the PR |

Everything not listed runs exactly as in `instructions.md`, including
artifact verification (Phase 4.1) and the test-failure recovery gate
(Phase 3).

## Deriving the cases

1. Read the `dev10x:qa-scope` report for the PR. Its manual-test and
   coverage-gap lists are the starting cases.
2. For each changed route, screen or dialog in the diff, add one case
   that walks the change end to end with seed data.
3. Add one probe for the states a scripted case tends to miss: empty,
   loading, error and permission-denied.
4. Name each case in one line. These names become the video captions
   and the review pack's "Every changed surface" section.

## Choosing the environment

Use the first that resolves, and say which one was used:

1. **Staging** with the PR head deployed (Phase 1.2 verdict
   `deployed`).
2. **A local stack** running the PR head, when the project configures
   one: point `STAGING_URL` (or `run-playwright.sh --staging-url`) at
   it, the same knob a preview host uses.

When neither resolves, do not record anything. Return the one-line
skip note `Self-QA skipped: no runnable environment for <PR>` so the
caller can print it. Never record production: footage is staging or
seed data only, and `dev10x-qa:yt-upload` enforces that gate at upload
time.

## Narration is required

An exploratory video is a review artifact, so it carries all three
pieces `dev10x-qa:review-pack` asks for: the cursor overlay, one
caption per case, and `dev10x-qa:tts` voice narration muxed over it
(Phase 4.3). When a piece fails for an external reason, such as TTS
quota or a voice model that will not load, try it once, then ship
without it and state the reason in the video caption.

## Output

Return to the caller, without publishing:

- the run directory and the verified artifact paths;
- the narrated take's path, verified per Phase 4.1;
- one line per case: name, pass or fail, and the evidence file.

Publishing is the caller's job: `dev10x-qa:review-pack` assembles the
pack and publishes the video through `dev10x-qa:qa-publish` or
`dev10x-qa:yt-upload`, each of which keeps its own external-publish
gate.
