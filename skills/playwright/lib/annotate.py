"""Annotation overlay for Playwright recordings watched by humans.

Imported by generated QA scripts (``Dev10x:qa-self`` Phase 2) to make a
headless recording followable: a pointer that indicates one exact
coordinate, captions whose dwell is derived from their own length, and a
``click`` wrapper that fixes the point -> narrate -> act ordering.

An optional ``Narration`` (``narration.py``) speaks the captions as well
as showing them; without one this module behaves exactly as it did before
narration existed.

Five properties are load-bearing and were each a defect before this
module existed (GH-1087, GH-1086, GH-1129):

1. **The overlay survives navigation.** It installs through
   ``add_init_script``, which every new document re-runs. The previous
   ``page.evaluate(OVERLAY_JS)`` form applied to the current document
   only, so the cursor and captions vanished after the first ``goto``
   while recording continued and the run still passed.
2. **Caption text is passed as an argument, never interpolated.**
   Building JS by f-string meant a newline, a backtick or ``</script>``
   in a caption produced broken JS — one unescaped backtick uninstalled
   the whole overlay and cost a recording cycle.
3. **The pointer has a defined point.** A symmetrical dot indicates
   "somewhere around here"; an arrow whose tip is the path origin can be
   aligned to a grid cell, table row or checkbox.
4. **Pointing scrolls first and then asserts the viewport.**
   ``bounding_box()`` returns coordinates for anything laid out, so an
   element below the fold has a perfectly good box. Checking only for
   ``None`` caught detached elements — which are rare — and let
   below-the-fold elements, which are the normal state of a long page,
   ship as evidence for a claim they do not show (GH-1129).
5. **The caption never lands on the evidence.** It sits at the bottom
   until the pointer enters the lower third of the frame, then flips to
   the top. Overlapping the pointed-at target is caught only by
   extracting frames, and costs a re-record.

The module imports no Playwright symbols at runtime so it can be loaded
and unit-tested without a browser environment.
"""

from __future__ import annotations

import os
import time
from typing import Any

# Movement below ~0.5s reads as a teleport rather than a gesture, so the
# viewer never sees where the pointer went (GH-1087 finding #1.3 — the
# previous default was 0.3).
#
# Every duration below is multiplied by ``Annotator(pace=...)``. One knob
# on the object replaced four module constants with two different
# override mechanisms: the caption constants are read *inside*
# ``caption_dwell_ms`` so patching them works, while the old
# ``settle=POINT_SETTLE_SECONDS`` default argument bound at import time,
# so patching it silently did nothing (GH-1129).
POINT_SETTLE_SECONDS = 0.6

# Held after a scroll so the app's own smooth-scroll animation finishes
# before the bounding box is measured. A box read mid-animation is a
# stale coordinate, and the pointer lands where the target used to be.
SCROLL_SETTLE_SECONDS = 0.4

# Held after an action so the viewer sees the result as a state, not as
# a frame the recording cuts away from.
BEAT_SECONDS = 0.9

# Interpolated mouse steps. Enough for the halo to trace a visible path
# across the frame at recording frame rates.
CURSOR_MOVE_STEPS = 25

# Caption dwell bounds, in milliseconds. A single fixed duration either
# truncates a long caption or drags a short one, so dwell is computed
# from the caption's own length (see `caption_dwell_ms`).
CAPTION_BASE_MS = 1800
CAPTION_MS_PER_CHAR = 55
CAPTION_MAX_MS = 6500

# Amber-to-red is absent from the app palette, and the white ring keeps
# the pointer legible on both light and dark surfaces.
POINTER_COLOR = "#ff8a00"
POINTER_EDGE = "#e02b1d"

