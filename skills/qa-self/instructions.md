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

**Auto-advance:** Complete each phase, immediately start the next — no checkpoints under adaptive friction.
Never pause between phases to ask "should I continue?".

**REQUIRED: Create tasks before ANY work.** Execute these
`TaskCreate` calls at startup:

1. `TaskCreate(subject="Verify staging deployment", activeForm="Verifying deployment")`
2. `TaskCreate(subject="Write Playwright test script", activeForm="Writing test script")`
3. `TaskCreate(subject="Execute tests on staging", activeForm="Executing tests")`
4. `TaskCreate(subject="Prepare evidence (screenshots + video)", activeForm="Preparing evidence")`
5. `TaskCreate(subject="Post results to Linear", activeForm="Posting results")`

Set sequential dependencies: each phase blocked by the previous.

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

Check that the feature commit is included in the staging image:

```bash
# Always fetch first — local argocd clone may be days stale
git -C /work/example/app-argocd fetch origin --quiet
# Commit message contains the deployed SHA: "🚀 [STAGING] app-pos deploy develop-fcd3ea5-..."
git -C /work/example/app-argocd log --oneline -1 origin/main -- apps/staging/app-pos/generated.yaml

# Check if feature commit is an ancestor of the deployed SHA
git -C /work/example/app-pos merge-base --is-ancestor <feature-sha> <staging-sha>
```

If the feature is NOT deployed, post a "BLOCKED — not deployed" comment
on the QA ticket and stop. Include:
- Current staging image tag
- Feature commit SHA
- Gap size (number of commits between)

#### 1.3 Understand the UI Flow

Read the relevant frontend code to understand:
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
SCREENSHOT_DIR = "/tmp"
VIDEO_DIR = "/tmp/Dev10x/self-qa/qa-<ticket>-video"
```

#### 2.2 Required Patterns

Follow these patterns learned from production QA sessions:

**Viewport + Video Recording**: Always use `1680x1050` (app-e2e standard).
Enable video recording on the test context (see **Two-phase recording**
below for where this fits):
```python
os.makedirs(VIDEO_DIR, exist_ok=True)
context = browser.new_context(
    viewport={"width": 1680, "height": 1050},
    record_video_dir=VIDEO_DIR,
    record_video_size={"width": 1680, "height": 1050},
)
```

**Video pacing**: Add `time.sleep(1)` pauses after filling forms and
`time.sleep(2)` after results appear so the video is reviewable.

**Finalize video**: Close the context (not just the browser) to flush:
```python
context.close()
browser.close()
```

**Two-phase recording** (keeps video focused on test cases, not login/setup):
```python
# Phase 1: authenticate + create test data WITHOUT video
setup_context = browser.new_context(
    viewport={"width": 1680, "height": 1050},
)
setup_page = setup_context.new_page()
setup_cf_headers(setup_page)
login(setup_page)
wo_url = create_new_wo(setup_page)
storage_state = setup_context.storage_state()
setup_context.close()

# Phase 2: reuse auth cookies, start recording on the target page
context = browser.new_context(
    viewport={"width": 1680, "height": 1050},
    record_video_dir=VIDEO_DIR,
    record_video_size={"width": 1680, "height": 1050},
    storage_state=storage_state,
)
page = context.new_page()
page.goto(wo_url, wait_until="networkidle")
```

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

**Cursor + click overlay** (visual tracking for video reviewers):

Inject a red cursor dot and click ripple animation after navigating to the
target page. Playwright headless doesn't render a system cursor in video,
so this JS overlay makes actions visible. Call `inject_overlay(page)` once
after `page.goto()`, then use `move_cursor_to(page, locator)` before
interactions to guide the viewer's eye.

```python
OVERLAY_JS = """
(() => {
    if (document.getElementById('qa-cursor')) return;
    const cursor = document.createElement('div');
    cursor.id = 'qa-cursor';
    cursor.style.cssText = `
        position: fixed; z-index: 999999; pointer-events: none;
        width: 20px; height: 20px; border-radius: 50%;
        background: rgba(255, 50, 50, 0.7);
        border: 2px solid rgba(255, 255, 255, 0.9);
        box-shadow: 0 0 8px rgba(255, 50, 50, 0.5);
        transform: translate(-50%, -50%);
        transition: left 0.05s linear, top 0.05s linear;
        left: -100px; top: -100px;
    `;
    document.body.appendChild(cursor);
    const style = document.createElement('style');
    style.textContent = `
        @keyframes qa-ripple {
            0%   { transform: translate(-50%,-50%) scale(0.5); opacity: 1; }
            100% { transform: translate(-50%,-50%) scale(3);   opacity: 0; }
        }
        .qa-click-ripple {
            position: fixed; z-index: 999998; pointer-events: none;
            width: 20px; height: 20px; border-radius: 50%;
            border: 3px solid rgba(255, 50, 50, 0.8);
            animation: qa-ripple 0.6s ease-out forwards;
        }
    `;
    document.head.appendChild(style);
    document.addEventListener('mousemove', e => {
        cursor.style.left = e.clientX + 'px';
        cursor.style.top  = e.clientY + 'px';
    }, true);
    document.addEventListener('click', e => {
        const ripple = document.createElement('div');
        ripple.className = 'qa-click-ripple';
        ripple.style.left = e.clientX + 'px';
        ripple.style.top  = e.clientY + 'px';
        document.body.appendChild(ripple);
        setTimeout(() => ripple.remove(), 700);
    }, true);
})();
"""

def inject_overlay(page: Page):
    page.evaluate(OVERLAY_JS)

