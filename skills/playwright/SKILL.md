---
name: Dev10x:playwright
invocation-name: Dev10x:playwright
description: >
  Run Playwright Python scripts against ExampleCorp staging safely.
  Use when writing or executing a Playwright automation script for self-QA
  or browser testing on staging-app.example.com. Handles CF Access
  headers, credential injection, syntax validation before execution, and
  uv run wrapping — so secrets are never hardcoded in scripts.
  TRIGGER when: running browser automation against ExampleCorp staging.
  DO NOT TRIGGER when: testing non-ExampleCorp sites, running unit tests,
  or writing Playwright scripts for other projects.
allowed-tools:
  - Bash(${CLAUDE_PLUGIN_ROOT}/skills/playwright/scripts/:*)
---

# Dev10x:playwright

## Orchestration

This skill follows `references/task-orchestration.md` patterns.
Create a task at invocation, mark completed when done:

**REQUIRED: Create a task at invocation.** Execute at startup:

1. `TaskCreate(subject="Run Playwright script", activeForm="Running Playwright")`

Mark completed when done: `TaskUpdate(taskId, status="completed")`

## Overview

Wraps `uv run --with playwright python3` with:

1. **Syntax validation** — `python -m py_compile` before any browser launches
2. **Credential injection** — CF Access + CRM passwords read from
   `/work/example/app-e2e/settings.secrets.env` and passed as env vars, never
   hardcoded in scripts
3. **VIRTUAL_ENV suppression** — avoids the noisy uv warning
4. **Single allow rule** — the wrapper script can be pre-approved once

## Writing Playwright Scripts

Scripts live in `/tmp/Dev10x/playwright/qa-<ticket>-<description>.py`. They must read
credentials from environment variables injected by the wrapper:

```python
import os

CF_CLIENT_ID = os.environ["CF_CLIENT_ID"]
CF_SECRET    = os.environ["CF_SECRET"]
STAGING_URL  = os.environ["STAGING_URL"]
CRM_USERNAME = os.environ["CRM_USERNAME"]
CRM_PASSWORD = os.environ["CRM_PASSWORD"]
```

All five are set by the wrapper, so read them with `os.environ[...]` and
let a missing one fail loudly at import. A
`os.environ.get("STAGING_URL", "<host>")` default here is **dead code**
that reads as a working fallback — and while the wrapper's own
assignment was unconditional, that dead default was exactly what made
the resulting `ERR_NAME_NOT_RESOLVED` confusing to diagnose (GH-1130).

To point a run at a different deployment, set `STAGING_URL` in the
wrapper's environment; it now defers to a caller's value.

### Required Patterns

**CF headers** (all `*.example.com` requests):
```python
def setup_cf_headers(page):
    def add_cf_headers(route):
        headers = route.request.all_headers()
        headers["cf-access-client-id"] = CF_CLIENT_ID
        headers["cf-access-client-secret"] = CF_SECRET
        route.continue_(headers=headers)
    page.route("**/*.example.com/**", add_cf_headers)
```

**Viewport + video** (always 1680x1050):
```python
os.makedirs(VIDEO_DIR, exist_ok=True)
context = browser.new_context(
    viewport={"width": 1680, "height": 1050},
    record_video_dir=VIDEO_DIR,
    record_video_size={"width": 1680, "height": 1050},
)
```

**Flush video** — close context before browser:
```python
context.close()   # flushes video
browser.close()
```

**Login**:
```python
def login(page):
    page.goto(f"{STAGING_URL}/login", wait_until="networkidle")
    page.get_by_role("textbox", name="Username").fill(CRM_USERNAME)
    page.get_by_label("Password", exact=True).fill(CRM_PASSWORD)
    page.get_by_label("Remember Me").check()
    page.get_by_role("button", name="Continue").click()
    page.wait_for_url(re.compile(r"^(?!.*login)"), timeout=15000)
    page.wait_for_load_state("networkidle")
```

**GraphQL response capture**:
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

**Wait for mutation before screenshot**:
```python
with page.expect_response(
    lambda resp: "/graphql" in resp.url, timeout=15000
) as response_info:
    save_btn.click()
```

**Phone input** (mui-phone-number quirk — always prepend `1` for US):
```python
phone_input.click()
page.keyboard.press("Control+a")
page.keyboard.press("Backspace")
phone_input.type("16175551234", delay=50)
```

**Button clicks** — always scroll first:
```python
btn.scroll_into_view_if_needed()
time.sleep(0.5)
btn.click()
```

For a **recorded** run, use `Annotator.tap(btn, announce=..., then=...)`
from `lib/annotate.py` instead — it scrolls, asserts the target is
actually inside the viewport, points at it, narrates, acts, and holds a
beat, in the order a viewer needs. Every click on the recorded path goes
through it; a bare `locator.click()` cuts between two states with
nothing showing what was pressed.
See [`references/recording-for-humans.md`](references/recording-for-humans.md).

