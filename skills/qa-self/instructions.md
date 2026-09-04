# Self-QA — Automated Staging Test Execution (Instructions)

Execute QA regression test cases on staging using headless Playwright,
capture screenshot and video evidence, and post structured results to
Linear.

**Use when:**
- A QA ticket (e.g., QA-xxx) has test cases ready to execute
- You need to verify a feature works on staging before closing a ticket
- `Dev10x:qa-scope` has created a QA sub-ticket and tests need running

**Do NOT use when:**
- The test requires real hardware (e.g., Square Terminal pairing)
- E2E tests in app-e2e already cover the scenario

## Orchestration

This skill follows `references/task-orchestration.md` patterns.

**Auto-advance:** Complete each phase, immediately start the next — no checkpoints the resolver did not ask for.
Never pause between phases to ask "should I continue?".

**REQUIRED: Create tasks before ANY work.** Execute these
`TaskCreate` calls at startup:

1. `TaskCreate(subject="Verify staging deployment", activeForm="Verifying deployment")`
2. `TaskCreate(subject="Write Playwright test script", activeForm="Writing test script")`
3. `TaskCreate(subject="Execute tests on staging", activeForm="Executing tests")`
4. `TaskCreate(subject="Verify captured artifacts", activeForm="Verifying artifacts")`
5. `TaskCreate(subject="Prepare evidence (screenshots + video)", activeForm="Preparing evidence")`
6. `TaskCreate(subject="Review evidence locally before upload", activeForm="Reviewing evidence")`
7. `TaskCreate(subject="Post results to Linear", activeForm="Posting results")`

Set sequential dependencies: each phase blocked by the previous.

**Evidence review gate (Phase 4.4):** the local review is a blocking
gate, not a courtesy. Uploads are append-only on the ticket, so a bad
take published first can only be superseded, never withdrawn.

**REQUIRED: Call `AskUserQuestion`** before any upload (do NOT use plain
text). Options:
- Approve — upload to Linear (Recommended)
- Re-capture — artifacts do not show what the test cases claim
- Abort — stop without publishing

**Error recovery gate (Phase 3):** When tests fail, queue the
decision in task metadata. If no other tasks can advance, present
the decision.

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text, call spec: [ask-test-failure-recovery.md](./tool-calls/ask-test-failure-recovery.md)).
Options:
- Fix and retry (Recommended) — Adjust the test script and re-run
- Skip failing test case — Mark as skipped, continue with passing tests
- Abort — Stop QA execution entirely

## Prerequisites

- Linear ticket with test cases (from `Dev10x:qa-scope` or manual)
- Headless Playwright: `uv run --with playwright python3 -m playwright install chromium`

## Workflow

### Phase 1: Gather Context

#### 1.1 Read the QA Ticket

Use Linear MCP to get the QA ticket. Extract:
- Test cases (checkbox items in description)
- Parent ticket ID (the feature ticket)
- Expected behavior for each test

#### 1.2 Verify Deployment

**Critical — do this before writing any test code.**

Nothing deployment-specific is baked in (GH-1147). Every path below is an
environment override with a documented default, the same convention
`run-playwright.sh` uses for its own knobs (GH-1130) — so a different
checkout layout needs no edit to this skill, and nobody has to skip the
one step this phase calls critical:

```bash
QA_ARGOCD_REPO="${QA_ARGOCD_REPO:-/work/example/app-argocd}"
QA_APP_REPO="${QA_APP_REPO:-/work/example/app-pos}"
QA_STAGING_MANIFEST="${QA_STAGING_MANIFEST:-apps/staging/app-pos/generated.yaml}"
```

`QA_STAGING_MANIFEST` is a knob in its own right, not a detail of
`QA_ARGOCD_REPO`: pointing at your own argocd clone still reads the wrong
file if the manifest path inside it stays fixed, and the resulting "not
deployed" verdict looks like a stale clone rather than a wrong path.

Check that the feature commit is included in the staging image:

```bash
# Always fetch first — local argocd clone may be days stale
git -C "$QA_ARGOCD_REPO" fetch origin --quiet
# Commit message contains the deployed SHA: "🚀 [STAGING] app-pos deploy develop-fcd3ea5-..."
git -C "$QA_ARGOCD_REPO" log --oneline -1 origin/main -- "$QA_STAGING_MANIFEST"

# Check if feature commit is an ancestor of the deployed SHA
git -C "$QA_APP_REPO" merge-base --is-ancestor <feature-sha> <staging-sha>
```

`git -C` is correct here — these are *other* clones, not the session's own
worktree, so the usual objection to `-C` (it shifts the allow-rule prefix
for a path that is already the CWD) does not apply.

If the feature is NOT deployed, post a "BLOCKED — not deployed" comment
on the QA ticket and stop. Include:
- Current staging image tag
- Feature commit SHA
- Gap size (number of commits between)

#### 1.3 Understand the UI Flow

Read the relevant frontend code — `${QA_FRONTEND_REPO:-/work/example/app-admin}`,
with the backend at `$QA_APP_REPO` from 1.2 — to understand:
- Which page/dialog to interact with
- Form field IDs and selectors
- Success/error indicators (snackbars, form helper text)
- GraphQL mutations involved

### Phase 2: Write the Playwright Test Script

