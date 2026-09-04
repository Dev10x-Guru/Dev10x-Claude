# Narrating a qa-self walkthrough

`Dev10x:qa-self` captions are already narration copy — they describe the
user benefit ("One click assigns them, no Save needed"), not the assertion.
Narration speaks those same lines and keeps the caption on screen for
exactly as long as the speech takes.

Narration is **opt-in**. A capture that does not construct a `Narration`
behaves exactly as it did before this existed.

## 0. Clear the licence gate before capturing

`Narration.prerender()` shells out to the wrapper directly, so it does not
pass through `Dev10x:tts`'s own orchestration — the licence gate has to be
resolved here or it never fires on this path. Run the check first:

```bash
${CLAUDE_PLUGIN_ROOT}/skills/tts/scripts/synthesize.py check
```

When `warning` is non-null, apply the gate documented in
[`../SKILL.md`](../SKILL.md) § *Voice licensing is the supervisor's call*
— **REQUIRED: Call `AskUserQuestion`**, do NOT use plain text — before any
capture. When `warning` is `null`, proceed silently.

Do this BEFORE recording, not after: discovering the licence problem once
a walkthrough is already captured wastes the whole take.

## 1. Declare the lines up front

The generated test script gets a `NARRATION` list. This is the storyboard —
it is also the only place the narration copy is persisted, so keep it
ordered and readable.

```python
import os
import sys

sys.path.insert(0, os.environ["DEV10X_PLAYWRIGHT_LIB"])
from annotate import Annotator
from narration import Narration

NARRATION = [
    "Pick a customer. One click assigns them, no Save needed.",
    "Done. Assigned instantly, no extra clicks.",
]
```

Every line passed to `anno.say()` should appear here verbatim. A line that
does not is still shown and still recorded — it just plays silently, and
lands in the manifest's `unrendered` list so the gap is visible.

## 2. Anchor the timeline, then install

Playwright starts recording when the **context** is created, not when the
annotator installs. Call `mark_video_start()` immediately after the
recorded context opens, or every cue lands early by however long setup took.

```python
context = browser.new_context(
    viewport={"width": 1680, "height": 1050},
    device_scale_factor=2,
    record_video_dir=VIDEO_DIR,
    record_video_size={"width": 1920, "height": 1080},
    storage_state=storage_state,
)
narration = Narration(f"{RUN_DIR}/narration", script=NARRATION)
narration.mark_video_start()

page = context.new_page()
page.goto(wo_url, wait_until="networkidle")

anno = Annotator(page, narration=narration)
anno.install()          # pre-renders every line before the first caption
```

If `mark_video_start()` is never called the offsets are relative to
`install()` instead, and the manifest records `anchor: "install"` — an
approximate anchor that says so, rather than a silently wrong one.

## 3. Narrate as usual

No call-site changes. `say()` and `click(announce=...)` pick up the audio
duration automatically:

```python
anno.say("Pick a customer. One click assigns them, no Save needed.")
anno.click(customer_row, announce="Choosing Hulk Smash from the list")
```

## 4. Write the manifest after the context closes

```python
context.close()
browser.close()
narration.write_manifest()      # <RUN_DIR>/narration/narration.json
```

## 5. Build the track and mux it

After Phase 4.3 has produced the `.mp4`:

```bash
${CLAUDE_PLUGIN_ROOT}/skills/tts/scripts/synthesize.py \
  track --segments-file <RUN_DIR>/narration/narration.json \
        --out <RUN_DIR>/narration/track.wav

${CLAUDE_PLUGIN_ROOT}/skills/qa-self/scripts/convert-evidence.sh \
  narrate <RUN_DIR>/video/qa-<ticket>.mp4 <RUN_DIR>/narration/track.wav
```

The mux copies the video stream untouched and does **not** pass
`-shortest`, so a voice-over that ends before the recording does cannot
truncate the closing frames.

Upload the `-narrated.mp4` in place of the silent one — do not upload both.

## Timing model

| Quantity | Source |
|---|---|
| Caption dwell | pre-rendered audio duration + 700 ms tail |
| Cue offset | monotonic clock at the moment the caption is shown |
| Track length | last cue + its clip length |

Recording the offset **before** the caption is displayed is deliberate: the
offset must mark when the viewer first sees the line, which is also when
the audio must start. Recording it after `say()`'s settle sleep would cue
every clip one full dwell late.

## Cost

Pre-rendering happens during `install()`, before the first caption, so it
never freezes a frame mid-take whichever engine renders it. What it costs
depends on the voice:

- **Piper** — one process for the whole script; measured ~1.0 s for three
  lines, against ~0.7 s each when run separately.
- **Kokoro** — one process *per line*, ~5 s each, because `kokoro-tts`
  emits one audio file per run. A twenty-caption walkthrough is a couple of
  minutes of setup. Worth it for the Apache-2.0 licence on English; reach
  for a Piper voice when the script is long and the timbre allows it.
