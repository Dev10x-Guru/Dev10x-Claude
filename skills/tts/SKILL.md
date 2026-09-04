---
name: Dev10x:tts
description: >
  Synthesize narration audio from text with a local voice — Kokoro for
  English, Piper for Polish and everything else — and lay rendered lines
  onto a timeline as a single voice-over track for muxing over a screen
  recording.
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

# Dev10x:tts — narration, routed by language

Turns narration copy into audio with a locally-installed voice, then places
the rendered lines on a timeline so they can be muxed onto a recording.

Everything runs through `scripts/synthesize.py`. Never call `piper` or
`kokoro-tts` directly — the wrapper owns engine selection, voice
resolution, the licence gate, the batching, and the failure messages.

## Two engines, because neither covers the job

| | [Kokoro](https://huggingface.co/hexgrad/Kokoro-82M) | [Piper](https://github.com/OHF-Voice/piper1-gpl) |
|---|---|---|
| Weights | Apache-2.0 — commercial use welcomed | per-voice; most good English voices are CC BY-NC-SA |
| Languages | 8 (**no Polish**) | 30+, including five `pl_PL` voices |
| Batching | one process per segment (~5s each) | one process for the whole batch (~1s) |
| Blending | `--voice "af_sarah:60,am_adam:40"` | none |

So English routes to Kokoro — which makes the commercial-use question
disappear on the default path instead of being negotiated per voice — and
Polish routes to Piper, which is the only engine that can speak it at all.
Kokoro's `pf_`/`pm_` voices read as Polish at a glance and are Brazilian
Portuguese.

**You never name an engine.** It is inferred from the voice name's shape,
and the two namespaces cannot collide: `af_heart` is Kokoro,
`pl_PL-gosia-medium` is Piper.

## Prerequisites

```bash
uv tool install piper-tts
uv tool install kokoro-tts   # requires-python <3.13; add --python 3.12 if needed
```

Piper voices are downloaded per voice; the downloader lives inside the
tool's venv and is not on `PATH`:

```bash
~/.local/share/uv/tools/piper-tts/bin/python -m piper.download_voices \
  --download-dir ~/.local/share/piper/voices pl_PL-gosia-medium
```

Kokoro needs two files once, for all 50 voices:

```bash
mkdir -p ~/.local/share/kokoro
curl -L -o ~/.local/share/kokoro/kokoro-v1.0.onnx \
  https://github.com/nazdridoy/kokoro-tts/releases/download/v1.0.0/kokoro-v1.0.onnx
curl -L -o ~/.local/share/kokoro/voices-v1.0.bin \
  https://github.com/nazdridoy/kokoro-tts/releases/download/v1.0.0/voices-v1.0.bin
```

`synthesize.py check` reports both engines' readiness and prints the exact
command to fix whichever is missing. `ffmpeg` is required only for `track`.

## Commands

| Command | Purpose |
|---|---|
| `check` | Engine readiness (both), resolved voice, licence, acceptance |
| `pin` | Persist the supervisor's voice choice to `~/.config/Dev10x/tts.yaml` |
| `batch` | Synthesize every segment |
| `track` | Lay rendered segments at their offsets onto one voice-over WAV |

```bash
${CLAUDE_PLUGIN_ROOT}/skills/tts/scripts/synthesize.py check --lang pl

echo '{"segments":[{"id":"tc1","text":"One click assigns them."}]}' \
  | ${CLAUDE_PLUGIN_ROOT}/skills/tts/scripts/synthesize.py batch --out-dir vo

${CLAUDE_PLUGIN_ROOT}/skills/tts/scripts/synthesize.py \
  track --segments-file vo/narration.json --out vo/track.wav
```

`--lang` picks the voice for a language (`en`, `pl`); `--voice` names one
outright and outranks it.

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

**On the built-in paths the gate no longer fires at all**: Kokoro's weights
are Apache-2.0, and every `pl_PL` Piper voice is CC0, CC BY 4.0, or
Apache-2.0. It still fires for a Piper English voice chosen on purpose.

Piper licences are transcribed from the upstream `MODEL_CARD` files — a
voice's own `.onnx.json` has a `license` field that is `null` for every
voice checked. See [`references/voices.md`](references/voices.md) for both
engines' tables and how to verify a voice not listed there.

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text) before the
first synthesis in a session when `check` reports a `warning` — that is,
the resolved voice is non-commercial or unknown AND not yet accepted.
Options:

- **Switch to the commercial-safe default for this language (Recommended)**
  — `af_heart` (Apache-2.0) for English, `pl_PL-gosia-medium` (CC0) for
  Polish.
- **Keep `<voice>` and accept its terms** — records the acceptance so the
  gate does not fire again for that voice.
- **Cancel narration** — capture the recording silently.

On either *Switch* / *Keep*, persist the answer so it is asked once:

```bash
${CLAUDE_PLUGIN_ROOT}/skills/tts/scripts/synthesize.py \
  pin --voice af_heart --accept-licence
```

When `check` reports `warning: null`, the gate does **not** fire — asking
on every run is the friction the pin exists to remove.

## Voice preference

Without `--lang`, resolved highest-first: `--voice` → `DEV10X_TTS_VOICE`
(or its `DEV10X_PIPER_VOICE` predecessor) → a matching `projects[]` entry
in `~/.config/Dev10x/tts.yaml` → its `defaults` → the built-in `af_heart`.

**With** `--lang` (or `DEV10X_TTS_LANG`), the language-agnostic `voice:`
keys are skipped entirely and only `languages:` blocks are consulted — a
globally pinned English voice must not end up narrating Polish. An unknown
language is an error naming the pin command, never a silent fall back to
English.

```yaml
# ~/.config/Dev10x/tts.yaml
defaults:
  voice: af_heart                    # used when no language is requested
  licence_accepted: true
  languages:
    en: {voice: af_heart, licence_accepted: true}
    pl: {voice: pl_PL-gosia-medium, licence_accepted: true}
projects:
  - match: ["*/my-repo", "*/my-repo-*"]
    languages:
      pl: {voice: pl_PL-bass-high, licence_accepted: true}
```

`pin --lang pl --voice pl_PL-bass-high` writes that nested block and leaves
the English default — and its recorded acceptance — untouched.

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

- **No SSML, on either engine.** Pacing is `--length-scale` only — no
  per-word emphasis, no `<break>`. Kokoro receives its reciprocal as
  `--speed`. `--sentence-silence` and `--speaker` are Piper-only and fail
  loudly on a Kokoro voice rather than being silently dropped.
- **One line per segment.** Piper emits one WAV per input *line*, which is
  what makes its single-process batching work; the wrapper collapses
  whitespace and rejects an empty segment.
- **Kokoro is ~5s per segment.** It emits one audio file per run and its
  `--split-output` chunks by size rather than by line, so there is no
  batched shape that preserves the caption mapping. For a long script where
  the timbre allows it, a Piper voice renders the whole batch in ~1s.
- **espeak reads punctuation literally.** Markdown, URLs, code identifiers
  and bare numbers are spoken as written — write narration copy, not
  documentation prose.
