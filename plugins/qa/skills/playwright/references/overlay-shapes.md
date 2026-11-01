# Overlay Shapes

Treatments beyond the pointer, ripple and single-line caption. All are
**opt-in and additive**: every one composes with the pointer halo and
`move_cursor_to()`, and none replaces it.

That constraint is not decoration. The source recording these shapes
came from had no cursor at all, which the QA guidance calls "the #1
miss" — these are attention-*labelling*, and a recording still needs
attention-*guiding*.

Read alongside [`redaction.md`](redaction.md) (the highest-priority
shape) and [`print-capture.md`](print-capture.md).

## Colour comes from the theme, never a literal

```python
anno = Annotator(page, theme=Theme(accent="#00a0ff"))
```

`Theme` carries `accent`, `accent_edge`, `surface`, `on_surface`,
`absence` and `redaction`. The defaults' *reasoning* generalises even
though the hexes do not: the accent is chosen to be absent from typical
app palettes so the pointer is never mistaken for UI, and the surface is
near-black and clearly *not the app* so a card is never read as a screen.

The source implementation hardcoded a brand orange — the exact literal
the originating repo's own guidelines name as the example of a colour
never to hardcode. It is deliberately not adopted here.

**Contrast is measured, not assumed.** No ratio was ever taken of the
source overlay. `Theme.assert_readable()` runs at construction and
refuses any palette whose text tokens fall below WCAG AA 4.5:1 on their
own surface; `tests/skills/playwright/test_annotate.py` pins the shipped
defaults. Accessibility is not a place to inherit a guess.

## Full-screen card

```python
anno.card([
    "How this was recorded",
    "Staging, fixture data — no production record appears.",
    "The print step is filmed from the share-link page.",
])
```

A one-line subtitle bar has nowhere to put framing that belongs to the
whole recording: how it was made, what the fixture is, what the footage
does and does not prove. Putting the caveats only in a ticket comment
means the video travels without them — which matters the moment it is on
YouTube and watched with no ticket in view.

Duration is **explicit** here, unlike a caption's, because a reader has
to finish eight lines. `card_dwell_ms()` allows ~1.3s per line (11s for
8 lines, 8s for 5, 12s for 9), measured against real footage and
deliberately generous: a caveat card that scrolls past unread defeats
its own purpose.

The card attaches to `documentElement`, not `body`, so it outlives a
body re-render. The first line auto-styles as a heading. Every line is
set with `textContent`; the only markup is the static wrapper, which
carries no caller text.

## Two-tier caption

```python
anno.say("Surface 1 of 3 — Vehicle Details",
         sub="The vehicle carries over from the estimate untouched")
```

A step frequently needs both a claim and the sentence explaining what
makes it correct, and one line forces the author to pick.

Dwell derives from **both** lines. Deriving it from the title alone is
how the longer two-tier captions came out too fast to finish — the
source author's own verdict on their fixed 2200–3600ms was that it was
"the weakest part and I would not port it".

## A treatment for absence

```python
anno.say("The tech's work-order copy is not shown — Print blocks capture",
         kind="absence")
```

QA evidence constantly has to say *we did NOT verify X*, and in a single
caption style that renders identically to a positive claim. A viewer
skimming cannot tell a demonstration from a disclaimer. The absence
caption is hollow and italic instead of solid.

It is simultaneously the caption most likely to be skipped and the most
damaging to skip.

## Step chip and real chapter timestamps

```python
anno.mark_video_start()          # right after the recorded context opens
...
anno.step(3, 4, "The decline survives the conversion")
...
for line in anno.chapter_lines():
    print(line)                  # 1:45 Approving converts the estimate
```

155 seconds of four test cases with nothing on screen naming the case in
flight forces a reviewer to scrub and guess. The chip is persistent,
unlike a caption.

**The chapter emission is the valuable half.** Its origin is a
self-reported defect worth keeping:

> "I hand-wrote chapter timestamps into the video description. Those are
> estimates. I inferred them from the pacing constants; I never measured
> them against the encoded file. They are close, and they are presented
> in a public description with the authority of measurements."

So `step()` measures `time.monotonic()` against `mark_video_start()`,
and `chapters()` **raises** when that anchor was never set rather than
emitting timestamps derived from nothing — the difference between making
a class of error impossible and merely discouraging it.

YouTube requires a chapter at `0:00`, so give the opening card a
`step()` too, or prepend one line by hand.

## Before / after on a changing value

```python
before = anno.capture_region(total)
anno.tap(decline_btn, announce="Declining the tyre")
anno.compare(total, before, caption="It leaves the bill")
```

A test case whose entire point is a value changing could otherwise only
*assert* the delta in a caption — asking the viewer to take it on trust
from the same automation whose correctness the video exists to
demonstrate. Circular, and the weakest moment in an otherwise decent
artifact.

With the before-crop pinned beside the live element the delta is
**shown**, and the caption goes back to saying why it matters rather
than what happened.

Generalises well past totals: any state flip a QA case turns on — a
status chip, a count, an enabled control, a row moving between sections.
*"A number moved because of what you just watched"* is close to the most
common QA-evidence shape there is.

## Highlight what is being read

```python
anno.highlight(row)
anno.say("This row is the one the estimate created")
anno.clear_highlight()
```

Distinct from the cursor, and the distinction is the point: the cursor
shows *where an action happens*; the highlight shows *what to read* on a
screen where nothing is being clicked. A walkthrough that mostly reads
state has no action primitive to reach for, and the fallback — scrolling
to it and naming it in prose — is strictly worse.

Pair it with `anno.hold()` at section boundaries; sections otherwise run
into each other with no beat.

## Zoom on a small target

```python
anno.zoom(line_item, factor=2.0, caption="Struck through, not removed")
```

Fine-grained typography — a strikethrough on a line item, a small status
pill — is near-unreadable once a 1680×1050 capture is downscaled by a
video player on a phone. The magnified crop sits *beside* the element
rather than replacing the frame, because losing page context defeats
showing the thing in situ.

**Recorded at the strength its author gave it:** they noticed this
reviewing frames but never tested whether a viewer actually fails to
read them. It is a hypothesis, which is why it is opt-in per call rather
than applied to every small target.
