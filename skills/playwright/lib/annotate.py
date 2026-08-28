"""Annotation overlay for Playwright recordings watched by humans.

Imported by generated QA scripts (``Dev10x:qa-self`` Phase 2) to make a
headless recording followable: a pointer that indicates one exact
coordinate, captions whose dwell is derived from their own length, and a
``click`` wrapper that fixes the point -> narrate -> act ordering.

Three properties are load-bearing and were each a defect before this
module existed (GH-1087, GH-1086):

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

The module imports no Playwright symbols at runtime so it can be loaded
and unit-tested without a browser environment.
"""

from __future__ import annotations

import time
from typing import Any

# Movement below ~0.5s reads as a teleport rather than a gesture, so the
# viewer never sees where the pointer went (GH-1087 finding #1.3 — the
# previous default was 0.3).
POINT_SETTLE_SECONDS = 0.6

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

  const state = { root: null, halo: null, arrow: null, caption: null, timer: null };

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
      return true;
    },
    caption(text, dwellMs) {
      build();
      if (!state.caption) return false;
      // textContent, not innerHTML — the caption is data, never markup.
      state.caption.textContent = text;
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

    Raises when the box is ``None`` — an off-screen or absent target is a
    capture defect, not something to point at approximately. A silent
    ``if box:`` guard here is how a step no-ops into empty evidence
    (GH-1086).
    """
    if box is None:
        raise ValueError(
            "target has no bounding box — it is detached or scrolled out of"
            " the viewport; scroll it into view before pointing at it"
        )
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


class Annotator:
    """Pointer + caption overlay bound to one Playwright page."""

    def __init__(self, page: Any) -> None:
        self._page = page

    def install(self) -> None:
        """Install the overlay for this document and every later one.

        ``add_init_script`` is registered on the browser *context*, so
        the overlay is rebuilt after each navigation; the immediate
        ``evaluate`` covers the document already loaded when this runs.
        """
        script = overlay_script()
        self._page.context.add_init_script(script)
        self._page.evaluate(script)

    def say(self, text: str, *, settle: bool = True) -> None:
        """Show a caption and hold for its length-derived dwell.

        Call this only AFTER a navigation completes — the overlay is
        re-created per document, so a caption set before ``goto`` is
        wiped by the page load and the step plays silently.
        """
        dwell = caption_dwell_ms(text)
        self._page.evaluate(
            "([text, dwell]) => window.__dxAnnotate.caption(text, dwell)",
            [text, dwell],
        )
        if settle:
            time.sleep(dwell / 1000)

    def point_at(self, locator: Any, *, settle: float = POINT_SETTLE_SECONDS) -> None:
        """Move the pointer onto ``locator`` and let the viewer register it."""
        x, y = target_center(locator.bounding_box())
        self._page.evaluate("([x, y]) => window.__dxAnnotate.point(x, y)", [x, y])
        self._page.mouse.move(x, y, steps=CURSOR_MOVE_STEPS)
        time.sleep(settle)

    def click(self, locator: Any, *, announce: str | None = None) -> None:
        """Point, then narrate, then act — in that order.

        Narrating first describes a target the viewer has not been shown
        yet, so the caption and the action refer to different moments.
        """
        locator.scroll_into_view_if_needed()
        self.point_at(locator)
        if announce:
            self.say(announce)
        locator.click()
