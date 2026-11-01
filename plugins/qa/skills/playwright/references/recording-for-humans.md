# Recording for Humans

Evidence recordings are watched by a person on a ticket. A recording
that is merely *present* is not evidence — the viewer has to be able to
follow what is being demonstrated without replaying it and guessing.

The rules below are evidence-validated: each one corresponds to a defect
that shipped a misleading or unusable recording (GH-1086, GH-1087).
`skills/playwright/lib/annotate.py` implements them; import it rather
than re-pasting an overlay into each generated script.

## Use the module, not an inline blob

```python
import sys

sys.path.insert(0, os.environ["DEV10X_PLAYWRIGHT_LIB"])
from annotate import Annotator

anno = Annotator(page)
anno.install()
```

`run-playwright.sh` exports `DEV10X_PLAYWRIGHT_LIB`, so the import path
does not have to be hard-coded in the generated script.

An overlay pasted inline into `instructions.md` cannot be linted,
imported, type-checked or unit-tested. That is why its navigation bug,
its JS-injection bug and its unusable pointer all survived: they were
documentation, not code.

## Overlay lifetime

Install through `add_init_script` (what `Annotator.install()` does), not
a bare `page.evaluate`. `page.evaluate` applies to the *current*
document; the next `goto` creates a new one and destroys the pointer,
the click listeners and the caption bar — while recording continues and
the run still passes.

The corollary at call sites: **set captions only after a navigation
completes.** A caption set before `goto` is wiped by the page load and
the step plays silently.

## Pointer

- **Tip is the anchor.** The arrow's path origin is its tip, so the
  widget's coordinate *is* the target coordinate. A symmetrical dot has
  no defined point — it can only indicate "somewhere around here", which
  is not enough for a grid cell, a table row or a checkbox.
- **Split widget.** A large near-transparent halo (~76px) centred on the
  tip is what the eye tracks across the frame; the small opaque arrow
  hangs below-right so it never covers what it points at.
- **Palette-absent colour.** Amber→red with a white ring, chosen to be
  absent from the app's own palette so the pointer is never mistaken for
  UI, and legible on light and dark surfaces alike.
- Never an emoji glyph: it has no defined point and cannot be aligned to
  a coordinate.

## Pointing proves the target is on screen

`point_at()` scrolls the target to the middle of the frame, waits for the
scroll to settle, and then asserts the box is inside the viewport — not
merely that `bounding_box()` returned something.

The distinction is the whole point. `bounding_box()` returns
coordinates for **anything attached and laid out**, so `None` comes back
only for a detached or `display:none` element. An element 200px below
the fold has a perfectly good box, and below-the-fold is the normal
state of most of a long page. A screenshot pointed at one is a real
picture of a real UI that does not show the thing being asserted — and
`verify-evidence.py` cannot catch it either, because its size floor and
non-uniform-frame checks are structurally incapable of catching *a
picture of the wrong thing* (GH-1129).

Merely on screen is not enough either. `scroll_into_view_if_needed()`
stops as soon as the element is *anywhere* in the viewport, so a target
one pixel under the fold lands flush against the bottom edge — which
passes the assertion and is still the worst place to point at: the caption
flips to the top to avoid the cursor, a sticky header can cover a top-edge
landing, and the viewer's eye leaves the middle of the frame to find the
target. `Annotator.center_on()` — which `point_at()`, `highlight()` and
`capture_region()` all go through, and which a step may call directly to
move the page without pointing — follows the minimum scroll with
`scrollIntoView({block: "center", inline: "center"})`, and the browser
clamps at the ends of the scroll range so the first and last screenful
centre as far as they can and no further.

That scroll is smooth — a viewer follows a page that moves and loses one
that cuts — and is waited out by **measuring** the box until it stops
moving, never by a fixed sleep: a box read mid-animation is a stale
coordinate, and the pointer lands where the target used to be.

## Pacing

- Caption dwell is computed **inside** `say()` from the caption's length
  (`min(6500, 1800 + 55 * len(text))` ms). One fixed duration either
  truncates a long caption or drags a short one.
- Never add per-call `wait_for_timeout` at call sites to compensate —
  that reintroduces the fixed-dwell problem one site at a time.
- Pointer settle is 0.6s. Below roughly half a second the movement reads
  as a teleport and the viewer never sees where the pointer went.