OVERLAY_JS = r"""
(() => {
  if (window.__dxAnnotate) return;

  const POINTER_COLOR = '__POINTER_COLOR__';
  const POINTER_EDGE = '__POINTER_EDGE__';

  const state = {
    root: null, halo: null, arrow: null, caption: null, timer: null,
    pointerY: null
  };

  // The caption lives at the bottom until the pointer enters the lower
  // third, then moves to the top. A caption printed over the element it
  // is describing is caught only by extracting frames (GH-1129).
  function placeCaption() {
    if (!state.caption) return;
    const h = window.innerHeight || 0;
    const low = state.pointerY !== null && h > 0 && state.pointerY > h * (2 / 3);
    state.caption.style.bottom = low ? 'auto' : '32px';
    state.caption.style.top = low ? '32px' : 'auto';
  }

  function build() {
    if (state.root || !document.body) return;

    const style = document.createElement('style');
    style.textContent = [
      '@keyframes dx-ripple {',
      '  0%   { transform: translate(-50%,-50%) scale(0.4); opacity: 0.9; }',
      '  100% { transform: translate(-50%,-50%) scale(3);   opacity: 0; }',
      '}',
      '.dx-click-ripple {',
      '  position: fixed; z-index: 2147483646; pointer-events: none;',
      '  width: 28px; height: 28px; border-radius: 50%;',
      '  border: 3px solid ' + POINTER_EDGE + ';',
      '  animation: dx-ripple 0.7s ease-out forwards;',
      '}'
    ].join('\n');
    document.head.appendChild(style);

    const root = document.createElement('div');
    root.id = 'dx-pointer';
    root.style.cssText = [
      'position: fixed', 'z-index: 2147483647', 'pointer-events: none',
      'left: -400px', 'top: -400px', 'width: 0', 'height: 0',
      'transition: left 0.06s linear, top 0.06s linear'
    ].join(';');

    // Large, near-transparent halo centred ON the tip. The eye tracks
    // this across the frame; it never hides what it points at.
    const halo = document.createElement('div');
    halo.style.cssText = [
      'position: absolute', 'left: 50%', 'top: 50%',
      'margin-left: -38px', 'margin-top: -38px',
      'width: 76px', 'height: 76px', 'border-radius: 50%',
      'background: rgba(255, 138, 0, 0.18)',
      'border: 2px solid rgba(255, 255, 255, 0.55)'
    ].join(';');

    // Arrow tip is the path origin (0,0), so the widget's anchor point
    // IS the target coordinate. The body hangs below-right, clear of it.
    const arrow = document.createElement('div');
    arrow.style.cssText = 'position: absolute; left: 0; top: 0;';
    arrow.innerHTML = [
      '<svg width="34" height="40" viewBox="0 0 34 40" fill="none">',
      '<path d="M0 0 L0 27 L7.5 20.5 L12.5 32 L18.5 29 L13.5 18 L23 17 Z"',
      ' fill="', POINTER_COLOR, '" stroke="#ffffff" stroke-width="2"',
      ' stroke-linejoin="round"/>',
      '</svg>'
    ].join('');

    root.appendChild(halo);
    root.appendChild(arrow);
    document.body.appendChild(root);

    const caption = document.createElement('div');
    caption.id = 'dx-caption';
    caption.style.cssText = [
      'position: fixed', 'bottom: 32px', 'left: 50%',
      'transform: translateX(-50%)',
      'z-index: 2147483647', 'pointer-events: none',
      'background: rgba(0, 0, 0, 0.82)', 'color: #fff',
      'font: 600 22px/1.35 Arial, Helvetica, sans-serif',
      'padding: 12px 32px', 'border-radius: 8px',
      'max-width: 80%', 'text-align: center',
      'opacity: 0', 'transition: opacity 0.35s ease'
    ].join(';');
    document.body.appendChild(caption);

    state.root = root;
    state.halo = halo;
    state.arrow = arrow;
    state.caption = caption;

    document.addEventListener('click', (e) => {
      const ripple = document.createElement('div');
      ripple.className = 'dx-click-ripple';
      ripple.style.left = e.clientX + 'px';
      ripple.style.top = e.clientY + 'px';
      document.body.appendChild(ripple);
      setTimeout(() => ripple.remove(), 800);
    }, true);
  }

  window.__dxAnnotate = {
    point(x, y) {
      build();
      if (!state.root) return false;
      state.root.style.left = x + 'px';
      state.root.style.top = y + 'px';
      state.pointerY = y;
      placeCaption();
      return true;
    },
    caption(text, dwellMs) {
      build();
      if (!state.caption) return false;
      // textContent, not innerHTML — the caption is data, never markup.
      state.caption.textContent = text;
      placeCaption();
      state.caption.style.opacity = '1';
      if (state.timer) clearTimeout(state.timer);
      state.timer = setTimeout(() => {
        state.caption.style.opacity = '0';
      }, dwellMs);
      return true;
    }
  };

  if (document.body) {
    build();
  } else {
    document.addEventListener('DOMContentLoaded', build, { once: true });
  }
})();
"""


def overlay_script() -> str:
    """The overlay source with palette placeholders resolved."""
    return OVERLAY_JS.replace("__POINTER_COLOR__", POINTER_COLOR).replace(
        "__POINTER_EDGE__", POINTER_EDGE
    )


def caption_dwell_ms(text: str) -> int:
    """Milliseconds a caption stays on screen, derived from its length."""
    return min(CAPTION_MAX_MS, CAPTION_BASE_MS + CAPTION_MS_PER_CHAR * len(text))