def move_cursor_to(page: Page, locator, pause: float = 0.3):
    box = locator.bounding_box()
    if box:
        cx = box["x"] + box["width"] / 2
        cy = box["y"] + box["height"] / 2
        page.mouse.move(cx, cy, steps=15)
        time.sleep(pause)
```

**Subtitle overlay** (announce each TC and results on video):

The `OVERLAY_JS` above also creates a `#qa-subtitle` bar. Add it inside
the same `OVERLAY_JS` block, after the cursor element:

```python
# Inside OVERLAY_JS, after cursor setup:
const bar = document.createElement('div');
bar.id = 'qa-subtitle';
bar.style.cssText = `
    position: fixed; bottom: 30px; left: 50%; transform: translateX(-50%);
    z-index: 999999; pointer-events: none;
    background: rgba(0, 0, 0, 0.8); color: #fff;
    font-size: 22px; font-family: Arial, sans-serif; font-weight: 600;
    padding: 12px 32px; border-radius: 8px;
    max-width: 80%; text-align: center;
    opacity: 0; transition: opacity 0.4s ease;
`;
document.body.appendChild(bar);
```

Then call `subtitle()` before each TC and after results:

```python
def subtitle(page: Page, text: str, duration: float = 3.0):
    safe = text.replace("\\", "\\\\").replace("'", "\\'")
    page.evaluate(f"""(() => {{
        const bar = document.getElementById('qa-subtitle');
        if (!bar) return;
        bar.textContent = '{safe}';
        bar.style.opacity = '1';
        setTimeout(() => {{ bar.style.opacity = '0'; }}, {int(duration * 1000)});
    }})();""")
    time.sleep(0.5)

# Usage — describe the USER BENEFIT, not implementation details:
subtitle(page, "TC1: Pick a customer — one click assigns them, no Save needed", 4)
# ... run TC1 ...
subtitle(page, "Done! 'Hulk Smash' assigned instantly — no extra clicks", 3)
```

#### 2.3 Test Data Strategy

- **Self-contained tests**: Create test data within the test, don't
  depend on pre-existing records
- **Unique identifiers**: Use `uuid.uuid4().hex[:6]` for names,
  `random.randint(1000,9999)` for phone suffixes
- **Test order matters**: If tests depend on each other (e.g., create
  first, then duplicate), enforce ordering in the script
- **e2e_test_user is USER-level only (level=1)**: Has USER permissions for
  dealer 382. Cannot test features gated on dealer admin (level≥2) — e.g.
  reopen/void work orders. For admin-level tests use `janusz_ai` (level=2,
  dealer 585, password in `/work/example/app-e2e/settings.secrets.env` as
  `CRM_PASSWORD2`). Per-dealer constraints only fire within the same dealer.

#### 2.4 Screenshot Timing

Take screenshots **immediately** after the expected UI state appears:
- After success snackbar appears (before it auto-dismisses ~3s)
- After error message renders on the form
- Before closing dialogs

```python
# Wait for success indicator THEN screenshot immediately
try:
    page.wait_for_selector("text=Successfully updated", timeout=10000)
except Exception:
    time.sleep(3)  # fallback wait
screenshot(page, "test1-success.png")
```

### Phase 3: Execute Tests

#### 3.1 Install Playwright browsers (first time only)

```bash
uv run --with playwright python3 -m playwright install chromium
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

### Phase 4: Prepare Evidence

#### 4.1 Convert screenshots

Use the bundled conversion script:
```bash
${CLAUDE_PLUGIN_ROOT}/skills/qa-self/scripts/convert-evidence.sh \
  screenshots /tmp/Dev10x/self-qa/qa-test1.png /tmp/Dev10x/self-qa/qa-test2.png
```

Converts PNGs to JPGs (quality 70, max 1200px wide). Prints converted
file paths to stdout.

#### 4.2 Convert video

Playwright records video as `.webm`. Convert to `.mp4` for Linear:
```bash
${CLAUDE_PLUGIN_ROOT}/skills/qa-self/scripts/convert-evidence.sh \
  video /tmp/Dev10x/self-qa/qa-<ticket>-video/*.webm
```

Uses ffmpeg (`h264, crf 28, faststart`). Prints the `.mp4` path to
stdout.

#### 4.3 Upload to Linear

Use the upload script bundled with this skill (supports images and
video):
```bash
${CLAUDE_PLUGIN_ROOT}/skills/qa-self/scripts/upload-screenshots.py \
  upload /tmp/Dev10x/self-qa/qa-test1.jpg /tmp/Dev10x/self-qa/qa-test2.jpg /tmp/Dev10x/self-qa/qa-video.mp4
```

Output is JSON with `[{"file": "...", "url": "..."}]` — parse the URLs
for the comment.

**Key**: The script includes signed headers from the `fileUpload`
mutation response. Without these headers, uploads appear to succeed but
files fail to load.

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
| Feature "not deployed" on first check | Local argocd clone may be stale. Always `git -C /work/example/app-argocd fetch origin` before reading the image tag. |
| New WO page renders as skeleton | After "New Work Order" click, capture `page.url` then hard-navigate with `page.goto(new_wo_url)` to force a fresh render. |
| Dialog closes but status unchanged | `onClose` may be wired unconditionally (not to mutation success). Check DB or use `page.expect_response()` to confirm the mutation actually fired. A dialog can close via Escape, backdrop click, or explicit close handler without any mutation being called. |
| Video not finalized (0 bytes) | Must `context.close()` before `browser.close()` to flush video |
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
│   └── convert-evidence.sh (PNG→JPG, webm→mp4 conversion)
├── Reads: /work/example/app-argocd/ (verify deployment)
├── Reads: /work/example/app-admin/ (understand UI selectors)
└── Reads: /work/example/app-pos/ (understand backend behavior)
```