**Video pacing** — add sleeps for reviewable playback:
```python
time.sleep(1)  # after form fills
time.sleep(2)  # after result appears
```

### User Accounts

**The account map lives in the secrets file, not in this script**
(GH-1130). Accounts are keyed by an optional suffix shared between a
username and a password key:

```sh
CRM_USERNAME=e2e_test_user    CRM_PASSWORD=…      # the default profile
CRM_USERNAME2=janusz_ai       CRM_PASSWORD2=…     # --profile 2
CRM_USERNAME_QA=qa_bot        CRM_PASSWORD_QA=…   # --profile _QA
```

A third credential pair is two lines of config — no edit to the wrapper,
and no fork (a fork loses the syntax validation and the
no-hardcoded-credentials guarantee the wrapper exists to provide).

Select one either by name, which is resolved against the file:
```bash
${CLAUDE_PLUGIN_ROOT}/skills/playwright/scripts/run-playwright.sh \
  /tmp/Dev10x/playwright/qa-xxx.py --user janusz_ai
```

or by suffix, which skips the lookup:
```bash
${CLAUDE_PLUGIN_ROOT}/skills/playwright/scripts/run-playwright.sh \
  /tmp/Dev10x/playwright/qa-xxx.py --profile 2
```

`--user` with an unknown name lists what the secrets file does offer and
names the two keys to add. A secrets file carrying only `CRM_PASSWORD`
keeps working unsuffixed: the username falls back to `$CRM_USERNAME`,
then `$PLAYWRIGHT_DEFAULT_USER`, then `e2e_test_user`.

Which account a given feature needs — permission level, dealer scoping —
is a property of the deployment, not of this plugin. Record it in the
project's own notes alongside the secrets file.

## Running Scripts

### Validate only (no browser)
```bash
${CLAUDE_PLUGIN_ROOT}/skills/playwright/scripts/run-playwright.sh \
  /tmp/Dev10x/playwright/qa-xxx.py --validate-only
```

### Execute
```bash
${CLAUDE_PLUGIN_ROOT}/skills/playwright/scripts/run-playwright.sh /tmp/Dev10x/playwright/qa-xxx.py
```

The wrapper:
1. Reads `/work/example/app-e2e/settings.secrets.env`
2. Validates syntax with `python -m py_compile`
3. Exports credentials as env vars
4. Runs `VIRTUAL_ENV="" uv run --with playwright python3 <script>`

### Install browsers (first time)

Pin the version — an unbounded resolve picked up a release that refused
to install a browser on a current Linux distro, reporting it as an OS
problem rather than a resolver one (GH-1129):

```bash
uv run --with 'playwright>=1.47,<2' python3 -m playwright install chromium
```

`PLAYWRIGHT_SPEC` overrides the pin the wrapper runs scripts with.

## Common Failures

| Symptom | Fix |
|---|---|
| `KeyError: CF_CLIENT_ID` | Script uses hardcoded creds — replace with `os.environ[...]` |
| `net::ERR_NAME_NOT_RESOLVED` on the first `goto` | The run is pointed at the placeholder host. Set `STAGING_URL` in the wrapper's environment — it defers to a caller's value (GH-1130) |
| `--user` rejects an account that exists | Its `CRM_USERNAME<suffix>` / `CRM_PASSWORD<suffix>` pair is missing from the secrets file. The error names the two keys to add |
| Clicking Print hangs the run with no error | `window.print()` opens a browser modal that stops Playwright dead. Patch `print` in **both** realms — see [`references/print-capture.md`](references/print-capture.md) |
| PII wandered into frame | `Annotator(page, redact=[...])` — opaque masks that survive navigation. See [`references/redaction.md`](references/redaction.md) |
| Phone shows +61 | Prepend `1` for US country code |
| Button click doesn't register | `scroll_into_view_if_needed()` + `time.sleep(0.5)` |
| Screenshot misses snackbar | Screenshot immediately after `wait_for_selector`, not after sleep |
| Video 0 bytes | `context.close()` before `browser.close()` |
| Dialog closes, DB unchanged | Use `page.expect_response()` to confirm mutation fired |
| `VIRTUAL_ENV` warning | Wrapper suppresses with `VIRTUAL_ENV=""` |

## Integration

```
Dev10x:playwright
├── Called by: Dev10x:qa-self (Phase 3 execution)
├── Reads: /work/example/app-e2e/settings.secrets.env (credentials)
├── Scripts: run-playwright.sh (validate + inject + run)
└── Output: /tmp/Dev10x/playwright/  (screenshots, video)
```
