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
   ship as evidence for a claim they do not show (GH-1129). The scroll
   *centres* the target rather than merely revealing it: a minimum scroll
   parks it against an edge, which passes the assertion and is still the
   worst place in the frame to put the thing being demonstrated
   (GH-1144).
5. **The caption never lands on the evidence.** It sits at the bottom
   until the pointer enters the lower third of the frame, then flips to
   the top. Overlapping the pointed-at target is caught only by
   extracting frames, and costs a re-record.

The module imports no Playwright symbols at runtime so it can be loaded
and unit-tested without a browser environment.
"""

from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import dataclass
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

# Where a pointed-at target belongs in the frame.
# ``scroll_into_view_if_needed()`` stops as soon as the element is
# *anywhere* in the viewport, so a target one pixel under the fold ends up
# flush against the bottom edge — legal for ``assert_in_viewport`` and the
# worst place to point at: the caption flips to the top to avoid the
# cursor, a sticky app header can cover a top-edge landing, and the
# viewer's eye has to leave the middle of the frame to find the target.
# ``block: 'center'`` puts it where the viewer is already looking, and the
# browser clamps at the ends of the scroll range on its own — which is what
# "centred if possible" means on the first and last screenful.
CENTER_SCROLL_JS = (
    "el => el.scrollIntoView({behavior: 'smooth', block: 'center', inline: 'center'})"
)

# The scroll is smooth because a viewer follows a page that moves and loses
# a page that cuts. It is then waited out by *measuring* the target instead
# of holding a fixed sleep: one fixed duration is simultaneously too short
# for a long smooth scroll — a box read mid-animation is a stale
# coordinate, and the pointer lands where the target used to be — and pure
# overhead on the common case where nothing had to move at all.
TARGET_TOP_JS = "el => el.getBoundingClientRect().top"
SCROLL_POLL_SECONDS = 0.1
SCROLL_STABLE_PX = 0.5
SCROLL_SETTLE_MAX_SECONDS = 2.0

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

# Full-screen card and two-tier caption dwell. A reader has to finish
# the card, so its duration is explicit rather than derived: 1.2-1.4s
# per line, measured against real footage (11s for 8 lines, 8s for 5,
# 12s for 9). Deliberately generous — a caveat card that scrolls past
# unread defeats its own purpose.
CARD_MS_PER_LINE = 1300
CARD_MIN_MS = 3000

# How often the redaction masks re-measure their targets. A mask that
# lags a scroll exposes what it is covering.
REDACTION_REFRESH_MS = 100


@dataclass(frozen=True)
class Theme:
    """Overlay colours, as tokens rather than literals.

    Every value here is overridable because a plugin ships to other
    brands. The reasoning behind the defaults generalises even though the
    hexes do not:

    - ``accent`` is amber, chosen to be absent from typical app palettes
      so the pointer is never mistaken for UI.
    - ``surface`` is near-black and clearly *not the app*, so a card is
      never read as a screen.

    Do not hardcode a brand colour here. The source implementation this
    module borrows shapes from used a literal that the originating repo's
    own guidelines name as the example of a colour never to hardcode
    (GH-1126) — that hex is deliberately not adopted.

    ``assert_readable()`` measures rather than assumes: no contrast ratio
    was ever taken of the source overlay, and accessibility is not a
    place to inherit a guess.
    """

    accent: str = POINTER_COLOR
    accent_edge: str = POINTER_EDGE
    surface: str = "#0c0e14"
    on_surface: str = "#ffffff"
    absence: str = "#ffd166"
    redaction: str = "#101014"

    def assert_readable(self, *, minimum: float = 4.5) -> None:
        """Raise unless every text colour clears WCAG AA on the surface."""
        for name in ("on_surface", "accent", "absence"):
            ratio = contrast_ratio(getattr(self, name), self.surface)
            if ratio < minimum:
                raise ValueError(
                    f"theme.{name} ({getattr(self, name)}) on"
                    f" theme.surface ({self.surface}) is {ratio:.2f}:1,"
                    f" below the {minimum}:1 floor"
                )


DEFAULT_THEME = Theme()


def _relative_luminance(hex_color: str) -> float:
    """WCAG 2.1 relative luminance of a ``#rrggbb`` colour."""
    raw = hex_color.lstrip("#")
    if len(raw) != 6:
        raise ValueError(f"expected #rrggbb, got {hex_color!r}")
    channels = []
    for offset in (0, 2, 4):
        value = int(raw[offset : offset + 2], 16) / 255
        channels.append(value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4)
    red, green, blue = channels
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(foreground: str, background: str) -> float:
    """WCAG 2.1 contrast ratio between two ``#rrggbb`` colours."""
    lighter = _relative_luminance(foreground)
    darker = _relative_luminance(background)
    if lighter < darker:
        lighter, darker = darker, lighter
    return (lighter + 0.05) / (darker + 0.05)


