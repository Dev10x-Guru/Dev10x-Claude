# Voice licences

Two engines, two licensing shapes. Kokoro licenses its whole voice pack
under one grant; Piper licenses per voice, from the dataset each was
trained on.

## Kokoro — one Apache-2.0 grant for all 50 voices

Kokoro-82M's model card releases the **weights** under Apache-2.0 and says
so explicitly about deployment: *"This is an Apache-licensed model, and
Kokoro has been deployed in numerous projects and commercial APIs. We
welcome the deployment of the model in real use cases."* (verified
2026-09-04 at `huggingface.co/hexgrad/Kokoro-82M`).

The two files the wrapper installs — `kokoro-v1.0.onnx` and
`voices-v1.0.bin` — are a repackaging of those weights, distributed as
release assets by [`nazdridoy/kokoro-tts`](https://github.com/nazdridoy/kokoro-tts)
(the CLI itself is MIT, which is a separate grant covering the code, not
the voices). The voice pack carries no licence file of its own; its terms
are Kokoro-82M's, and that is what `licence_for()` reports.

Because it is one grant, there is no per-voice table to consult — but a
name outside the pack is reported as **unknown**, not permissive, so a
typo cannot inherit the Apache grant. `af_heart` is the wrapper's English
default for exactly this reason.

## Piper — per voice, from the `MODEL_CARD`

A Piper voice ships two files: `<voice>.onnx` and `<voice>.onnx.json`. The
JSON carries a `license` key that is **`null` for every voice checked** —
so the model as installed tells you nothing about what you may do with its
output. The authority is the `MODEL_CARD` beside the voice in the upstream
repo.

### Verified table

Transcribed from
`huggingface.co/rhasspy/piper-voices/raw/main/<lang>/<locale>/<voice>/<quality>/MODEL_CARD`
— English 2026-09-01, Polish 2026-09-04.

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
| `pl_PL-gosia-medium` | gosia | CC0 | ✅ |
| `pl_PL-darkman-medium` | OHF-Voice voice-datasets | CC0 | ✅ |
| `pl_PL-mc_speech-medium` | the-mc-speech-dataset | CC0 | ✅ |
| `pl_PL-mls_6892-low` | MLS Polish (openslr 94) | CC BY 4.0 | ✅ with attribution |
| `pl_PL-bass-high` | ~10k segments of Polish speech | Apache-2.0 | ✅ |

`en_US-libritts_r-medium` was the built-in default **because of this
table** — it is the only English Piper voice here that permits commercial
use. English now routes to Kokoro instead, so it is the fallback rather
than the default. It is multi-speaker, so `--speaker` selects a voice
within it; single-speaker voices ignore the flag.

Polish is the inverse situation: every `pl_PL` voice permits commercial
use, so routing Polish to Piper costs nothing on the licence axis.
`pl_PL-gosia-medium` is the built-in Polish default.

## Why this matters for QA evidence

A walkthrough recording attached to a client ticket is commercial use. A
CC BY-NC-SA voice narrating it is a licence breach, and nothing in the
toolchain would tell you — the audio renders identically either way.

The wrapper therefore reports the licence on every `check` and `batch`,
and refuses nothing. Whether a given recording is commercial use is a
judgement about the work, not about the audio, so it belongs to the
supervisor. `pin --accept-licence` is how that judgement is recorded.

## Verifying a Piper voice not in the table

```bash
curl -s https://huggingface.co/rhasspy/piper-voices/raw/main/\
<lang>/<locale>/<voice>/<quality>/MODEL_CARD
```

Read the **Licence** line and the dataset's own licence URL — a few cards
point at an external licence page rather than naming an SPDX identifier
(`lessac` is one). Then add the row to `VOICE_LICENCES` in
`scripts/synthesize.py` so the next caller does not repeat the lookup.

A voice absent from that table reports `licence: null` and warns that no
licence is on record — it is not assumed permissive.

## Verifying a Kokoro voice name

There is no per-voice card to read; the question is only whether the name
is in the installed pack.

```bash
kokoro-tts --help-voices \
  --model ~/.local/share/kokoro/kokoro-v1.0.onnx \
  --voices ~/.local/share/kokoro/voices-v1.0.bin
```

Both flags are required even here: `kokoro-tts` resolves those two files
against the current working directory and loads the pack just to list
names. If a future pack adds voices, extend `KOKORO_VOICES` in
`scripts/synthesize.py` — that frozenset is the offline existence check.

The first letter is the language (`a`/`b` English, `e` Spanish, `f`
French, `h` Hindi, `i` Italian, `j` Japanese, `p` **Brazilian
Portuguese**, `z` Mandarin) and the second is the gender. `pf_`/`pm_` read
as Polish and are not — that is a trap worth restating, because there is
no Polish voice to reach for and no `--lang pl` to pass. A Kokoro language
needs trained weights *and* `misaki` G2P support; Polish has neither.

## Attribution

CC BY 4.0 requires attribution. When publishing narrated evidence outside
the team, credit the voice, e.g.:

> Narration synthesized with Piper using the `pl_PL-mls_6892-low` voice
> (MLS Polish, CC BY 4.0).

Apache-2.0 and CC0 voices — which includes every built-in default — carry
no attribution obligation.