Generate a self-contained Python script at `/tmp/Dev10x/self-qa/qa-<ticket>-test.py`.

#### 2.1 Script Template

```python
"""QA test for <TICKET>: <title>."""
import json
import os
import random
import re
import time
import uuid
from playwright.sync_api import Page, sync_playwright

# --- Configuration ---
# Credentials are injected by run-playwright.sh — never hardcode them here.
# Read from environment variables:
CF_CLIENT_ID = os.environ["CF_CLIENT_ID"]
CF_SECRET    = os.environ["CF_SECRET"]
STAGING_URL  = os.environ.get("STAGING_URL", "https://staging-app.example.com")
CRM_USERNAME = os.environ.get("CRM_USERNAME", "e2e_test_user")
CRM_PASSWORD = os.environ["CRM_PASSWORD"]

# Run-scoped artifact directory — NEVER a bare /tmp or a pytest default
# basetemp. pytest rotates `pytest-N` basetemps (keeping the last 3), so
# parallel sessions running tests concurrently can destroy this run's
# captures mid-session.
RUN_ID = time.strftime("%Y%m%d-%H%M%S")
RUN_DIR = f"/tmp/Dev10x/self-qa/qa-<ticket>-{RUN_ID}"
SCREENSHOT_DIR = f"{RUN_DIR}/screenshots"
VIDEO_DIR = f"{RUN_DIR}/video"
```

For a pytest-driven capture, pass the same run-scoped directory
explicitly: `--basetemp=<RUN_DIR>`.

#### 2.2 Required Patterns

Follow these patterns learned from production QA sessions:

**Viewport + Video Recording**: the viewport must be **at least as large
as `record_video_size`**. Playwright's `record_video_size` only ever
scales *down*: a viewport smaller than the recording size is placed 1:1
in the top-left of the frame and the remainder is filled with mid-grey.
Pairing the old `1680x1050` app-e2e viewport with a `1920x1080`
recording padded every single take — 240px on the right, 30px at the
bottom (GH-1204).

Matching the aspect ratio does **not** fix it. `1680x945` is exactly
16:9 and still pads, because the rule is a size relation, not an aspect
relation.

Record Full HD and set the viewport to match — the canonical context is
the **Two-phase recording** snippet below; it is the only one to copy.
`device_scale_factor=2` renders the page at 3840x2160 and Playwright
scales that *down* to 1920x1080 — a genuine supersample, and the
scaling direction it actually supports. Text comes out visibly sharper.

1080 is also the height that survives publishing: YouTube's tiers are
1080 / 720 / 480, so a 1050-tall video is served at 720p **and**
resampled 1050 → 720, softening text a second time.

Choose the geometry once, at context creation, and never resize the
viewport mid-run — that silently changes the app's layout, so the
recording stops showing what a user sees. The reasoning, and the rest of
the recording guidance, is in
[`recording-for-humans.md`](../playwright/references/recording-for-humans.md).

**Video pacing**: Add `time.sleep(1)` pauses after filling forms and
`time.sleep(2)` after results appear so the video is reviewable.

**Finalize video**: Close the context (not just the browser) to flush:
```python
context.close()
browser.close()
```

**Two-phase recording** — the canonical capture context. It keeps the
video focused on the test cases rather than login/setup, and it carries
the padding-free geometry above. Copy this one:
```python
os.makedirs(VIDEO_DIR, exist_ok=True)

# Phase 1: authenticate + create test data WITHOUT video
setup_context = browser.new_context(
    viewport={"width": 1920, "height": 1080},
)
setup_page = setup_context.new_page()
setup_cf_headers(setup_page)
login(setup_page)
wo_url = create_new_wo(setup_page)
storage_state = setup_context.storage_state()
setup_context.close()

# Phase 2: reuse auth cookies, start recording on the target page.
# viewport == record_video_size, so nothing is padded; the 2x scale
# factor supersamples 3840x2160 down into the frame.
context = browser.new_context(
    viewport={"width": 1920, "height": 1080},
    device_scale_factor=2,
    record_video_dir=VIDEO_DIR,
    record_video_size={"width": 1920, "height": 1080},
    storage_state=storage_state,
)
page = context.new_page()
page.goto(wo_url, wait_until="networkidle")
```

Both contexts use the same viewport on purpose: setup runs at the
layout the recording will show, so an element positioned during Phase 1
is where Phase 2 expects it.

**Cloudflare headers**: Route all `.example.com` requests:
```python
def setup_cf_headers(page):
    def add_cf_headers(route):
        headers = route.request.all_headers()
        headers["cf-access-client-id"] = CF_CLIENT_ID
        headers["cf-access-client-secret"] = CF_SECRET
        route.continue_(headers=headers)
    page.route("**/*.example.com/**", add_cf_headers)
```

**Login flow**:
```python
def login(page):
    page.goto(f"{STAGING_URL}/login", wait_until="networkidle")
    time.sleep(1)
    page.get_by_role("textbox", name="Username").fill(CRM_USERNAME)
    page.get_by_label("Password", exact=True).fill(CRM_PASSWORD)
    page.get_by_label("Remember Me").check()
    page.get_by_role("button", name="Continue").click()
    page.wait_for_url(re.compile(r"^(?!.*login)"), timeout=15000)
    page.wait_for_load_state("networkidle")
    time.sleep(2)
```

