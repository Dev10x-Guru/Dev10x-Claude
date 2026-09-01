# Redaction

Cover anything that must not reach the recording with an opaque block.

Requested independently by three sessions, each their top priority, and
the argument for it is the same each time: **the existing control is a
policy with no mechanism.**

`Dev10x:yt-upload` carries a hard prohibition on production recordings,
enforced by an `AskUserQuestion` gate. That gate asks the operator to
*state a judgment* — it cannot verify one. Two of the three sessions
published recordings to unlisted URLs containing a customer name, phone,
business name, email and the signed-in user's identity. All of it was
fixture data, and both cleared it the same way: by recognising the
fixture *by eye*, at the last gate, from sampled frames.

> "The reasoning was 'I recognise this fixture', which does not
> generalise."

The third session left no defect at all, and that is the more expensive
case: they narrowed *what they recorded* — staying on a single store for
the whole run — because nothing could obscure what wandered into frame.
Evidence that was never captured leaves no trace.

## Usage

Declare the list **once, near the top of the script**, so it reads as a
policy statement rather than scattered calls that can be forgotten on
the one page that matters:

```python
anno = Annotator(page, redact=[
    "[data-test='customer-name']",
    "[data-test='customer-phone']",
    ".signed-in-user",
])
anno.install()
```

`anno.redact(selector)` adds one later; `anno.redact_region(x, y, w, h)`
covers a fixed viewport rectangle, for chrome rather than content.

## Two properties, both non-obvious

**It re-applies through `add_init_script`, exactly like the overlay.**
A mask applied with a bare `page.evaluate` evaporates at the first
navigation *while recording continues* — the precise failure GH-1086 and
GH-1087 documented for the overlay itself. A redaction that silently
stops redacting is worse than none at all, because the author believes
they are covered.

Each `redact()` call re-registers the whole list so far, and the overlay
de-duplicates on replay, so masks never stack.

**Opaque, never blur.** Blur is reversible enough to be a liability, and
it reads as a rendering artifact rather than as a deliberate act. The
masks re-measure their targets every 100ms rather than positioning once,
because a mask that lags a scroll exposes what it is covering.

## What it unblocks

Environments where PII presence is not guaranteed are often exactly the
environments where the interesting bugs live. Redaction converts a hard
constraint — *we can only record on fixtures* — into a soft one: *we can
record anywhere and redact*.

**Prefer redaction over cropping.** Cropping removes the surrounding
layout that makes the evidence legible in the first place.

## What it does not do

It does not make a production recording acceptable. The `Dev10x:yt-upload`
provenance gate still fires, and still has to be answered honestly. What
redaction changes is that the answer can now rest on a declared list at
the top of the script rather than on a recollection of what the frames
looked like.