def target_center(box: dict[str, float] | None) -> tuple[float, float]:
    """Centre of a Playwright ``bounding_box()``.

    Raises when the box is ``None`` — an absent target is a capture
    defect, not something to point at approximately. A silent ``if box:``
    guard here is how a step no-ops into empty evidence (GH-1086).

    A non-``None`` box proves only that the element is attached and laid
    out; see ``assert_in_viewport`` for the on-screen half.
    """
    if box is None:
        raise ValueError(
            "target has no bounding box — it is detached or display:none; it cannot be pointed at"
        )
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


def assert_in_viewport(
    box: dict[str, float] | None,
    viewport: dict[str, int] | None,
) -> None:
    """Raise unless ``box`` is at least partly inside ``viewport``.

    ``bounding_box()`` is viewport-relative but unbounded: an element
    200px below the fold reports ``y`` past the viewport height rather
    than ``None``. Checking only for ``None`` therefore catches detached
    elements — rare — and passes below-the-fold ones, which are the
    normal state of anything on a long page. That gap shipped two
    screenshots pointed at a figure nobody could see (GH-1129).

    ``verify-evidence.py`` cannot cover this: its size floor and
    non-uniform-frame checks are structurally incapable of catching a
    real picture of the wrong thing.

    A ``None`` viewport (a context created without one) disables the
    check rather than failing the run — there is no frame to be outside
    of.
    """
    target_center(box)
    assert box is not None
    if viewport is None:
        return
    below = box["y"] >= viewport["height"]
    above = box["y"] + box["height"] <= 0
    right = box["x"] >= viewport["width"]
    left = box["x"] + box["width"] <= 0
    if below or above or right or left:
        raise ValueError(
            "target is outside the viewport"
            f" (box y={box['y']:.0f} h={box['height']:.0f}"
            f" x={box['x']:.0f} w={box['width']:.0f};"
            f" viewport {viewport['width']}x{viewport['height']}) —"
            " a screenshot taken here is a picture of something else"
        )


def debug_dump(
    page: Any, tag: str, *, out_dir: str = "/tmp/Dev10x/self-qa/debug"
) -> dict[str, Any]:
    """Capture what a failed *un-recorded* setup step was looking at.

    A locator timeout during setup otherwise yields a stack trace and
    nothing else, so the next run is a guess. A full-page screenshot plus
    the sorted accessible names of every button found a drifted label —
    the same control capitalised differently on two pages — on the very
    next run (GH-1129).

    Returns the report rather than printing it: this module is imported
    by generated scripts, and the caller owns its own output. Wrap each
    setup step as ``except Exception: print(debug_dump(page, "step"));
    raise``.
    """
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{tag}.png")
    page.screenshot(path=path, full_page=True)
    names = page.evaluate(
        "() => Array.from(document.querySelectorAll("
        "'button,[role=button],a[href],input[type=submit]'))"
        ".map(el => (el.getAttribute('aria-label') || el.textContent || '').trim())"
        ".filter(Boolean)"
    )
    return {
        "tag": tag,
        "url": page.url,
        "screenshot": path,
        "buttons": sorted({n for n in names if n}),
    }


