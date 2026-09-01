---
name: Dev10x:tts
description: >
  Synthesize narration audio from text with a local Piper voice, and lay
  rendered lines onto a timeline as a single voice-over track for muxing
  over a screen recording.
  TRIGGER when: narration or voice-over audio is needed for a walkthrough
  recording, or a Dev10x:qa-self capture should be narrated.
  DO NOT TRIGGER when: capturing the recording itself (use Dev10x:qa-self),
  or converting/verifying evidence files (use qa-self's own scripts).
user-invocable: true
invocation-name: Dev10x:tts
allowed-tools:
  - Bash(${CLAUDE_PLUGIN_ROOT}/skills/tts/scripts/:*)
  - AskUserQuestion
---

# Dev10x:tts — Piper narration

Turns narration copy into audio with a locally-installed
[Piper](https://github.com/OHF-Voice/piper1-gpl) voice, then places the
rendered lines on a timeline so they can be muxed onto a recording.

Everything runs through `scripts/synthesize.py`. Never call `piper`
directly — the wrapper owns voice resolution, the licence gate, the
single-process batching, and the failure messages.

## Prerequisites

```bash
uv tool install piper-tts
```

A voice must be installed separately. The downloader lives inside the
tool's venv and is not on `PATH`:

```bash
~/.local/share/uv/tools/piper-tts/bin/python -m piper.download_voices \
  --download-dir ~/.local/share/piper/voices en_US-libritts_r-medium
```

`synthesize.py check` reports what is missing and prints the exact command
to fix it. `ffmpeg` is required only for `track`.

## Commands

| Command | Purpose |
|---|---|
| `check` | Is piper present, is the voice installed, what is it licensed for |
| `pin` | Persist the supervisor's voice choice to `~/.config/Dev10x/tts.yaml` |
| `batch` | Synthesize every segment — **one piper process for the whole batch** |
| `track` | Lay rendered segments at their offsets onto one voice-over WAV |

```bash
${CLAUDE_PLUGIN_ROOT}/skills/tts/scripts/synthesize.py check

echo '{"segments":[{"id":"tc1","text":"One click assigns them."}]}' \
  | ${CLAUDE_PLUGIN_ROOT}/skills/tts/scripts/synthesize.py batch --out-dir vo

${CLAUDE_PLUGIN_ROOT}/skills/tts/scripts/synthesize.py \
  track --segments-file vo/narration.json --out vo/track.wav
```

`batch` returns each segment's `wav` and exact `duration_ms`. `track`
consumes the same list with an `offset_ms` per segment.

Every command prints JSON to stdout. On failure it prints
`{"error": "..."}` to **stdout** and exits non-zero, so a caller parses one
channel and never sees empty output on failure.

## Voice licensing is the supervisor's call

Most good English Piper voices are **CC BY-NC-SA** — no commercial use. QA
evidence recorded for client work *is* commercial use. The wrapper reports
this and never enforces it: an unaccepted non-commercial voice yields a
`warning` in the payload and `licence_accepted: false`, and synthesis
proceeds anyway.

Licences are transcribed from the upstream `MODEL_CARD` files — a voice's
own `.onnx.json` has a `license` field that is `null` for every voice
checked. See [`references/voices.md`](references/voices.md) for the table
and how to verify a voice not listed there.

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text) before the
first synthesis in a session when `check` reports a `warning` — that is,
the resolved voice is non-commercial or unknown AND not yet accepted.
Options:

- **Use `en_US-libritts_r-medium` (Recommended)** — CC BY 4.0, commercial
  use permitted with attribution.
- **Keep `<voice>` and accept its terms** — records the acceptance so the
  gate does not fire again for that voice.
- **Cancel narration** — capture the recording silently.

On either *Use* / *Keep*, persist the answer so it is asked once:

```bash
${CLAUDE_PLUGIN_ROOT}/skills/tts/scripts/synthesize.py \
  pin --voice en_US-libritts_r-medium --accept-licence
```

When `check` reports `warning: null`, the gate does **not** fire — asking
on every run is the friction the pin exists to remove.

## Voice preference

Resolved highest-first: `--voice` → `DEV10X_PIPER_VOICE` → a matching
`projects[]` entry in `~/.config/Dev10x/tts.yaml` → its `defaults` →
the built-in `en_US-libritts_r-medium`.

```yaml
# ~/.config/Dev10x/tts.yaml
defaults:
  voice: en_US-libritts_r-medium
  licence_accepted: true
projects:
  - match: ["*/my-repo", "*/my-repo-*"]
    voice: en_US-ryan-medium
    licence_accepted: true
```

The file lives under `~/.config/Dev10x/` alongside the other durable prefs
(ADR-0018), so one answer covers a repo and every worktree of it, and no
self-settings consent gate fires. An acceptance is recorded **per voice** —
switching voices re-arms the gate rather than inheriting the old consent.

## Narrating a qa-self walkthrough

`Dev10x:qa-self` captions already carry narration copy. See
[`references/qa-self-narration.md`](references/qa-self-narration.md) for
the full recipe: declare the lines, attach `Narration` to the `Annotator`,
build the track, mux it on.

## Constraints worth knowing before writing copy

- **No SSML.** Pacing is `--length-scale` and `--sentence-silence` only —
  no per-word emphasis, no `<break>`.
- **One line per segment.** Piper emits one WAV per input *line*, which is
  what makes single-process batching work; the wrapper collapses whitespace
  and rejects an empty segment.
- **espeak reads punctuation literally.** Markdown, URLs, code identifiers
  and bare numbers are spoken as written — write narration copy, not
  documentation prose.