OVERLAY_JS = r"""
(() => {
  if (window.__dxAnnotate) return;

  const POINTER_COLOR = '__ACCENT__';
  const POINTER_EDGE = '__ACCENT_EDGE__';
  const SURFACE = '__SURFACE__';
  const ON_SURFACE = '__ON_SURFACE__';
  const ABSENCE = '__ABSENCE__';
  const REDACTION = '__REDACTION__';
  const REDACTION_REFRESH_MS = __REDACTION_REFRESH_MS__;

  const TOP = 2147483647;
  const UI_FONT = 'Arial, Helvetica, sans-serif';

  const state = {
    root: null, halo: null, arrow: null, caption: null, timer: null,
    pointerY: null,
    redactions: { selectors: [], regions: [] },
    redactionTimer: null
  };

  function maskLayer() {
    let layer = document.getElementById('dx-redactions');
    if (!layer && document.body) {
      layer = document.createElement('div');
      layer.id = 'dx-redactions';
      layer.style.cssText = 'position:fixed;inset:0;z-index:2147483642;pointer-events:none';
      document.body.appendChild(layer);
    }
    return layer;
  }

  function paintRedactions() {
    const layer = maskLayer();
    if (!layer) return;
    const boxes = [];
    state.redactions.selectors.forEach((selector) => {
      let found;
      try {
        found = document.querySelectorAll(selector);
      } catch (e) {
        return;   // a selector this document cannot parse masks nothing
      }
      found.forEach((el) => {
        const r = el.getBoundingClientRect();
        if (r.width > 0 && r.height > 0) boxes.push(r);
      });
    });
    state.redactions.regions.forEach((r) => boxes.push(r));

    while (layer.childElementCount > boxes.length) layer.lastElementChild.remove();
    while (layer.childElementCount < boxes.length) {
      const mask = document.createElement('div');
      mask.style.cssText = 'position:fixed;background:' + REDACTION + ';border-radius:3px';
      layer.appendChild(mask);
    }
    boxes.forEach((r, i) => {
      const mask = layer.children[i];
      mask.style.left = (r.x - 2) + 'px';
      mask.style.top = (r.y - 2) + 'px';
      mask.style.width = (r.width + 4) + 'px';
      mask.style.height = (r.height + 4) + 'px';
    });
  }

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
      'z-index: ' + TOP, 'pointer-events: none',
      'background: rgba(0, 0, 0, 0.82)', 'color: ' + ON_SURFACE,
      'font: 600 22px/1.35 ' + UI_FONT,
      'padding: 12px 32px', 'border-radius: 8px',
      'border: 2px solid transparent',
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
    caption(text, dwellMs, sub, kind) {
      build();
      if (!state.caption) return false;

      // textContent, not innerHTML — a caption is data, never markup.
      // The only markup here is the static two-tier wrapper, which
      // carries no caller text at all.
      state.caption.textContent = '';
      const title = document.createElement('div');
      title.textContent = text;
      state.caption.appendChild(title);

      if (sub) {
        const detail = document.createElement('div');
        detail.textContent = sub;
        detail.style.cssText = [
          'font: 400 15px/1.4 ' + UI_FONT, 'opacity: 0.78',
          'margin-top: 6px'
        ].join(';');
        state.caption.appendChild(detail);
      }

      // An absence caption says "we did NOT verify X". Rendering it
      // identically to a positive claim is how a viewer skimming cannot
      // tell a demonstration from a disclaimer (GH-1126).
      const absent = kind === 'absence';
      state.caption.style.background = absent ? 'transparent' : 'rgba(0, 0, 0, 0.82)';
      state.caption.style.color = absent ? ABSENCE : ON_SURFACE;
      state.caption.style.border = absent ? ('2px dashed ' + ABSENCE) : '2px solid transparent';
      state.caption.style.fontStyle = absent ? 'italic' : 'normal';
      state.caption.style.textShadow = absent ? '0 1px 3px rgba(0,0,0,0.95)' : 'none';

      placeCaption();
      state.caption.style.opacity = '1';
      if (state.timer) clearTimeout(state.timer);
      state.timer = setTimeout(() => {
        state.caption.style.opacity = '0';
      }, dwellMs);
      return true;
    },

    // Full-viewport interstitial. Appended to documentElement rather
    // than body so it outlives a body re-render.
    card(lines) {
      let el = document.getElementById('dx-card');
      if (!el) {
        el = document.createElement('div');
        el.id = 'dx-card';
        el.style.cssText = [
          'position: fixed', 'inset: 0', 'z-index: ' + TOP,
          'background: ' + SURFACE, 'color: ' + ON_SURFACE,
          'display: flex', 'flex-direction: column', 'justify-content: center',
          'padding: 0 90px', 'font: 400 20px/1.6 ' + UI_FONT
        ].join(';');
        document.documentElement.appendChild(el);
      }
      el.textContent = '';
      lines.forEach((line, i) => {
        const row = document.createElement('div');
        row.textContent = line;          // never innerHTML
        row.style.cssText = i === 0
          ? 'font: 700 40px/1.25 ' + UI_FONT + ';margin-bottom: 26px;color:' + POINTER_COLOR
          : 'margin-bottom: 11px';
        el.appendChild(row);
      });
      return true;
    },

    clearCard() {
      const el = document.getElementById('dx-card');
      if (el) el.remove();
      return true;
    },

    // Numbered step chip. Persistent, unlike a caption: a reviewer
    // scrubbing to case 3 needs to see which case is in flight at any
    // frame, not only while a caption happens to be up.
    step(label) {
      build();
      let el = document.getElementById('dx-step');
      if (!el) {
        el = document.createElement('div');
        el.id = 'dx-step';
        el.style.cssText = [
          'position: fixed', 'top: 24px', 'left: 24px', 'z-index: ' + TOP,
          'pointer-events: none', 'background: rgba(0, 0, 0, 0.82)',
          'color: ' + ON_SURFACE, 'font: 700 17px/1.3 ' + UI_FONT,
          'padding: 9px 18px', 'border-radius: 999px',
          'border-left: 4px solid ' + POINTER_COLOR
        ].join(';');
        document.body.appendChild(el);
      }
      el.textContent = label;
      return true;
    },

    // Outline on the element being *read*. The cursor shows where an
    // action happens; a walkthrough that mostly reads state has no
    // action to point at, and prose alone is strictly worse (GH-1126).
    highlight(box) {
      build();
      let el = document.getElementById('dx-highlight');
      if (!el) {
        el = document.createElement('div');
        el.id = 'dx-highlight';
        el.style.cssText = [
          'position: fixed', 'z-index: 2147483645', 'pointer-events: none',
          'border-radius: 6px', 'transition: all 0.25s ease',
          'border: 3px solid ' + POINTER_COLOR,
          'box-shadow: 0 0 0 9999px rgba(0,0,0,0.28)'
        ].join(';');
        document.body.appendChild(el);
      }
      el.style.left = (box.x - 4) + 'px';
      el.style.top = (box.y - 4) + 'px';
      el.style.width = (box.width + 8) + 'px';
      el.style.height = (box.height + 8) + 'px';
      return true;
    },

    clearHighlight() {
      const el = document.getElementById('dx-highlight');
      if (el) el.remove();
      return true;
    },

    // A pinned image beside a live element: the "before" crop for a
    // comparison, or a magnified crop for a small target. Both keep the
    // element itself on screen — losing page context defeats showing it
    // in situ.
    inset(dataUri, box, label, scale) {
      build();
      const el = document.createElement('div');
      el.className = 'dx-inset';
      const width = Math.max(box.width * scale, 120);
      const spaceLeft = box.x;
      const left = spaceLeft > width + 40 ? box.x - width - 24 : box.x + box.width + 24;
      el.style.cssText = [
        'position: fixed', 'z-index: 2147483644', 'pointer-events: none',
        'left: ' + Math.max(8, left) + 'px',
        'top: ' + Math.max(8, box.y - 12) + 'px',
        'background: ' + SURFACE, 'padding: 8px', 'border-radius: 8px',
        'border: 2px solid ' + POINTER_COLOR,
        'box-shadow: 0 8px 28px rgba(0,0,0,0.55)'
      ].join(';');

      const tag = document.createElement('div');
      tag.textContent = label;                      // never innerHTML
      tag.style.cssText = [
        'color: ' + ON_SURFACE, 'font: 700 13px/1.3 ' + UI_FONT,
        'margin-bottom: 6px', 'letter-spacing: 0.04em', 'text-transform: uppercase'
      ].join(';');

      const img = document.createElement('img');
      img.src = dataUri;
      img.style.cssText = 'display:block;width:' + width + 'px;height:auto;border-radius:4px';

      el.appendChild(tag);
      el.appendChild(img);
      document.body.appendChild(el);
      return true;
    },

    clearInsets() {
      document.querySelectorAll('.dx-inset').forEach((el) => el.remove());
      return true;
    },

    // Opaque masks over anything that must not reach the recording.
    // Re-measured on a timer rather than positioned once, because a mask
    // that lags a scroll exposes what it covers. Opaque, never blur:
    // blur is reversible enough to be a liability and reads as a
    // rendering artifact rather than a deliberate act (GH-1126).
    redact(spec) {
      // De-duplicating matters: each call to Annotator.redact registers a
      // fresh init script carrying the WHOLE list so far, so a new
      // document replays every one of them and would otherwise stack a
      // mask per registration.
      const merge = (current, incoming, key) => {
        const seen = new Set(current.map(key));
        return current.concat((incoming || []).filter((item) => {
          if (seen.has(key(item))) return false;
          seen.add(key(item));
          return true;
        }));
      };
      const identity = (item) => item;
      const asBox = (r) => [r.x, r.y, r.width, r.height].join(',');
      state.redactions.selectors = merge(state.redactions.selectors, spec.selectors, identity);
      state.redactions.regions = merge(state.redactions.regions, spec.regions, asBox);
      if (!state.redactionTimer) {
        state.redactionTimer = setInterval(paintRedactions, REDACTION_REFRESH_MS);
      }
      paintRedactions();
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


def overlay_script(theme: Theme | None = None) -> str:
    """The overlay source with theme placeholders resolved."""
    theme = DEFAULT_THEME if theme is None else theme
    tokens = {
        "__ACCENT__": theme.accent,
        "__ACCENT_EDGE__": theme.accent_edge,
        "__SURFACE__": theme.surface,
        "__ON_SURFACE__": theme.on_surface,
        "__ABSENCE__": theme.absence,
        "__REDACTION__": theme.redaction,
        "__REDACTION_REFRESH_MS__": str(REDACTION_REFRESH_MS),
    }
    script = OVERLAY_JS
    for placeholder, value in tokens.items():
        script = script.replace(placeholder, value)
    return script


def _js_literal(value: Any) -> str:
    """A JS literal for ``value``, safe to embed in an init script.

    Init scripts take no arguments — unlike ``evaluate``, which is how
    every piece of *caption text* reaches the page — so a redaction spec
    has to be serialised into the source. ``json.dumps`` produces a valid
    JS literal with every quote, backslash and newline escaped, and
    ``<`` is escaped too so the payload cannot terminate a surrounding
    element in any context that later inlines it.
    """
    return json.dumps(value).replace("<", "\\u003c")


def redaction_script(
    selectors: list[str],
    regions: list[dict[str, float]],
) -> str:
    """An init script re-applying these masks to every future document."""
    spec = _js_literal({"selectors": selectors, "regions": regions})
    return (
        "(() => { const apply = () => window.__dxAnnotate"
        f" && window.__dxAnnotate.redact({spec});"
        " if (document.body) { apply(); } else {"
        " document.addEventListener('DOMContentLoaded', apply, {once: true}); } })();"
    )


def _data_uri(png: bytes) -> str:
    """A ``data:`` URI for PNG bytes, for an ``img.src`` assignment."""
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def caption_dwell_ms(text: str, sub: str | None = None) -> int:
    """Milliseconds a caption stays on screen, derived from its length.

    A two-tier caption derives its dwell from **both** lines. Deriving it
    from the title alone is how the longer two-tier captions came out too
    fast to finish comfortably — the source implementation's own author
    rated its fixed 2200-3600ms the weakest part of that overlay and said
    not to port it (GH-1126).
    """
    length = len(text) + (len(sub) if sub else 0)
    return min(CAPTION_MAX_MS, CAPTION_BASE_MS + CAPTION_MS_PER_CHAR * length)


def card_dwell_ms(lines: list[str]) -> int:
    """Milliseconds a full-screen card holds, from its line count."""
    return max(CARD_MIN_MS, CARD_MS_PER_LINE * len(lines))


def format_timestamp(seconds: float) -> str:
    """``M:SS`` / ``H:MM:SS`` — the shape a chapter list wants."""
    total = int(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


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
        theme: Theme | None = None,
        redact: list[str] | None = None,
    ) -> None:
        self._page = page
        self._narration = narration
        self._pace = pace
        self._theme = DEFAULT_THEME if theme is None else theme
        self._theme.assert_readable()
        self._manifest: list[dict[str, str]] = []
        self._redact_selectors: list[str] = list(redact or [])
        self._redact_regions: list[dict[str, float]] = []
        self._video_start: float | None = None
        self._steps: list[dict[str, Any]] = []

    @property
    def theme(self) -> Theme:
        return self._theme

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
        up front, so no ``say()`` pays a model load mid-take. Piper renders
        the whole script in one process; a kokoro voice pays a load per
        line, which is setup cost rather than a frozen frame either way.
        """
        script = overlay_script(self._theme)
        self._page.context.add_init_script(script)
        self._page.evaluate(script)
        if self._redact_selectors or self._redact_regions:
            self._install_redactions()
        if self._narration is not None:
            self._narration.prerender()

    def _install_redactions(self) -> None:
        """(Re-)register the masks for this document and every later one.

        Registering through ``add_init_script`` is not a nicety. A mask
        applied with a bare ``evaluate`` evaporates at the first
        navigation *while recording continues*, so the author believes
        they are covered and the footage is not — strictly worse than no
        redaction at all, and the exact failure GH-1086/GH-1087
        documented for the overlay itself (GH-1126).
        """
        script = redaction_script(self._redact_selectors, self._redact_regions)
        self._page.context.add_init_script(script)
        self._page.evaluate(script)

    def redact(self, selector: str) -> None:
        """Cover every element matching ``selector`` with an opaque block.

        Declare the whole list once near the top of a script — as a
        ``redact=[...]`` argument or a run of these calls — so it reads
        as a policy statement rather than scattered calls that can be
        forgotten on the one page that matters.

        Opaque, never blur: blur is reversible enough to be a liability
        and reads as a rendering artifact rather than a deliberate act.
        """
        self._redact_selectors.append(selector)
        self._install_redactions()

    def redact_region(self, x: float, y: float, width: float, height: float) -> None:
        """Cover a fixed viewport rectangle — for chrome, not content."""
        self._redact_regions.append({"x": x, "y": y, "width": width, "height": height})
        self._install_redactions()

    def card(self, lines: list[str], *, ms: int | None = None) -> None:
        """Hold a full-viewport interstitial carrying framing prose.

        The subtitle bar is one line, so what was recorded, what the
        fixture is, and what the footage does and does not prove have
        nowhere to go. Putting the caveats only in a ticket comment means
        the video travels without them — which matters the moment it is
        on YouTube, watched with no ticket in view.

        Duration is explicit here, unlike a caption's: a reader has to
        finish eight lines. ``card_dwell_ms`` allows ~1.3s per line,
        deliberately generous, because a caveat card that scrolls past
        unread defeats its own purpose.
        """
        dwell = card_dwell_ms(lines) if ms is None else ms
        self._page.evaluate("(lines) => window.__dxAnnotate.card(lines)", lines)
        time.sleep(dwell * self._pace / 1000)
        self._page.evaluate("() => window.__dxAnnotate.clearCard()")

    def mark_video_start(self) -> None:
        """Anchor chapter offsets — call right after the recorded context opens."""
        self._video_start = time.monotonic()

    def step(self, index: int, total: int, title: str) -> dict[str, Any]:
        """Show a persistent "N of M" chip and record a chapter offset.

        A 155-second recording of four cases with nothing on screen
        naming the case in flight forces a reviewer to scrub and guess.

        The offset is **measured** here, against ``mark_video_start()``.
        Chapter timestamps inferred from the pacing constants and typed
        into a video description are estimates presented with the
        authority of measurements — an error a shape can make
        structurally impossible rather than merely discouraged (GH-1126).
        """
        offset = None if self._video_start is None else time.monotonic() - self._video_start
        self._page.evaluate(
            "(label) => window.__dxAnnotate.step(label)", f"{index} of {total} — {title}"
        )
        entry = {"index": index, "total": total, "title": title, "offset": offset}
        self._steps.append(entry)
        return entry

    def chapters(self) -> list[dict[str, Any]]:
        """Measured chapter list — offset, timestamp and label per step.

        Raises when ``mark_video_start()`` was never called rather than
        emitting timestamps derived from nothing. An unanchored chapter
        list looks exactly like a measured one and is the fabricated
        precision this method exists to prevent.
        """
        if any(entry["offset"] is None for entry in self._steps):
            raise ValueError(
                "chapter offsets are unanchored — call mark_video_start()"
                " immediately after the recorded context opens, before the"
                " first step()"
            )
        return [
            {
                "offset": entry["offset"],
                "timestamp": format_timestamp(entry["offset"]),
                "label": entry["title"],
            }
            for entry in self._steps
        ]

    def chapter_lines(self) -> list[str]:
        """``0:00 Label`` lines for a video description.

        A first chapter at ``0:00`` is required by YouTube, so an opening
        card should carry ``step(...)`` too — or prepend a line by hand.
        """
        return [f"{chapter['timestamp']} {chapter['label']}" for chapter in self.chapters()]

    def center_on(self, locator: Any) -> None:
        """Scroll ``locator`` to the middle of the frame, and wait it out.

        Every pointing entry point goes through here — the pointer, the
        read-highlight and the before-crop — so all three agree on where a
        point of interest belongs. ``scroll_into_view_if_needed()`` runs
        first because it realises a virtualised or lazily-mounted element
        that ``scrollIntoView`` alone would centre an empty box on; the
        centring scroll then moves it off whichever edge the minimum scroll
        left it against.

        The reference guidance used to be a ``block: 'center'`` snippet each
        script re-pasted at the call sites its author remembered — which is
        how the overlay's own bugs survived as documentation rather than
        code (GH-1087).
        """
        locator.scroll_into_view_if_needed()
        locator.evaluate(CENTER_SCROLL_JS)
        self._wait_for_scroll(locator)

    def _wait_for_scroll(self, locator: Any) -> None:
        """Hold until the target stops moving, or until the cap expires.

        Expiring returns rather than raises: a page with its own perpetual
        animation is still recordable, the measurement is then no worse than
        the fixed sleep this replaced, and ``assert_in_viewport`` still
        refuses a target that ended up off screen.
        """
        deadline = time.monotonic() + SCROLL_SETTLE_MAX_SECONDS * self._pace
        previous: float | None = None
        while True:
            current = locator.evaluate(TARGET_TOP_JS)
            if previous is not None and abs(current - previous) < SCROLL_STABLE_PX:
                return
            previous = current
            if time.monotonic() >= deadline:
                return
            time.sleep(SCROLL_POLL_SECONDS)

    def highlight(self, locator: Any) -> None:
        """Outline the element being *read*, and leave it outlined.

        Distinct from the pointer on purpose: the cursor shows where an
        action happens, the highlight shows what to read on a screen
        where nothing is being clicked. A walkthrough that mostly reads
        state has no action primitive to reach for, and naming the row in
        prose is strictly worse (GH-1126).
        """
        self.center_on(locator)
        box = locator.bounding_box()
        assert_in_viewport(box, self._page.viewport_size)
        self._page.evaluate("(box) => window.__dxAnnotate.highlight(box)", box)

    def clear_highlight(self) -> None:
        self._page.evaluate("() => window.__dxAnnotate.clearHighlight()")

    def capture_region(self, locator: Any) -> bytes:
        """Snapshot the pixels of ``locator`` — the "before" of a compare."""
        self.center_on(locator)
        return locator.screenshot()

    def compare(
        self,
        locator: Any,
        before: bytes,
        *,
        caption: str,
        sub: str | None = None,
        scale: float = 1.0,
    ) -> None:
        """Pin the captured "before" beside the live element and narrate.

        A test case whose entire point is a value changing can otherwise
        only *assert* the delta in a caption — which asks the viewer to
        take it on trust from the same automation whose correctness the
        video exists to demonstrate. Circular, and the weakest moment in
        an otherwise decent artifact (GH-1126).

        With the before-crop on screen the delta is **shown**, and the
        caption goes back to saying why it matters rather than what
        happened. Generalises past totals to any state flip a QA case
        turns on: a status chip, a count, an enabled control, a row
        moving between sections.
        """
        self.point_at(locator)
        box = locator.bounding_box()
        self._page.evaluate(
            "([uri, box, label, scale]) => window.__dxAnnotate.inset(uri, box, label, scale)",
            [_data_uri(before), box, "Before", scale],
        )
        self.say(caption, sub=sub)
        self._page.evaluate("() => window.__dxAnnotate.clearInsets()")

    def zoom(self, locator: Any, *, factor: float = 2.0, caption: str | None = None) -> None:
        """Magnify a small target in an inset *beside* it, not instead of it.

        Fine-grained typography — a strikethrough on a line item, a small
        status pill — is near-unreadable once a 1680x1050 capture is
        downscaled by a video player on a phone. The inset sits next to
        the element so page context survives; losing it defeats showing
        the thing in situ.

        Recorded at the strength its author gave it (GH-1126): they
        noticed this reviewing frames but never tested whether a viewer
        actually fails to read them. It is opt-in per call for that
        reason.
        """
        self.point_at(locator)
        box = locator.bounding_box()
        self._page.evaluate(
            "([uri, box, label, scale]) => window.__dxAnnotate.inset(uri, box, label, scale)",
            [_data_uri(locator.screenshot()), box, "Detail", factor],
        )
        if caption:
            self.say(caption)
        else:
            self.hold()
        self._page.evaluate("() => window.__dxAnnotate.clearInsets()")

    def say(
        self,
        text: str,
        *,
        sub: str | None = None,
        kind: str = "claim",
        settle: bool = True,
    ) -> None:
        """Show a caption and hold for as long as it takes to read or hear.

        ``sub`` adds a second, smaller tier — a step frequently needs
        both a claim ("Surface 1 of 3 — Vehicle Details") and the
        sentence explaining what makes it correct, and one line forces
        the author to pick. Dwell is derived from **both** lines.

        ``kind="absence"`` renders the caption hollow and italic instead
        of solid. QA evidence constantly has to say *we did NOT verify
        X*, and in a single style that renders identically to a positive
        claim — a viewer skimming cannot tell a demonstration from a
        disclaimer. It is simultaneously the caption most likely to be
        skipped and the most damaging to skip (GH-1126).

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
            dwell = int(caption_dwell_ms(text, sub) * self._pace)

        # Record BEFORE the caption is shown: the offset must mark when the
        # viewer first sees the line, which is also when the audio must
        # start. Recording after the settle sleep would cue every clip one
        # dwell late.
        if self._narration is not None:
            self._narration.record(text, dwell)

        self._page.evaluate(
            "([text, dwell, sub, kind]) => window.__dxAnnotate.caption(text, dwell, sub, kind)",
            [text, dwell, sub, kind],
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

        The scroll centres the target rather than merely revealing it (see
        ``center_on``), so the point of interest is in the middle of the
        frame where the viewer is already looking.

        ``settle`` defaults to ``POINT_SETTLE_SECONDS * pace``; the module
        constant is read here rather than bound as a default argument, so
        patching it in a test actually takes effect.
        """
        self.center_on(locator)

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
