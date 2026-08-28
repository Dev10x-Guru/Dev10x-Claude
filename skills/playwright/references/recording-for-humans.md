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

## Pacing

- Caption dwell is computed **inside** `say()` from the caption's length
  (`min(6500, 1800 + 55 * len(text))` ms). One fixed duration either
  truncates a long caption or drags a short one.
- Never add per-call `wait_for_timeout` at call sites to compensate —
  that reintroduces the fixed-dwell problem one site at a time.
- Pointer settle is 0.6s. Below roughly half a second the movement reads
  as a teleport and the viewer never sees where the pointer went.

## Ordering

`Annotator.click(target, announce=...)` does **point → narrate → act**,
in that order, and the ordering lives in the wrapper so no call site can
get it wrong. Narrating first describes a target that has not been
indicated yet, so the caption and the action refer to different moments.

## Resolution

Keep the viewport at the app's designed size — resizing it silently
changes the app's layout, so the recording no longer shows what a user
sees. Buy sharpness instead with a higher raster and a Full HD
recording:

```python
context = browser.new_context(
    viewport={"width": 1680, "height": 1050},
    device_scale_factor=2,
    record_video_dir=VIDEO_DIR,
    record_video_size={"width": 1920, "height": 1080},
)
```

## Captions describe the benefit

Write what the user gets ("One click assigns them — no Save needed"),
not what the test asserts ("TC1: should auto-save on onChange"). The
audience is a reviewer deciding whether the feature works, not a
maintainer reading the script.