- **One knob, not four constants.** `Annotator(page, pace=1.6)` scales
  every derived duration together. The caption constants are read inside
  `caption_dwell_ms()` so patching the module global works, but
  `POINT_SETTLE_SECONDS` used to be bound as a *default argument* of
  `point_at()`, so patching it silently did nothing — two override
  mechanisms for one concept. `pace` replaces both.
- A narrated dwell is **not** scaled by `pace`: it is the measured length
  of the audio, and stretching it desyncs the caption from the voice.
- **Budget ~2.5 minutes of footage per four test cases** when every step
  is annotated. One measured run went 68s → 155s for four cases and was
  accepted first try. That is the cost of a followable recording, not
  overhead to trim.

## Ordering

`Annotator.click(target, announce=...)` does **point → narrate → act**,
in that order, and the ordering lives in the wrapper so no call site can
get it wrong. Narrating first describes a target that has not been
indicated yet, so the caption and the action refer to different moments.

**Every click on the recorded path goes through the wrapper.** This is a
rule, not an illustration for the interesting steps. A bare
`locator.click()` cuts between two states with nothing on screen saying
what was pressed, and lengthening the sleeps is the wrong fix — it holds
a still frame of an unexplained change for longer.

`Annotator.tap()` is the whole beat, so no script re-derives it:

```python
anno.tap(decline_btn,
         announce="Declining the tyre the customer didn't want",
         then="It's gone from the bill — the total dropped")
```

scroll → point → narrate → act → **beat** → outcome caption. Use
`click()` only when the following step supplies its own beat.

## Screenshot manifest

`shoot()` records what each artifact was pointed at, so Phase 4.4 review
reads as a specific comparison:

```python
anno.shoot(total, f"{SCREENSHOT_DIR}/tc3-total.png",
           claim="Declining the tyre removed it from the bill")

for row in anno.manifest_rows():
    print(row)     # tc3-total.png → Locator@... → Declining the tyre …
```

`target` is `repr(locator)` — Playwright's own selector description.
There is deliberately **no** author-written label parameter: a hand-typed
description drifts from the locator it claims to describe, and then the
manifest reassures the reviewer about the wrong thing.

"Does this look OK?" is a question people answer *yes* to while
skimming. "Does this image show **that** element?" is checkable in
seconds and fails visibly.

## Setup failures leave an artifact

The un-recorded setup phase has no video, so a locator timeout there
yields a stack trace and nothing else — and the next run is a guess.
Wrap each setup step:

```python
try:
    open_work_order(setup_page)
except Exception:
    print(json.dumps(debug_dump(setup_page, "open-work-order"), indent=2))
    raise
```

`debug_dump` writes a full-page screenshot and returns the sorted
accessible names of every button on the page. That found a drifted label
— the same control capitalised differently on two pages — on the very
next run.

## Resolution

Pick the viewport once, at context creation, and never resize it
mid-run — resizing silently changes the app's layout, so the recording
no longer shows what a user sees. Buy sharpness with a higher raster,
not with a mid-run resize:

```python
context = browser.new_context(
    viewport={"width": 1920, "height": 1080},
    device_scale_factor=2,
    record_video_dir=VIDEO_DIR,
    record_video_size={"width": 1920, "height": 1080},
)
```

**The viewport must be >= `record_video_size` (GH-1204).**
`record_video_size` only ever scales *down*. A smaller viewport is
placed 1:1 in the top-left of the frame and the rest is filled with
mid-grey, so `1680x1050` into `1920x1080` pads 240px right and 30px
bottom on every take. Matching the aspect ratio does not help —
`1680x945` is exactly 16:9 and pads just the same, because the rule is
a size relation, not an aspect relation. With the two equal,
`device_scale_factor=2` renders at 3840x2160 and Playwright scales that
down into the frame: a real supersample, and the only scaling direction
it supports.

## Beyond the pointer and one caption line

[`overlay-shapes.md`](overlay-shapes.md) — card, two-tier and absence
captions, step chip with measured chapters, before/after compare,
highlight, zoom, theme tokens. Each composes with the pointer; none
replaces it. Covering PII: [`redaction.md`](redaction.md). Print flows
that deadlock the run: [`print-capture.md`](print-capture.md).

## Captions describe the benefit

Write what the user gets ("One click assigns them — no Save needed"),
not what the test asserts ("TC1: should auto-save on onChange"). The
audience is a reviewer deciding whether the feature works, not a
maintainer reading the script.