**Phone number input** (mui-phone-number quirk):
```python
# MUST prepend "1" for US country code
# Clear field with Ctrl+A then type with delay
phone_input = dialog.locator("#phoneNumber")
phone_input.click()
page.keyboard.press("Control+a")
page.keyboard.press("Backspace")
phone_input.type("16175551234", delay=50)
```

**Button clicks**: Always scroll into view first:
```python
save_btn.scroll_into_view_if_needed()
time.sleep(0.5)
save_btn.click()
```

**Wait for GraphQL response** (don't rely on timing):
```python
with page.expect_response(
    lambda resp: "/graphql" in resp.url,
    timeout=15000,
) as response_info:
    save_btn.click()
response = response_info.value
```

**GraphQL response capture** for debugging:
```python
def setup_response_capture(page):
    def on_response(response):
        if "/graphql" in response.url:
            try:
                body = response.json()
                if "errors" in body:
                    print(f"  [GraphQL ERROR] {json.dumps(body['errors'])[:500]}")
            except Exception:
                pass
    page.on("response", on_response)
```

**Annotation overlay** (pointer, captions, click ordering):

Playwright headless renders no system cursor, so an unannotated
recording shows things happening with nothing indicating where or why.
**Import the shared module — never paste an overlay into the generated
script.** An inline overlay cannot be linted, imported or unit-tested,
which is exactly how its navigation bug, its JS-injection bug and its
unusable pointer all survived unnoticed (GH-1087).

```python
import os
import sys

sys.path.insert(0, os.environ["DEV10X_PLAYWRIGHT_LIB"])
from annotate import Annotator

anno = Annotator(page, pace=1.0)   # one knob scales every derived dwell
anno.install()          # installs for THIS document and every later one

anno.say("Pick a customer — one click assigns them, no Save needed")
anno.tap(customer_row,
         announce="Choosing Hulk Smash from the list",
         then="Done — assigned instantly, no extra clicks")
```

**Every click on the recorded path goes through `anno.tap()` (or
`anno.click()`) — this is a rule, not an example for the interesting
steps.** A bare `locator.click()` cuts between two states with nothing
on screen saying what was pressed, and longer sleeps are the wrong fix:
they hold a still frame of an unexplained change. `tap()` ships the
whole ordering — scroll → point → narrate → act → beat → outcome — so no
script re-derives it. Budget **~2.5 minutes of footage per four test
cases**; one measured run went 68s → 155s and was accepted first try.

`run-playwright.sh` exports `DEV10X_PLAYWRIGHT_LIB`, so the import path
is never hard-coded in the generated script.

**When the target repo already ships its own narrated-capture harness,
do not replace it.** Run the Annotator as a separate script and raise
the overlap with that repo's owners separately. Three reasons, from a
session that faced the choice:

- The Annotator's failure modes are documented and fixed; a bespoke
  overlay would need auditing to know it is free of them.
- The artifacts have different audiences. A CI regression net narrated
  with step names is not the reviewer-facing walkthrough narrated with
  user outcomes.
- Swapping a shared repo's capture mechanism touches the file every
  scenario runs through, for the sake of one recording.

**Keep the caveat rather than papering over it:** this leaves two
overlay implementations coexisting, which is the duplication the shared
module was created to end. It is the right trade for a single task and
the wrong one permanently — so the follow-up conversation with that
repo's owners is part of the job, not optional.

What the module guarantees, and why each one matters:

| Guarantee | Failure it prevents |
|---|---|
| `install()` uses `add_init_script` | `page.evaluate` applies to the current document only — the pointer and captions vanish after the first `goto` while the run still passes |
| Caption text passed as an evaluate **argument** | f-string interpolation broke on a newline, backtick or `</script>`; one unescaped backtick uninstalled the whole overlay |
| Arrow tip is the path origin | A symmetrical dot indicates "somewhere around here" — useless for a grid cell, table row or checkbox |
| Dwell computed from caption length | One fixed duration truncates long captions and drags short ones |
| `click()` does point → narrate → act | Narrating first describes a target the viewer has not been shown yet |
| `point_at` scrolls, then asserts the box is **inside the viewport** | `bounding_box()` answers for anything laid out, so a below-the-fold element passed the old `None` check and shipped as evidence for a claim it did not show (GH-1129) |
| The caption flips to the top when the pointer is in the lower third | A caption at `bottom: 32px` lands on the evidence itself; caught only by extracting frames, and it cost a re-record |
| `pace=` is the only pacing knob | `POINT_SETTLE_SECONDS` was a *default argument*, so patching it silently did nothing while patching the caption constants worked |

**Set captions only AFTER a navigation completes.** The overlay is
re-created per document, so a caption set before `goto` is wiped by the
page load and the step plays silently.

Captions describe the **user benefit** ("One click assigns them, no Save
needed"), not the assertion ("TC1: should auto-save on onChange").

**Optional narration (voice-over).** Because captions are already
user-benefit prose, they double as narration copy. Attaching a `Narration`
speaks them and switches caption dwell from a character-count estimate to
the actual audio duration, so the two tracks cannot drift:

```python
from narration import Narration

NARRATION = [
    "Pick a customer — one click assigns them, no Save needed",
    "Done — assigned instantly, no extra clicks",
]

narration = Narration(f"{RUN_DIR}/narration", script=NARRATION)
narration.mark_video_start()      # right after the recorded context opens
anno = Annotator(page, narration=narration)
anno.install()                    # pre-renders all lines in ONE piper process
...
narration.write_manifest()        # after context.close()
```

Narration is **opt-in** — omit it and every behaviour above is unchanged.

**Before capturing a narrated run**, resolve the voice-licence gate: run
`${CLAUDE_PLUGIN_ROOT}/skills/tts/scripts/synthesize.py check` and, when it
returns a non-null `warning`, **REQUIRED: Call `AskUserQuestion`** per
`skills/tts/SKILL.md` § *Voice licensing is the supervisor's call*. Most
English Piper voices forbid commercial use, and QA evidence for client work
is commercial use — catching that after the take wastes the recording.

Full recipe, timing model and the licence gate:
[`skills/tts/references/qa-self-narration.md`](../tts/references/qa-self-narration.md).

**Redact anything that must not reach the recording.** The
`Dev10x:yt-upload` provenance gate asks the operator to *state* that no
production data is on screen — it cannot verify it, and "I recognised
the fixture from sampled frames" does not generalise. Declare the list
once, at the top:

```python
anno = Annotator(page, redact=[
    "[data-test='customer-name']",
    "[data-test='customer-phone']",
])
```

Masks re-apply through `add_init_script` like the overlay itself, and
are opaque rather than blurred. Full argument and the two non-obvious
properties: [`redaction.md`](../playwright/references/redaction.md).

**Further shapes** — full-screen card for framing the whole recording,
two-tier caption, a distinct treatment for *absence* ("we did NOT verify
X"), step chip with measured chapter timestamps, before/after compare
for a changing value, highlight, zoom, and the theme tokens that replace
every hardcoded colour:
[`overlay-shapes.md`](../playwright/references/overlay-shapes.md).

Full guidance — pointer anatomy, palette, pacing, resolution — lives in
[`skills/playwright/references/recording-for-humans.md`](../playwright/references/recording-for-humans.md).

#### 2.3 Test Data Strategy

- **Build the fixture; do not hunt for one.** Creating the record in the
  un-recorded setup phase is the default, not a preference. Querying for
  a clean pre-existing fixture burns real time and usually finds none —
  existing records are consumed by earlier runs or malformed. A built
  fixture is deterministic and the run is re-runnable.
- **Corollary: each capture iteration leaves fixture residue.** Three
  takes leave three records behind, so published results must name
  **exactly which record** the evidence shows.
- **Self-contained tests**: Create test data within the test, don't
  depend on pre-existing records
- **Unique identifiers**: Use `uuid.uuid4().hex[:6]` for names,
  `random.randint(1000,9999)` for phone suffixes
- **Test order matters**: If tests depend on each other (e.g., create
  first, then duplicate), enforce ordering in the script
- **e2e_test_user is USER-level only (level=1)**: Has USER permissions for
  dealer 382. Cannot test features gated on dealer admin (level≥2) — e.g.
  reopen/void work orders. For admin-level tests use `janusz_ai` (level=2,
  dealer 585, password in the secrets file — `$PLAYWRIGHT_SECRETS_FILE`,
  defaulting to `/work/example/app-e2e/settings.secrets.env` — as
  `CRM_PASSWORD2`). Per-dealer constraints only fire within the same dealer.

#### 2.4 Screenshot Timing

Take screenshots **immediately** after the expected UI state appears:
- After success snackbar appears (before it auto-dismisses ~3s)
- After error message renders on the form
- Before closing dialogs

**Assert the subject is on screen at shoot time.** A screenshot
taken while the target is scrolled out of the viewport is
indistinguishable from a working feature — it is just a picture of
something else. Route every shot through `Annotator.shoot()`, which
scrolls, asserts the box is **inside the viewport**, points at the
subject, captures, and records a manifest row:

```python
# Wait for the success indicator THEN shoot immediately
try:
    page.wait_for_selector("text=Successfully updated", timeout=10000)
except Exception:
    time.sleep(3)  # fallback wait

anno.shoot(page.get_by_text("Successfully updated"),
           f"{SCREENSHOT_DIR}/test1-success.png",
           claim="The customer's details saved without a second click")
```

**A non-`None` bounding box is not proof the element is visible**
(GH-1129). `bounding_box()` returns coordinates for anything attached
and laid out; `None` comes back only for detached or `display:none`
elements. Off-screen is far more common than detached, because
below-the-fold is the normal state of most of a long page — so the old
`None`-only check passed screenshots pointed at figures nobody could
see, and Phase 4.1 verification passed them too.

Phase 4.1 catches a *blank* or *truncated* artifact after the fact. It
is structurally incapable of catching **a picture of the wrong thing**:
the image has a real file size and real stddev. Only the capture-time
viewport assertion catches that, and it catches it while the run can
still be fixed.

**Wrap every un-recorded setup step so a failure leaves an artifact.** A
locator timeout during setup otherwise yields a stack trace and nothing
else:

```python
try:
    wo_url = create_new_wo(setup_page)
except Exception:
    print(json.dumps(debug_dump(setup_page, "create-wo"), indent=2))
    raise
```

`debug_dump` writes a full-page screenshot and returns every button's
accessible name, sorted. That found a drifted label — the same control
capitalised differently on two pages — on the very next run.

### Phase 3: Execute Tests

#### 3.1 Install Playwright browsers (first time only)

**Pin the version.** A bare `--with playwright` resolves to whatever is
newest, and one recent release refused to install a browser at all on a
current Linux distro — reporting the failure as *"does not support
chromium on \<distro\>"*, which points at the OS rather than at the
resolver and sends you the wrong way. `run-playwright.sh` pins the same
range it runs scripts with; use it here too:

```bash
uv run --with 'playwright>=1.47,<2' python3 -m playwright install chromium
```

#### 3.2 Validate and run the test script

Always validate syntax before launching a browser:

```bash
${CLAUDE_PLUGIN_ROOT}/skills/playwright/scripts/run-playwright.sh \
  /tmp/Dev10x/self-qa/qa-<ticket>-test.py --validate-only
```

Then execute (credentials injected automatically from settings.secrets.env):

```bash
${CLAUDE_PLUGIN_ROOT}/skills/playwright/scripts/run-playwright.sh \
  /tmp/Dev10x/self-qa/qa-<ticket>-test.py
```

For admin-gated features (reopen/void WO), use `--user janusz_ai`:

```bash
${CLAUDE_PLUGIN_ROOT}/skills/playwright/scripts/run-playwright.sh \
  /tmp/Dev10x/self-qa/qa-<ticket>-test.py --user janusz_ai
```

#### 3.3 Review output

Check console output for:
- GraphQL errors (expected for duplicate detection tests)
- Success confirmations
- Screenshot file paths

If tests fail, fix the script and re-run. Common issues:
- Dialog closed unexpectedly = mutation succeeded (check deployment)
- Phone format wrong = ensure "1" prefix for US numbers
- Element not found = add `wait_for` or increase sleep
- Wrong dealer data = e2e_test_user is dealer 382

#### 3.4 Confirm the mechanism, not just the pixels (optional)

Where the fix has an observable data signature, read it back and include
it alongside the UI evidence. A UI can look correct for the wrong reason
— a cached read, an unrelated code path, coincidence.

*UI evidence shows the symptom is gone; data evidence shows that **this
change** is why.* A GraphQL response captured by
`setup_response_capture()`, or a read-only query on the record the
fixture created, is usually enough. Skip it when the change has no data
signature — an alignment fix has nothing to read back.

### Phase 4: Prepare Evidence

#### 4.1 Verify the captured artifacts (REQUIRED before anything else)

A green capture run proves the code ran — not that the artifacts show
anything. Run the verifier on every screenshot and video before
converting, reviewing or uploading:

```bash
${CLAUDE_PLUGIN_ROOT}/skills/qa-self/scripts/verify-evidence.py \
  <RUN_DIR>/screenshots/*.png <RUN_DIR>/video/*.webm
```

It applies a file-size floor and a non-uniform-frame check per
screenshot, and the same checks to three frames extracted through each
video. Output is a JSON report; a non-zero exit means at least one
artifact is empty, blank or truncated.

Each video frame also gets a **border check** (GH-1204): an edge whose
outer 6px strip is a single flat colour in *every* sampled frame is
Playwright's grey padding, which means the viewport was smaller than
`record_video_size`. Fix the capture geometry (§ 2.2) and re-record —
no re-encode can recover the lost frame area. For a page whose right or
bottom edge genuinely is one flat colour, pass `--no-border-check`.

**On any failure, re-capture — do NOT convert or upload.** A failing
artifact is a capture bug (a step that no-opped, a context that was
never flushed, a viewport smaller than the recording size), not a
cosmetic problem.

**Anti-pattern — silent conditional capture guards.** A step written as

```python
if locator.count() > 0:      # ❌ no-ops without failing
    screenshot(page, "test1-success.png")
```

passes whether or not the target ever existed, so a missing feature
looks identical to a working one. Assert instead, by routing the shot
through `Annotator.shoot()`.

**"In-viewport" is not "`bounding_box()` non-null."** That check catches
only detached and `display:none` elements; anything laid out below the
fold returns a perfectly good box and sails through. `point_at()`
scrolls first and then compares the box against `page.viewport_size`,
which is the check that actually holds (GH-1129).

And note the ceiling on this phase: the verifier catches *blank* and
*truncated*. It cannot catch *a picture of the wrong thing* — that image
has a real file size and real stddev. The capture-time assertion in 2.4
is the only gate for that failure, and the 4.4 manifest is how a human
double-checks it.

#### 4.2 Convert screenshots

Use the bundled conversion script:
```bash
${CLAUDE_PLUGIN_ROOT}/skills/qa-self/scripts/convert-evidence.sh \
  screenshots /tmp/Dev10x/self-qa/qa-test1.png /tmp/Dev10x/self-qa/qa-test2.png
```

Converts PNGs to JPGs (quality 70, max 1200px wide). Prints converted
file paths to stdout.

#### 4.3 Convert video

Playwright records video as `.webm`. Convert to `.mp4` for Linear:
```bash
${CLAUDE_PLUGIN_ROOT}/skills/qa-self/scripts/convert-evidence.sh \
  video /tmp/Dev10x/self-qa/qa-<ticket>-video/*.webm
```

Uses ffmpeg (`h264, crf 18, yuv420p, faststart`). Prints the `.mp4` path
to stdout.

**If the capture was narrated**, build the voice-over track and mux it on.
Skip this step entirely when no `narration.json` was written:

```bash
${CLAUDE_PLUGIN_ROOT}/skills/tts/scripts/synthesize.py \
  track --segments-file <RUN_DIR>/narration/narration.json \
        --out <RUN_DIR>/narration/track.wav

${CLAUDE_PLUGIN_ROOT}/skills/qa-self/scripts/convert-evidence.sh \
  narrate <RUN_DIR>/video/qa-<ticket>.mp4 <RUN_DIR>/narration/track.wav
```

The narrated `-narrated.mp4` replaces the silent take for review and
upload — publish one or the other, never both. Check the manifest's
`unrendered` list: a non-empty list means some caption played with no
audio because it was missing from the script's `NARRATION`.

#### 4.4 Local review gate (REQUIRED before any upload)

Linear evidence trails are append-only: a problem spotted after upload
costs a superseded re-upload on the ticket, and the supervisor sees the
bad take either way. Review locally first.

1. Report what will be published — each artifact's path, size, duration
   and **raster** (for video), and the verifier's verdict from 4.1.

   **The raster line is not decoration (GH-1188).** Read it from the
   file, not from the script that was supposed to produce it:

   ```bash
   ffprobe -v error -select_streams v:0 \
     -show_entries stream=width,height -of csv=p=0 <video>
   ```

   Anything below `1920,1080` means the recording was captured at the
   viewport's own size instead of the Full HD raster, and no re-encode
   can recover the detail — the take has to be re-recorded. Every other
   check in the pipeline passes on a downgraded capture: the frames are
   non-uniform, the file is a real size, and `narration.json` reports no
   defects.

   **A `1920,1080` raster is not proof the frame is full-bleed
   (GH-1204).** A padded capture reports exactly those dimensions — the
   grey fill is inside the frame. That is what the verifier's border
   check in 4.1 is for: it fails a take whose right or bottom edge is a
   flat fill in every sampled frame. Do not try to eyeball it instead —
   a MUI modal backdrop dims the page to roughly the same mid-grey as
   the padding, so a frame sampled with a dialog open reads as clean
   when it is not, and `cropdetect` misses it at default settings
   because the fill is mid-grey rather than black.

   **When the capture was narrated, this report MUST also carry, from
   `narration.json`:**
   - `unrendered` — the count and the actual lines. A non-empty list means
     captions played silently because they were missing from `NARRATION`.
   - `warning` — the voice's licence caveat, if non-null.
   - `anchor` — `video-start` or `install`; the latter means every cue is
     offset by however long setup took, so the audio may lag the captions.

   These three are computed precisely so a human sees them. Leaving them in
   the JSON and reporting only paths and sizes reintroduces the silent
   failure the manifest exists to prevent.

   **Print the screenshot manifest — one `file → target → claim` row per
   artifact**, from `anno.manifest_rows()`:

   ```
   tc3-total.png → Locator@get_by_text('Amount due') → Declining the tyre removed it from the bill
   ```

   This is the counter-measure to the capture-time defect in 2.4. It
   turns review from *"does this look OK?"* — a question people answer
   *yes* to while skimming — into *"does this image show **that**
   element?"*, which is checkable in seconds and fails visibly.

   `target` is `repr(locator)`, Playwright's own selector description.
   Never substitute an author-written label: it drifts from the locator
   it claims to describe, and then reassures the reviewer about the
   wrong thing.
2. Keep the sampled frames so the footage can be inspected without
   playing it, then **Read the saved frames** — the report's paths are
   only useful if someone actually looks at them:
   ```bash
   ${CLAUDE_PLUGIN_ROOT}/skills/qa-self/scripts/verify-evidence.py \
     --save-frames <RUN_DIR>/review-frames \
     <RUN_DIR>/video/qa-<ticket>.mp4
   ```
3. **REQUIRED: Call `AskUserQuestion`** (do NOT use plain text). This
   blocks until the supervisor responds. Options:
   - **Approve — upload to Linear (Recommended)** — artifacts show what
     the test cases claim
   - **Re-capture** — something is missing, blank or unfollowable;
     return to Phase 2/3 and shoot again
   - **Abort** — stop without publishing anything

   **Narration shifts the recommendation.** When `unrendered` is non-empty
   or `anchor` is `install`, **Re-capture** becomes the recommended option
   and Approve is offered without the marker — a walkthrough whose
   narration is partly missing or systematically offset is exactly the
   "looks fine, is wrong" artifact this gate exists to catch. A non-null
   licence `warning` does NOT change the recommendation; it is stated in
   the question text so the supervisor publishes knowing the terms.

Only on *Approve* proceed to 4.5. Never upload first and ask after.

#### 4.5 Upload the evidence

Only reachable on *Approve* from 4.4.

**Linear** — use the upload script bundled with this skill (supports
images and video):
```bash
${CLAUDE_PLUGIN_ROOT}/skills/qa-self/scripts/upload-screenshots.py \
  upload /tmp/Dev10x/self-qa/qa-test1.jpg /tmp/Dev10x/self-qa/qa-test2.jpg /tmp/Dev10x/self-qa/qa-video.mp4
```

Output is JSON with `[{"file": "...", "url": "..."}]` — parse the URLs
for the comment.

**Key**: The script includes signed headers from the `fileUpload`
mutation response. Without these headers, uploads appear to succeed but
files fail to load.

**When the walkthrough also has to reach a PR**, Linear-hosted assets
are not enough: `uploads.linear.app` 401s for anyone on GitHub, and
GitHub strips the iframe a player would need. Delegate to
`Dev10x:yt-upload` for a shareable link rather than restating upload
mechanics here — it owns the production-recording gate, the token
handling, and the per-destination embed forms:

```bash
${CLAUDE_PLUGIN_ROOT}/skills/yt-upload/scripts/upload-video.py \
  resolve-video --run-dir <RUN_DIR>
```

`resolve-video` picks the single artifact to publish — the narrated take
when a sibling `-narrated.mp4` exists — and re-reports the same
`unrendered` / `warning` / `anchor` fields 4.4 surfaced, so a direct
invocation cannot skip them.

**The 4.4 gate does not carry over to YouTube.** Approving *that the
footage is good* is a different decision from approving *that it may
become world-readable to any link-holder*, so `Dev10x:yt-upload` fires
its own provenance gate. That is by design — do not try to satisfy it
with 4.4's answer.

For a full write-up to both a ticket and a PR — verdict, threaded
Jira-synced comment, per-destination screenshots — use
`Dev10x:qa-publish`, which composes this skill's scripts with
`Dev10x:yt-upload`.

### Phase 5: Post Results to Linear

Use **Linear MCP `create_comment`** (not the personal API key — it
cannot write to all team issues).

#### 5.1 Comment Template

```markdown
## QA Test Results — <TICKET> <Title>

**Environment:** Staging (`staging-app.example.com`)
**Date:** <YYYY-MM-DD>
**Tester:** Claude (automated via Playwright)

### Test Results

| Test | Expected | Actual | Status |
|------|----------|--------|--------|
| 1. <test case> | <expected> | <actual> | PASS/FAIL/BLOCKED |

### Evidence

**Test 1: <description>**
![Test 1](<uploaded-screenshot-url>)

**Video walkthrough:**
[QA Test Recording](<uploaded-video-url>)

### Notes
- <any observations, deployment issues, frontend quirks>
```

#### 5.2 Post comment

```
Linear MCP create_comment(issueId="<ticket>", body="<markdown>")
```

#### 5.3 Update ticket status

If all tests pass, move ticket to "Done" or ask user.
If tests are blocked, leave in current status and note the blocker.

## Pitfalls & Lessons Learned

| Pitfall | Solution |
|---------|----------|
| Phone input shows +61 (Australia) | Always prepend `1` for US country code |
| Per-dealer constraints don't fire | e2e_test_user is dealer 382; create test data in same session |
| Save button click doesn't register | `scroll_into_view_if_needed()` + `time.sleep(0.5)` |
| Screenshot misses snackbar | Screenshot immediately after `wait_for_selector`, before sleep |
| Linear images "Failed to load" | Must include signed headers from `fileUpload` response in PUT |
| Personal API key can't comment on QA issues | Use Linear MCP `create_comment` instead |
| Feature "not deployed" on first check | Local argocd clone may be stale. Always `git -C "$QA_ARGOCD_REPO" fetch origin` before reading the image tag. |
| New WO page renders as skeleton | After "New Work Order" click, capture `page.url` then hard-navigate with `page.goto(new_wo_url)` to force a fresh render. |
| Dialog closes but status unchanged | `onClose` may be wired unconditionally (not to mutation success). Check DB or use `page.expect_response()` to confirm the mutation actually fired. A dialog can close via Escape, backdrop click, or explicit close handler without any mutation being called. |
| Video not finalized (0 bytes) | Must `context.close()` before `browser.close()` to flush video — `verify-evidence.py` catches this before upload |
| Captures vanish mid-session | Artifacts written under a pytest default basetemp are rotated away (last 3 kept) by a parallel session. Use the run-scoped `RUN_DIR`, and pass `--basetemp=<RUN_DIR>` for pytest-driven runs |
| Screenshot published blank | A silent `if locator.count() > 0:` guard no-opped the step. Route the shot through `Annotator.shoot()`; run Phase 4.1 verification before upload |
| Screenshot shows the right page but not the asserted element | The target was below the fold. `bounding_box()` returns coordinates for anything laid out, so a `None`-only check passes it and so does `verify-evidence.py`. `point_at()` now scrolls and asserts against `page.viewport_size` (GH-1129) |
| Caption sits on top of the element being pointed at | Captions live at `bottom: 32px`. The overlay now flips them to the top when the pointer is in the lower third — no call-site change needed |
| Patching `POINT_SETTLE_SECONDS` changes nothing | It was bound as a default argument at import time. Use `Annotator(page, pace=…)`, the single knob for every derived duration |
| Recorded clicks have no pointer or caption | The script used bare `locator.click()`. Every click on the recorded path goes through `anno.tap()` / `anno.click()` — a rule, not an example |
| Setup step fails with only a stack trace | The setup phase is un-recorded. Wrap each step: `except Exception: print(json.dumps(debug_dump(page, tag))); raise` |
| `playwright install chromium` says the OS is unsupported | `--with playwright` resolved to a newer release than the wrapper was tested against. Pin it: `--with 'playwright>=1.47,<2'` |
| Clicking Print hangs the run — no error, execution just stops | `window.print()` opens a browser modal that blocks Playwright with nothing raised. Neutralise `print` in **both** realms, then reveal the iframe and `emulate_media(media="print")`. Full recipe, and why the alternative (film a second dialog-free surface) only works where such a surface exists: [`print-capture.md`](../playwright/references/print-capture.md) |
| A disclaimer reads as a demonstration | A caption saying "we did NOT verify X" renders identically to a positive claim. Use `anno.say(..., kind="absence")` — hollow and italic |
| Chapter timestamps in a video description are guesses | Inferring them from the pacing constants presents estimates with the authority of measurements. `anno.mark_video_start()` + `anno.step(...)` measure them; `chapter_lines()` emits them, and `chapters()` raises if the anchor was never set |
| A caption claims a value changed, showing only the after | Circular — the viewer takes the delta on trust from the automation the video exists to demonstrate. `anno.capture_region()` then `anno.compare()` shows it |
| The deploy check can't run outside one deployment | Phase 1.2 baked in absolute clone paths and the argocd manifest path, so the step it calls critical was the first one skipped. Now `$QA_ARGOCD_REPO`, `$QA_APP_REPO`, `$QA_STAGING_MANIFEST`, `$QA_FRONTEND_REPO`, each with a documented default (GH-1147) |
| Every script gets the placeholder host | `run-playwright.sh` used to assign `STAGING_URL` unconditionally, so a script's own `os.environ.get("STAGING_URL", …)` default could never apply. Now `${STAGING_URL:-…}`; drop the dead default from the script (GH-1130) |
| A third test account is unreachable | The wrapper's user map is config now: add `CRM_USERNAME<suffix>` + `CRM_PASSWORD<suffix>` to the secrets file and pass `--user <name>` or `--profile <suffix>`. Never fork the wrapper — a fork loses the syntax validation and no-hardcoded-credentials guarantees |
| Evidence names no specific record | Each capture iteration leaves fixture residue — three takes, three records. Name exactly which record the published evidence shows |
| Overlay disappears after navigation | `page.evaluate` binds to one document. Use `Annotator.install()` (`add_init_script`), and set captions only after navigation completes |
| Text looks smeared in the mp4 | CRF too high for screen content. `convert-evidence.sh` now encodes at CRF 18 with explicit `-pix_fmt yuv420p` |
| Video is `.webm`, Linear can't play inline | Convert to `.mp4` with `convert-evidence.sh video` |
| Video too fast to follow | Add `time.sleep(1)` after form fills, `time.sleep(2)` after results |
| Apollo GraphQL bypasses `window.fetch`/XHR patches; JS intercept captures nothing | Use `page.on("response", ...)` or `setup_response_capture()` — Apollo uses its own transport, not the browser's fetch/XHR prototypes |
| Coordinate-based dialog button clicks hit the backdrop instead of the button | Use `read_page` ref IDs (Chrome MCP) or Playwright role/testid selectors; never click dialogs by absolute coordinates |
| WO detail page URL uses wrong identifier | The URL path parameter is the **work order number** (e.g., `STAGING-WO:11V-DK`), not the database PK or Relay global ID. Route: `/pos/workorders/{order_no}`. The frontend `[posWorkOrderId]/index.tsx` calls `decodeURI()` and passes it to the `workOrderNoToId` GraphQL query. |
| Cursor/overlay appears duplicated | `inject_overlay()` must be idempotent — guard with `if (document.getElementById('qa-cursor')) return;` at the top of the JS. Page navigations or SPA route changes can re-trigger injection. |
| Video subtitles are too technical | Subtitles should describe the **user benefit** ("One click assigns them, no Save needed"), not implementation details ("TC1: should auto-save on onChange"). Sprinkle in light easter egg humor to keep viewers engaged. |
| TC only verifies UI presence, not full flow | Test cases should **complete full flows** — e.g., "Add Customer" should fill the form and actually save, not just verify the dialog opens. A TC that stops at "dialog opened" doesn't prove the feature works. |
| Dealer 382 has no vehicles | `e2e_test_user` (dealer 382) has no customers with real vehicles — only "No Vehicle" entries. For vehicle-related TCs, use `janusz_ai` (dealer 585) via `--user janusz_ai`. |

## Integration with Other Skills

```
Dev10x:qa-self
├── Prereq: Dev10x:qa-scope (creates the QA ticket with test cases)
├── Uses: Linear MCP (read ticket, post results)
├── Scripts:
│   ├── upload-screenshots.py (upload images & video to Linear)
│   ├── convert-evidence.sh (PNG→JPG, webm→mp4 conversion)
│   └── verify-evidence.py (size floor, uniform-frame, video frames,
│       padded-border check)
├── Imports: skills/playwright/lib/annotate.py (pointer, captions)
├── Reads: $QA_ARGOCD_REPO (verify deployment)
├── Reads: $QA_FRONTEND_REPO (understand UI selectors)
└── Reads: $QA_APP_REPO (understand backend behavior)
    Defaults for all three are documented in Phase 1.2 / 1.3.
```
