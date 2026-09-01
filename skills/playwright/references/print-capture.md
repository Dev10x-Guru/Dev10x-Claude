# Capturing a Print Flow

`window.print()` opens a browser modal that stops Playwright dead **with
no error** — the run just stops. Hit independently by two sessions, so
this one is corroborated rather than reported once.

It is nasty to diagnose cold: there is no exception, no timeout message,
and no failing assertion. The symptom is a script that produced fewer
artifacts than it should have and exited looking fine.

## Route 1 — neutralise `print` in both realms

The general pattern. The app-specific part is only the two selectors.

```python
context.add_init_script("() => { window.print = () => {}; }")

# Immediately before the click, patch the iframe's own realm too:
page.evaluate("""() => {
    const f = document.getElementById('printIframe');
    if (f && f.contentWindow) f.contentWindow.print = () => {};
}""")

anno.tap(print_btn, announce="Printing the work order")
page.wait_for_timeout(3500)

page.evaluate("""() => {
    const f = document.getElementById('printIframe');
    f.style.cssText = 'display:block;visibility:visible;position:fixed;'
        + 'top:0;left:0;width:100vw;height:100vh;border:0;'
        + 'background:#fff;z-index:2147483100';
}""")
page.emulate_media(media="print")
```

**Both patches are required.** The top window's `print` gets reassigned
by the app's own `useEffect`, and the iframe is a separate realm —
patching either one alone leaves the deadlock in place.

**The 3500ms is load-bearing, not padding.** The app copies the document
into the iframe asynchronously; rushing it reveals a blank frame.

This captured three separate print flows as real print output on video.

## Route 2 — film a different surface

Some apps expose a second surface that renders the same component
without a dialog — a share-link page, a preview route. Filming that is
simpler than patching two realms.

**But it only works where such a surface exists.** One session's
share-link page happened to render the same document component. That was
luck, not a general property of applications. Check for the surface
before planning around it; do not reach for this route and then discover
there is no share link.

## What to do when neither works

Say so on screen, in an absence caption rather than an ordinary one:

```python
anno.say("The tech's printed copy is not shown here — Print blocks capture",
         kind="absence")
```

A disclaimer rendered identically to a claim is a disclaimer a skimming
viewer will read as a demonstration. See
[`overlay-shapes.md`](overlay-shapes.md).