class Annotator:
    """Pointer + caption overlay bound to one Playwright page.

    Pass a ``Narration`` (see ``narration.py``) to speak the captions as
    well as show them. Narration is opt-in: without one, every behaviour
    below is exactly what it was before narration existed.
    """

    def __init__(
        self,
        page: Any,
        narration: Any | None = None,
        *,
        pace: float = 1.0,
    ) -> None:
        self._page = page
        self._narration = narration
        self._pace = pace
        self._manifest: list[dict[str, str]] = []

    @property
    def pace(self) -> float:
        """Multiplier on every derived duration this Annotator holds for."""
        return self._pace

    @property
    def manifest(self) -> list[dict[str, str]]:
        """One ``file`` / ``target`` / ``claim`` row per ``shoot()`` call."""
        return list(self._manifest)

    def install(self) -> None:
        """Install the overlay for this document and every later one.

        ``add_init_script`` is registered on the browser *context*, so
        the overlay is rebuilt after each navigation; the immediate
        ``evaluate`` covers the document already loaded when this runs.

        With narration attached this also pre-renders every declared line
        in one piper process, so no ``say()`` pays a model load mid-take.
        """
        script = overlay_script()
        self._page.context.add_init_script(script)
        self._page.evaluate(script)
        if self._narration is not None:
            self._narration.prerender()

    def say(self, text: str, *, settle: bool = True) -> None:
        """Show a caption and hold for as long as it takes to read or hear.

        Dwell comes from the narration audio when this line was
        pre-rendered, and from the caption's own length otherwise. Deriving
        it from the audio is what keeps the caption and the voice-over on
        the same beat — two independent estimates drift.

        Call this only AFTER a navigation completes — the overlay is
        re-created per document, so a caption set before ``goto`` is
        wiped by the page load and the step plays silently.
        """
        dwell = None
        if self._narration is not None:
            dwell = self._narration.dwell_ms(text)
        if dwell is None:
            # ``pace`` scales the *estimate* only. A narrated dwell is the
            # measured length of the audio; stretching it would desync the
            # caption from the voice it was derived from.
            dwell = int(caption_dwell_ms(text) * self._pace)

        # Record BEFORE the caption is shown: the offset must mark when the
        # viewer first sees the line, which is also when the audio must
        # start. Recording after the settle sleep would cue every clip one
        # dwell late.
        if self._narration is not None:
            self._narration.record(text, dwell)

        self._page.evaluate(
            "([text, dwell]) => window.__dxAnnotate.caption(text, dwell)",
            [text, dwell],
        )
        if settle:
            time.sleep(dwell / 1000)

    def point_at(self, locator: Any, *, settle: float | None = None) -> None:
        """Scroll ``locator`` into view, point at it, prove it is on screen.

        The scroll matches ``click()``, which has always done it. Without
        it the pointer lands on a coordinate outside the frame and the
        caption describes something the viewer cannot see — and because
        ``bounding_box()`` answers for anything laid out, nothing
        downstream notices (GH-1129).

        ``settle`` defaults to ``POINT_SETTLE_SECONDS * pace``; the module
        constant is read here rather than bound as a default argument, so
        patching it in a test actually takes effect.
        """
        locator.scroll_into_view_if_needed()
        time.sleep(SCROLL_SETTLE_SECONDS * self._pace)

        box = locator.bounding_box()
        assert_in_viewport(box, self._page.viewport_size)
        x, y = target_center(box)

        self._page.evaluate("([x, y]) => window.__dxAnnotate.point(x, y)", [x, y])
        self._page.mouse.move(x, y, steps=CURSOR_MOVE_STEPS)
        time.sleep(POINT_SETTLE_SECONDS * self._pace if settle is None else settle)

    def click(self, locator: Any, *, announce: str | None = None) -> None:
        """Point, then narrate, then act — in that order.

        Narrating first describes a target the viewer has not been shown
        yet, so the caption and the action refer to different moments.
        """
        self.point_at(locator)
        if announce:
            self.say(announce)
        locator.click()

    def tap(
        self,
        locator: Any,
        *,
        announce: str | None = None,
        then: str | None = None,
    ) -> None:
        """``click()`` plus the beat that lets the result register.

        The whole recorded path goes through this, not through bare
        ``locator.click()``. A bare click cuts between two states with
        nothing on screen saying what was pressed, and lengthening the
        sleeps does not fix it — it holds a still frame of an unexplained
        change for longer. Budget roughly 2.5 minutes per four test cases
        for a fully narrated path (GH-1129).

        ``then`` captions the outcome once the action has landed, which
        is the sentence a viewer needs and the one call sites most often
        forget to write.
        """
        self.click(locator, announce=announce)
        self.hold()
        if then:
            self.say(then)

    def hold(self, seconds: float | None = None) -> None:
        """Hold the current frame — a beat, not a pause for loading."""
        time.sleep((BEAT_SECONDS if seconds is None else seconds) * self._pace)

    def shoot(self, locator: Any, path: str, *, claim: str) -> dict[str, str]:
        """Screenshot with the subject proven on screen, and record why.

        The manifest row is the counter-measure to the defect this
        module's viewport assertion also guards: it turns Phase 4.4
        review from "does this look OK?" — which people answer yes to
        while skimming — into "does this image show *that* element?".

        ``target`` is ``repr(locator)``, Playwright's own selector
        description. An author-written label is deliberately not offered:
        it drifts from the locator it claims to describe and then
        reassures the reviewer about the wrong thing.
        """
        self.point_at(locator)
        self._page.screenshot(path=path)
        row = {"file": os.path.basename(path), "target": repr(locator), "claim": claim}
        self._manifest.append(row)
        return row

    def manifest_rows(self) -> list[str]:
        """``file → target → claim``, one line per captured screenshot."""
        return [f"{r['file']} → {r['target']} → {r['claim']}" for r in self._manifest]
