# Piper voice licences

A Piper voice ships two files: `<voice>.onnx` and `<voice>.onnx.json`. The
JSON carries a `license` key that is **`null` for every voice checked** —
so the model as installed tells you nothing about what you may do with its
output. The authority is the `MODEL_CARD` beside the voice in the upstream
repo.

## Verified table

Transcribed 2026-09-01 from
`huggingface.co/rhasspy/piper-voices/raw/main/en/en_US/<voice>/<quality>/MODEL_CARD`.

| Voice | Dataset | Licence | Commercial use |
|---|---|---|---|
| `en_US-libritts_r-medium` | LibriTTS-R (openslr 141) | CC BY 4.0 | ✅ with attribution |
| `en_US-libritts-high` | LibriTTS | CC BY 4.0 | ✅ with attribution |
| `en_US-ryan-medium` | RyanSpeech | CC BY-NC-SA 4.0 | ❌ |
| `en_US-ryan-high` | RyanSpeech | CC BY-NC-SA 4.0 | ❌ |
| `en_US-hfc_male-medium` | Hi-Fi Captain | CC BY-NC-SA 4.0 | ❌ |
| `en_US-hfc_female-medium` | Hi-Fi Captain | CC BY-NC-SA 4.0 | ❌ |
| `en_US-lessac-medium` | Blizzard Challenge 2013 | Blizzard research terms | ❌ |
| `en_US-lessac-high` | Blizzard Challenge 2013 | Blizzard research terms | ❌ |

`en_US-libritts_r-medium` is the wrapper's built-in default **because of
this table**, not because it sounds best. It is multi-speaker, so
`--speaker` selects a voice within it; single-speaker voices ignore the
flag.

## Why this matters for QA evidence

A walkthrough recording attached to a client ticket is commercial use. A
CC BY-NC-SA voice narrating it is a licence breach, and nothing in the
toolchain would tell you — the audio renders identically either way.

The wrapper therefore reports the licence on every `check` and `batch`,
and refuses nothing. Whether a given recording is commercial use is a
judgement about the work, not about the audio, so it belongs to the
supervisor. `pin --accept-licence` is how that judgement is recorded.

## Verifying a voice not in the table

```bash
curl -s https://huggingface.co/rhasspy/piper-voices/raw/main/\
en/en_US/<voice>/<quality>/MODEL_CARD
```

Read the **Licence** line and the dataset's own licence URL — a few cards
point at an external licence page rather than naming an SPDX identifier
(`lessac` is one). Then add the row to `VOICE_LICENCES` in
`scripts/synthesize.py` so the next caller does not repeat the lookup.

A voice absent from that table reports `licence: null` and warns that no
licence is on record — it is not assumed permissive.

## Attribution

CC BY 4.0 requires attribution. When publishing narrated evidence outside
the team, credit the voice, e.g.:

> Narration synthesized with Piper using the `en_US-libritts_r-medium`
> voice (LibriTTS-R, CC BY 4.0).
