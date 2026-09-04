#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6.0,<7"]
# ///
"""Synthesize narration audio, and lay it out on a timeline.

Two engines sit behind one entry point, because neither covers the job
alone: **Kokoro** ships Apache-2.0 weights but no Polish, and **Piper**
has five Polish voices but only one English voice that permits commercial
use. So this script routes by language rather than picking a winner — the
engine is inferred from the voice name's shape, which is unambiguous
(``af_heart`` is Kokoro, ``pl_PL-gosia-medium`` is Piper), so callers pass
a voice exactly as before and never name an engine.

Subcommands, each printing JSON to stdout:

``check``   preflight — is the engine on PATH, is the voice installed,
            what is it licensed for, has the supervisor accepted it.
            Reports availability for BOTH engines, and fails only when the
            *resolved* one is missing.
``pin``     persist the supervisor's voice choice to
            ``~/.config/Dev10x/tts.yaml`` so it is asked once, not per run.
            ``--lang`` pins a per-language voice.
``batch``   segments in, WAVs out.
``track``   timed segments in, one mixed voice-over WAV out.

Four properties are load-bearing:

1. **One piper process per batch.** Model load dominates a short run —
   measured 1.0s for three lines together against ~0.7s each when run
   separately. Piper emits one WAV per *line* of its input, so a batch is
   one N-line file, not N files.
2. **Kokoro pays that load per segment, and says so.** ``kokoro-tts``
   takes one input file and emits ONE audio file; ``--split-output``
   chunks by size, not by line, so there is no way to recover a per-line
   mapping from a batched run. One process per segment is the only
   correct shape — and it is ~5s each, against Piper's ~1s for a whole
   batch. Prefer Piper for long scripts where the timbre allows it.
3. **Output is mapped by position, never by parsing an engine's log.**
   Piper's ``--output-dir-naming timestamp`` writes monotonically-named
   files in line order, so sorting a *freshly created empty* directory
   recovers the input order; the count is asserted against the input
   length, so a surprise in piper's output shape fails loud instead of
   silently pairing the wrong audio with the wrong caption. Kokoro needs
   no inference at all — each segment is told its own output path.
4. **A voice licence is reported, never enforced.** Most good English
   piper voices are CC BY-NC-SA, and whether a given recording is
   commercial use is the supervisor's call, not this script's. An
   unaccepted non-commercial voice yields a ``warning`` in the payload and
   ``licence_accepted: false`` — the caller decides whether to gate on it.
   Kokoro's weights are Apache-2.0, so the English default never warns.

Stdout is parsed by callers, so errors are emitted as ``{"error": ...}``
on **stdout** (not stderr) and the process still exits non-zero — a
consumer parses one channel and never sees empty stdout on failure.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import yaml

# Both engines are CPU-bound: piper runs ~9x realtime, kokoro ~1s of audio
# per second of work. A single subprocess that has not finished in five
# minutes is wedged, not slow. Kokoro's per-segment shape means the budget
# applies per segment, so a long script is not squeezed by it.
_SUBPROCESS_TIMEOUT_SECONDS = 300

PIPER = "piper"
KOKORO = "kokoro"

DEFAULT_VOICES_DIR = Path.home() / ".local" / "share" / "piper" / "voices"

# kokoro-tts resolves these relative to the CURRENT WORKING DIRECTORY and
# offers no environment override, so every invocation must pass --model and
# --voices explicitly — including the informational ones, which load the
# voice pack just to list names.
DEFAULT_KOKORO_DIR = Path.home() / ".local" / "share" / "kokoro"
KOKORO_MODEL_FILE = "kokoro-v1.0.onnx"
KOKORO_VOICES_FILE = "voices-v1.0.bin"
KOKORO_RELEASE_URL = "https://github.com/nazdridoy/kokoro-tts/releases/download/v1.0.0"

# Every Kokoro voice is `<language-letter><gender-letter>_<name>`, and no
# piper voice has that shape — piper's are `<lang>_<REGION>-<name>-<quality>`.
# That is what lets a caller keep passing one --voice and get the right
# engine without ever naming one. Blends ("af_sarah:60,am_adam:40") are
# Kokoro-only and resolve component-by-component.
_KOKORO_VOICE_PATTERN = re.compile(r"^[abefhijpz][fm]_[a-z]+$")

# The 50 voices in voices-v1.0.bin. Kokoro keeps them inside one binary
# blob rather than as per-voice files, so unlike piper there is nothing on
# disk to stat — this list IS the offline existence check, and it is what
# separates "not installed" from "misspelled".
KOKORO_VOICES = frozenset(
    """
    af_alloy af_aoede af_bella af_heart af_jessica af_kore af_nicole af_nova
    af_river af_sarah af_sky am_adam am_echo am_eric am_fenrir am_liam
    am_michael am_onyx am_puck am_santa bf_alice bf_emma bf_isabella bf_lily
    bm_daniel bm_fable bm_george bm_lewis ef_dora em_alex em_santa ff_siwis
    hf_alpha hf_beta hm_omega hm_psi if_sara im_nicola jf_alpha jf_gongitsune
    jf_nezumi jf_tebukuro jm_kumo pf_dora pm_alex pm_santa zf_xiaobei
    zf_xiaoni zf_xiaoxiao zf_xiaoyi
    """.split()
)

# `kokoro-tts --help-languages` accepts exactly these six. A voice whose
# prefix has no entry (Spanish, Hindi, Brazilian Portuguese) is passed
# WITHOUT --lang: the voice already selects the speaker, and naming a
# language the CLI does not know is worse than letting its default stand.
KOKORO_VOICE_LANGUAGES = {
    "a": "en-us",
    "b": "en-gb",
    "f": "fr-fr",
    "i": "it",
    "j": "ja",
    "z": "cmn",
}

# Kokoro-82M's weights are Apache-2.0 and its model card explicitly welcomes
# commercial deployment (verified 2026-09-04), which is the whole reason
# English routes here: the licence question stops being negotiated per voice.
KOKORO_LICENCE = ("Apache-2.0", True)

# Built-in voice per language. English goes to Kokoro for its licence;
# Polish goes to Piper because Kokoro has no Polish weights at all — its
# `pf_`/`pm_` voices read as Polish and are Brazilian Portuguese. Only
# languages verified against an installed voice are listed; an unlisted
# language is an actionable error, not a guess.
LANGUAGE_DEFAULTS = {"en": "af_heart", "pl": "pl_PL-gosia-medium"}

# The language-agnostic default, used when no --lang is requested.
DEFAULT_VOICE = LANGUAGE_DEFAULTS["en"]

# Licence status per voice, keyed by the piper voice name. The model's own
# .onnx.json carries a `license` field that is null for every voice checked,
# so this table is transcribed from the upstream MODEL_CARD files at
# huggingface.co/rhasspy/piper-voices (verified 2026-09-01). A voice absent
# from this table reports an unknown licence — which warns, but never blocks.
VOICE_LICENCES = {
    "en_US-libritts_r-medium": ("CC BY 4.0", True),
    "en_US-libritts-high": ("CC BY 4.0", True),
    "en_US-ryan-medium": ("CC BY-NC-SA 4.0", False),
    "en_US-ryan-high": ("CC BY-NC-SA 4.0", False),
    "en_US-hfc_male-medium": ("CC BY-NC-SA 4.0", False),
    "en_US-hfc_female-medium": ("CC BY-NC-SA 4.0", False),
    "en_US-lessac-medium": ("Blizzard 2013 (research terms)", False),
    "en_US-lessac-high": ("Blizzard 2013 (research terms)", False),
    # Polish (verified 2026-09-04). Unlike English, every Polish voice
    # permits commercial use — so routing Polish to piper costs nothing on
    # the licence axis, and the gate stays quiet on that path too.
    "pl_PL-gosia-medium": ("CC0", True),
    "pl_PL-darkman-medium": ("CC0", True),
    "pl_PL-mc_speech-medium": ("CC0", True),
    "pl_PL-mls_6892-low": ("CC BY 4.0", True),
    "pl_PL-bass-high": ("Apache-2.0", True),
}

# Voice-over is mixed at 48 kHz because that is what screen-capture and
# delivery pipelines expect; piper models render at 22.05 kHz.
TRACK_SAMPLE_RATE = 48000


class SynthesisError(Exception):
    """A failure the caller can act on, carrying guidance in its message."""


def _fail(message: str) -> None:
    """Emit a parseable error on stdout and exit non-zero."""
    json.dump({"error": message}, sys.stdout)
    sys.stdout.write("\n")
    raise SystemExit(1)


# --------------------------------------------------------------------------
# Durable preference — ~/.config/Dev10x/tts.yaml
# --------------------------------------------------------------------------


def config_path() -> Path:
    """Where the supervisor's voice choice lives.

    Under ``~/.config/Dev10x/`` alongside the other durable Dev10x prefs
    (ADR-0018) rather than in a repo's ``.claude/``, so one answer covers a
    repo and every worktree of it and no self-settings consent gate fires.
    """
    home = os.environ.get("DEV10X_CONFIG_HOME")
    base = Path(home).expanduser() if home else Path.home() / ".config" / "Dev10x"
    return base / "tts.yaml"


def load_config() -> dict:
    """Parsed tts.yaml, or an empty config when the file is absent.

    An ABSENT config is normal and resolves to the built-in default. A
    MALFORMED one raises, blocking every subcommand rather than just
    `check`: silently ignoring a config the supervisor wrote would use a
    different voice than the one they pinned — including, potentially, one
    whose licence they never accepted.
    """
    path = config_path()
    if not path.exists():
        return {}
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise SynthesisError(f"{path} is not valid YAML: {error}") from error
    return loaded if isinstance(loaded, dict) else {}


def project_entry(config: dict, cwd: Path) -> dict | None:
    """First ``projects[]`` entry whose match globs cover ``cwd``.

    First match wins, mirroring the friction.yaml resolver so the two files
    behave the same way for the same reader.
    """
    for entry in config.get("projects") or []:
        if not isinstance(entry, dict):
            continue
        for pattern in entry.get("match") or []:
            if fnmatch.fnmatch(str(cwd), pattern) or fnmatch.fnmatch(cwd.name, pattern):
                return entry
    return None


def language_scope(scope: dict, language: str) -> dict:
    """A scope's ``languages[<language>]`` block, or an empty one."""
    found = (scope.get("languages") or {}).get(language)
    return found if isinstance(found, dict) else {}


def licence_is_accepted(voice: str, scopes: list[dict]) -> bool:
    """Whether any scope records acceptance for exactly this voice.

    A licence is accepted for a specific voice, so an acceptance recorded
    against a different one must not carry over. Scanning every scope
    rather than only the one the voice came from is what lets an explicit
    ``--voice`` re-use the consent already pinned for that same voice.
    """
    return any(scope.get("voice") == voice and scope.get("licence_accepted") for scope in scopes)


def resolve_preference(
    explicit_voice: str | None,
    cwd: Path | None = None,
    language: str | None = None,
) -> dict:
    """Resolve the effective voice and whether its licence was accepted.

    Without a language, the order is highest-first: explicit flag,
    ``DEV10X_TTS_VOICE`` (or its ``DEV10X_PIPER_VOICE`` predecessor), a
    matching ``projects[]`` entry, ``defaults``, the built-in.

    **With** a language, the language-agnostic ``voice:`` keys are skipped
    entirely: a supervisor who pinned an English voice globally must not
    have it narrate Polish text. The chain is the requested language's
    ``languages[<lang>]`` block in the project entry, then in ``defaults``,
    then the built-in for that language — and an unknown language is an
    actionable error rather than a silent fall back to English.
    """
    config = load_config()
    entry = project_entry(config, cwd or Path.cwd()) or {}
    defaults = config.get("defaults") or {}
    requested = language or os.environ.get("DEV10X_TTS_LANG")
    environment = os.environ.get("DEV10X_TTS_VOICE") or os.environ.get("DEV10X_PIPER_VOICE")

    candidates: list[tuple[str, str | None]] = [("flag", explicit_voice), ("env", environment)]
    scopes = [entry, defaults]
    if requested:
        project_language = language_scope(entry, requested)
        default_language = language_scope(defaults, requested)
        scopes = [project_language, default_language]
        candidates += [
            (f"project:{requested}", project_language.get("voice")),
            (f"defaults:{requested}", default_language.get("voice")),
            (f"built-in:{requested}", LANGUAGE_DEFAULTS.get(requested)),
        ]
    else:
        candidates += [
            ("project", entry.get("voice")),
            ("defaults", defaults.get("voice")),
            ("built-in", DEFAULT_VOICE),
        ]

    for source, voice in candidates:
        if voice:
            return {
                "voice": voice,
                "source": source,
                "language": requested,
                "licence_accepted": licence_is_accepted(voice, scopes),
            }

    raise SynthesisError(
        f"no voice is configured for language {requested!r}, and there is no built-in"
        f" one — known languages are {', '.join(sorted(LANGUAGE_DEFAULTS))}. Pin one with:\n"
        f"  synthesize.py pin --lang {requested} --voice <voice>"
    )


def write_config(config: dict) -> Path:
    """Persist tts.yaml atomically.

    A standalone uv-script cannot import ``dev10x.domain.file_locks``, so
    the honest equivalent is a temp-file rename: a crash mid-write leaves
    the previous config intact instead of a truncated one.
    """
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            yaml.safe_dump(config, stream, sort_keys=False, default_flow_style=False)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    return path


# --------------------------------------------------------------------------
# Engine selection
# --------------------------------------------------------------------------


def voice_components(voice: str) -> list[str]:
    """The individual voices in a name, splitting a Kokoro blend apart.

    ``"af_sarah:60,am_adam:40"`` is one Kokoro voice made of two, with
    optional per-component weights. Piper has no blend syntax, so a name
    that splits is Kokoro's by construction.
    """
    return [part.split(":", 1)[0].strip() for part in voice.split(",") if part.strip()]


def engine_for(voice: str) -> str:
    """Which engine renders this voice, inferred from the name's shape.

    The two namespaces cannot collide — Kokoro names are
    ``<lang><gender>_<name>`` and piper's always carry a ``-`` — so this
    never has to ask the caller, and no new syntax leaks into the runner
    contract that ``skills/playwright/lib/narration.py`` depends on.
    """
    components = voice_components(voice)
    if components and all(_KOKORO_VOICE_PATTERN.match(part) for part in components):
        return KOKORO
    return PIPER


def resolve_kokoro() -> str:
    """Absolute path to the kokoro-tts binary, or an actionable failure."""
    override = os.environ.get("DEV10X_KOKORO_BIN")
    found = override or shutil.which("kokoro-tts")
    if not found or not Path(found).exists():
        raise SynthesisError(
            "kokoro-tts not found on PATH. Install it with:\n"
            "  uv tool install kokoro-tts\n"
            "(it declares requires-python <3.13, so a 3.13 interpreter needs"
            " `--python 3.12`), or set DEV10X_KOKORO_BIN to the binary."
        )
    return found


def resolve_kokoro_dir(explicit: str | None) -> Path:
    """Directory holding kokoro's model and voice-pack files."""
    if explicit:
        return Path(explicit).expanduser()
    env = os.environ.get("DEV10X_KOKORO_DATA_DIR") or os.environ.get("KOKORO_DATA_DIR")
    return Path(env).expanduser() if env else DEFAULT_KOKORO_DIR


def kokoro_model(kokoro_dir: Path, voice: str) -> tuple[Path, Path]:
    """(model, voice-pack) paths, or an actionable failure naming the fix.

    Both are checked here rather than left to kokoro-tts, whose own failure
    for a missing file is a bare traceback about the current directory —
    which points at the wrong problem, since the paths are ours to supply.
    """
    model = kokoro_dir / KOKORO_MODEL_FILE
    voices = kokoro_dir / KOKORO_VOICES_FILE
    missing = [path for path in (model, voices) if not path.exists()]
    if missing:
        names = ", ".join(path.name for path in missing)
        raise SynthesisError(
            f"kokoro model data missing from {kokoro_dir} ({names}). Download it with:\n"
            f"  mkdir -p {kokoro_dir}\n"
            f"  curl -L -o {model} {KOKORO_RELEASE_URL}/{KOKORO_MODEL_FILE}\n"
            f"  curl -L -o {voices} {KOKORO_RELEASE_URL}/{KOKORO_VOICES_FILE}"
        )
    unknown = [part for part in voice_components(voice) if part not in KOKORO_VOICES]
    if unknown:
        raise SynthesisError(
            f"kokoro voice(s) {', '.join(unknown)} are not in {KOKORO_VOICES_FILE}."
            " List the installed ones with:\n"
            f"  kokoro-tts --help-voices --model {model} --voices {voices}"
        )
    return model, voices


def kokoro_language(voice: str) -> str | None:
    """The ``--lang`` value for a voice, or None when the CLI knows none."""
    return KOKORO_VOICE_LANGUAGES.get(voice_components(voice)[0][0])


# --------------------------------------------------------------------------
# Piper + voice resolution
# --------------------------------------------------------------------------


def normalize_line(text: str) -> str:
    """Collapse a caption into the single line piper's batching requires.

    Piper emits one WAV per input line, so an embedded newline would split
    one caption into two clips and silently shift every later segment onto
    the wrong timestamp.
    """
    collapsed = re.sub(r"\s+", " ", text).strip()
    if not collapsed:
        raise SynthesisError("narration segment is empty after whitespace collapse")
    return collapsed


def resolve_piper() -> str:
    """Absolute path to the piper binary, or an actionable failure."""
    override = os.environ.get("DEV10X_PIPER_BIN")
    found = override or shutil.which("piper")
    if not found or not Path(found).exists():
        raise SynthesisError(
            "piper not found on PATH. Install it with:\n"
            "  uv tool install piper-tts\n"
            "or set DEV10X_PIPER_BIN to the binary."
        )
    return found


def resolve_voices_dir(explicit: str | None) -> Path:
    """Directory holding the .onnx voice models.

    Piper's own ``--data-dir`` defaults to the *current working directory*,
    which is never where voices live, so this is always passed explicitly.
    """
    if explicit:
        return Path(explicit).expanduser()
    env = os.environ.get("DEV10X_PIPER_VOICES")
    return Path(env).expanduser() if env else DEFAULT_VOICES_DIR


def voice_model(voices_dir: Path, voice: str) -> Path:
    """Path to the voice's .onnx, or an actionable failure naming the fix."""
    model = voices_dir / f"{voice}.onnx"
    if not model.exists():
        raise SynthesisError(
            f"voice {voice!r} not installed in {voices_dir}. Download it with:\n"
            f"  ~/.local/share/uv/tools/piper-tts/bin/python -m piper.download_voices"
            f" --download-dir {voices_dir} {voice}"
        )
    return model


def licence_for(voice: str) -> tuple[str | None, bool | None]:
    """(licence name, commercial-use-allowed) for a voice; (None, None) if unknown.

    Kokoro licenses the whole voice pack under one Apache-2.0 grant rather
    than per voice, so its answer comes from membership in ``KOKORO_VOICES``
    — a name outside it is unknown, not permissive.
    """
    if engine_for(voice) == KOKORO:
        components = voice_components(voice)
        if components and all(part in KOKORO_VOICES for part in components):
            return KOKORO_LICENCE
        return (None, None)
    return VOICE_LICENCES.get(voice, (None, None))


def licence_warning(voice: str, accepted: bool) -> str | None:
    """The caveat a supervisor should see before publishing this audio.

    Returns None only when the voice is known to permit commercial use, or
    when the supervisor has already accepted this specific voice.
    """
    if accepted:
        return None
    licence, commercial_ok = licence_for(voice)
    if commercial_ok:
        return None
    if licence is None:
        source = (
            "list it with `kokoro-tts --help-voices` — an unrecognised name is usually a typo"
            if engine_for(voice) == KOKORO
            else "check its MODEL_CARD at huggingface.co/rhasspy/piper-voices"
        )
        return (
            f"voice {voice!r} has no licence on record — {source} before publishing"
            f" this audio. Accept it with:"
            f" synthesize.py pin --voice {voice} --accept-licence"
        )
    return (
        f"voice {voice!r} is {licence} — it does not permit commercial use."
        " QA evidence recorded for client work is commercial use."
        f" Accept the risk with: synthesize.py pin --voice {voice} --accept-licence"
    )


def voice_context(args: argparse.Namespace) -> dict:
    """Everything the subcommands need about the chosen voice and engine."""
    preference = resolve_preference(args.voice, language=getattr(args, "lang", None))
    voice = preference["voice"]
    licence, commercial_ok = licence_for(voice)
    return {
        "voice": voice,
        "voice_source": preference["source"],
        "language": preference["language"],
        "engine": engine_for(voice),
        "voices_dir": resolve_voices_dir(args.voices_dir),
        "kokoro_dir": resolve_kokoro_dir(getattr(args, "kokoro_dir", None)),
        "licence": licence,
        "commercial_use_allowed": commercial_ok,
        "licence_accepted": preference["licence_accepted"],
        "warning": licence_warning(voice, preference["licence_accepted"]),
    }


def wav_duration_ms(path: Path) -> int:
    """Exact duration of a WAV, from its own header.

    Both engines write WAV, so this needs no ffprobe — which keeps this
    script's dependency surface to a single YAML parser.
    """
    with wave.open(str(path), "rb") as handle:
        frames = handle.getnframes()
        rate = handle.getframerate()
    if not rate:
        raise SynthesisError(f"{path} declares a zero sample rate")
    return round(frames * 1000 / rate)


def run_piper(
    *,
    piper: str,
    model: Path,
    voices_dir: Path,
    lines: list[str],
    raw_dir: Path,
    length_scale: float | None,
    sentence_silence: float | None,
    speaker: int | None,
) -> list[Path]:
    """Synthesize every line in ONE process; return WAVs in line order."""
    lines_file = raw_dir.parent / "lines.txt"
    lines_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    command = [
        piper,
        "--model",
        str(model),
        "--data-dir",
        str(voices_dir),
        "--input-file",
        str(lines_file),
        "--output-dir",
        str(raw_dir),
        "--output-dir-naming",
        "timestamp",
    ]
    if length_scale is not None:
        command += ["--length-scale", str(length_scale)]
    if sentence_silence is not None:
        command += ["--sentence-silence", str(sentence_silence)]
    if speaker is not None:
        command += ["--speaker", str(speaker)]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise SynthesisError(f"piper failed ({result.returncode}): {result.stderr.strip()}")

    produced = sorted(raw_dir.glob("*.wav"))

    # Why a count check is sufficient to protect the positional mapping:
    # piper synthesizes lines sequentially and stamps each output with a
    # monotonic timestamp, so sorting a freshly-emptied directory recovers
    # input order. The one way that ordering could break is two clips
    # landing on the SAME timestamp — but identical names are the same
    # file, so a collision costs a file and trips this count check rather
    # than silently reordering. There is no reachable state where the count
    # matches and the order does not.
    if len(produced) != len(lines):
        raise SynthesisError(
            f"piper wrote {len(produced)} clips for {len(lines)} segments — refusing to"
            " guess the pairing. A caption containing a newline is the usual cause."
        )
    return produced


def run_kokoro(
    *,
    kokoro: str,
    model: Path,
    voices: Path,
    voice: str,
    lines: list[str],
    raw_dir: Path,
    length_scale: float | None,
    sentence_silence: float | None,
    speaker: int | None,
) -> list[Path]:
    """Synthesize each line in its OWN process; return WAVs in line order.

    One process per line is not a missed optimisation. ``kokoro-tts`` takes
    one input file and writes one audio file, and its ``--split-output``
    chunks by size rather than by line — so a batched run gives back audio
    with no recoverable mapping to the captions. Naming each output
    explicitly removes the positional inference that piper's path needs.
    """
    if sentence_silence is not None or speaker is not None:
        unsupported = "--sentence-silence" if sentence_silence is not None else "--speaker"
        raise SynthesisError(
            f"{unsupported} has no kokoro equivalent, and silently dropping a pacing"
            f" flag would render audio the caller did not ask for. Use a piper voice"
            f" for it, or drop the flag."
        )

    produced = []
    for index, line in enumerate(lines):
        text_file = raw_dir / f"line-{index:03d}.txt"
        text_file.write_text(line + "\n", encoding="utf-8")
        output = raw_dir / f"clip-{index:03d}.wav"

        # The input file is positional, so every flag is appended after it —
        # a leading --model would be swallowed as that positional argument.
        command = [kokoro, str(text_file), str(output), "--format", "wav"]
        command += ["--model", str(model), "--voices", str(voices)]
        # --voice defaults to an INTERACTIVE picker, which hangs any
        # non-interactive caller on a menu nobody is there to answer.
        command += ["--voice", voice]
        language = kokoro_language(voice)
        if language:
            command += ["--lang", language]
        if length_scale is not None:
            # piper slows down as length-scale rises; kokoro slows down as
            # speed falls. They are reciprocals, so one flag serves both.
            command += ["--speed", str(round(1 / length_scale, 4))]

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            raise SynthesisError(
                f"kokoro-tts failed ({result.returncode}): {result.stderr.strip()}"
            )
        if not output.exists():
            raise SynthesisError(
                f"kokoro-tts exited 0 but wrote no audio for segment {index}"
                f" — expected {output}. Its stdout was: {result.stdout.strip()[:200]}"
            )
        produced.append(output)
    return produced


def synthesize_lines(
    *, context: dict, lines: list[str], raw_dir: Path, args: argparse.Namespace
) -> list[Path]:
    """Render every line with the resolved engine; WAVs in line order."""
    if context["engine"] == KOKORO:
        model, voices = kokoro_model(context["kokoro_dir"], context["voice"])
        return run_kokoro(
            kokoro=resolve_kokoro(),
            model=model,
            voices=voices,
            voice=context["voice"],
            lines=lines,
            raw_dir=raw_dir,
            length_scale=args.length_scale,
            sentence_silence=args.sentence_silence,
            speaker=args.speaker,
        )
    return run_piper(
        piper=resolve_piper(),
        model=voice_model(context["voices_dir"], context["voice"]),
        voices_dir=context["voices_dir"],
        lines=lines,
        raw_dir=raw_dir,
        length_scale=args.length_scale,
        sentence_silence=args.sentence_silence,
        speaker=args.speaker,
    )


# --------------------------------------------------------------------------
# Subcommands
# --------------------------------------------------------------------------


def engine_availability(context: dict) -> dict:
    """Per-engine readiness, each entry naming its own fix when unready.

    Both engines are probed even though only one renders this run: a
    supervisor deciding whether Polish is reachable at all should not have
    to re-run `check` with a different voice to find out.
    """
    report = {}
    for engine, probe in (
        (PIPER, lambda: {"bin": resolve_piper(), "voices_dir": str(context["voices_dir"])}),
        (KOKORO, lambda: {"bin": resolve_kokoro(), "data_dir": str(context["kokoro_dir"])}),
    ):
        try:
            report[engine] = {"available": True, **probe()}
        except SynthesisError as error:
            report[engine] = {"available": False, "fix": str(error)}
    return report


def cmd_check(args: argparse.Namespace) -> dict:
    context = voice_context(args)
    engines = engine_availability(context)

    # The resolved engine is the one that has to work, so its absence is the
    # command's failure — the OTHER engine being absent is information, not
    # an error, and reporting it that way is what makes `check` usable for
    # "can I narrate Polish here?" as well as "will this run succeed?".
    resolved = engines[context["engine"]]
    if not resolved["available"]:
        raise SynthesisError(resolved["fix"])

    if context["engine"] == KOKORO:
        model, voices = kokoro_model(context["kokoro_dir"], context["voice"])
        model_paths = {"model": str(model), "voice_pack": str(voices)}
    else:
        model_paths = {"model": str(voice_model(context["voices_dir"], context["voice"]))}

    return {
        "engine": context["engine"],
        "engines": engines,
        # Retained for callers written against the piper-only wrapper.
        "piper": engines[PIPER].get("bin"),
        "voice": context["voice"],
        "voice_source": context["voice_source"],
        "language": context["language"],
        "voices_dir": str(context["voices_dir"]),
        **model_paths,
        "licence": context["licence"],
        "commercial_use_allowed": context["commercial_use_allowed"],
        "licence_accepted": context["licence_accepted"],
        "warning": context["warning"],
        "config": str(config_path()),
        "ffmpeg": shutil.which("ffmpeg"),
    }


def cmd_pin(args: argparse.Namespace) -> dict:
    """Persist the supervisor's voice choice so it is asked once."""
    config = load_config()
    record = {"voice": args.voice}
    if args.accept_licence:
        record["licence_accepted"] = True

    if args.match:
        projects = [
            entry
            for entry in (config.get("projects") or [])
            if isinstance(entry, dict) and list(entry.get("match") or []) != list(args.match)
        ]
        target = {"match": list(args.match)}
        projects.append(target)
        config["projects"] = projects
        scope = "project"
    else:
        target = config["defaults"] = dict(config.get("defaults") or {})
        scope = "defaults"

    if args.lang:
        # A per-language pin nests under `languages:` rather than replacing
        # the scope's own `voice:`, so pinning Polish never disturbs the
        # English default a supervisor already accepted.
        languages = dict(target.get("languages") or {})
        languages[args.lang] = {**(languages.get(args.lang) or {}), **record}
        target["languages"] = languages
        scope = f"{scope}:{args.lang}"
    else:
        target.update(record)

    path = write_config(config)
    licence, commercial_ok = licence_for(args.voice)
    return {
        "pinned": True,
        "scope": scope,
        "match": list(args.match) if args.match else None,
        "language": args.lang,
        "voice": args.voice,
        "engine": engine_for(args.voice),
        "licence": licence,
        "commercial_use_allowed": commercial_ok,
        "licence_accepted": bool(args.accept_licence),
        "config": str(path),
    }


def cmd_batch(args: argparse.Namespace) -> dict:
    payload = _read_payload(args.segments_file)
    segments = payload.get("segments") if isinstance(payload, dict) else payload
    if not isinstance(segments, list) or not segments:
        raise SynthesisError('no segments supplied — expected {"segments": [...]}')

    context = voice_context(args)

    out_dir = Path(args.out_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    # A fresh, guaranteed-empty directory is what makes piper's
    # position-based mapping sound: a stale WAV left over from an earlier
    # run would shift every segment onto the wrong caption.
    #
    # rmtree first (no exists() check — that is a TOCTOU window), then mkdir
    # WITHOUT exist_ok: if the directory somehow survives the removal, the
    # mkdir must fail loudly rather than let stale clips through.
    raw_dir = out_dir / ".tts-raw"
    shutil.rmtree(raw_dir, ignore_errors=True)
    raw_dir.mkdir(parents=True)

    missing_text = [index for index, segment in enumerate(segments) if not segment.get("text")]
    if missing_text:
        raise SynthesisError(
            f"segment(s) at index {missing_text} have no 'text' field — each segment"
            ' must be {"id": ..., "text": ...}'
        )
    lines = [normalize_line(str(segment["text"])) for segment in segments]
    produced = synthesize_lines(context=context, lines=lines, raw_dir=raw_dir, args=args)

    rendered = []
    for index, (segment, source, line) in enumerate(zip(segments, produced, lines)):
        destination = out_dir / f"seg-{index:03d}.wav"
        destination.unlink(missing_ok=True)
        source.rename(destination)
        rendered.append(
            {
                "index": index,
                "id": segment.get("id", f"seg-{index:03d}"),
                "text": line,
                "wav": str(destination),
                "duration_ms": wav_duration_ms(destination),
            }
        )
    shutil.rmtree(raw_dir, ignore_errors=True)

    return {
        "voice": context["voice"],
        "engine": context["engine"],
        "language": context["language"],
        "licence": context["licence"],
        "commercial_use_allowed": context["commercial_use_allowed"],
        "licence_accepted": context["licence_accepted"],
        "warning": context["warning"],
        "out_dir": str(out_dir),
        "segments": rendered,
    }


def build_track_command(segments: list[dict], output: Path) -> list[str]:
    """ffmpeg command placing each clip at its own offset on one track.

    Each input is delayed to its cue and the delayed streams are mixed.
    ``normalize=0`` keeps amix from dividing every clip's volume by the
    input count — the clips do not overlap, so mixing must not attenuate
    them.
    """
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error"]
    for segment in segments:
        command += ["-i", str(segment["wav"])]

    filters = []
    for index, segment in enumerate(segments):
        delay = max(0, int(segment.get("offset_ms", 0)))
        filters.append(f"[{index}:a]adelay={delay}|{delay}[d{index}]")
    labels = "".join(f"[d{index}]" for index in range(len(segments)))
    filters.append(f"{labels}amix=inputs={len(segments)}:duration=longest:normalize=0[vo]")

    command += [
        "-filter_complex",
        ";".join(filters),
        "-map",
        "[vo]",
        "-ar",
        str(TRACK_SAMPLE_RATE),
        "-ac",
        "1",
        str(output),
        "-y",
    ]
    return command


def cmd_track(args: argparse.Namespace) -> dict:
    payload = _read_payload(args.segments_file)
    segments = payload.get("segments") if isinstance(payload, dict) else payload
    if not isinstance(segments, list) or not segments:
        raise SynthesisError('no segments supplied — expected {"segments": [...]}')

    missing = [segment for segment in segments if not Path(str(segment.get("wav", ""))).exists()]
    if missing:
        raise SynthesisError(
            f"{len(missing)} segment(s) reference a WAV that does not exist — run"
            " `synthesize.py batch` before `track`."
        )
    if not shutil.which("ffmpeg"):
        raise SynthesisError("ffmpeg not found on PATH — required to lay out the voice track.")

    output = Path(args.out).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        build_track_command(segments, output),
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise SynthesisError(f"ffmpeg failed ({result.returncode}): {result.stderr.strip()}")

    return {
        "track": str(output),
        "duration_ms": wav_duration_ms(output),
        "segments": len(segments),
        "sample_rate": TRACK_SAMPLE_RATE,
    }


def _read_payload(path: str | None) -> dict | list:
    raw = Path(path).expanduser().read_text(encoding="utf-8") if path else sys.stdin.read()
    try:
        return json.loads(raw)
    except json.JSONDecodeError as error:
        raise SynthesisError(f"segments are not valid JSON: {error}") from error


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Narration synthesis for Dev10x.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_voice_options(target: argparse.ArgumentParser) -> None:
        target.add_argument(
            "--voice",
            default=None,
            help=f"voice name; its shape selects the engine (default {DEFAULT_VOICE})",
        )
        target.add_argument(
            "--lang",
            default=None,
            help=f"language to narrate; picks a per-language voice "
            f"({', '.join(sorted(LANGUAGE_DEFAULTS))})",
        )
        target.add_argument("--voices-dir", default=None, help="directory holding piper .onnx")
        target.add_argument(
            "--kokoro-dir", default=None, help="directory holding kokoro model data"
        )

    check = subparsers.add_parser("check", help="verify the engines, the voice, and its licence")
    add_voice_options(check)
    check.set_defaults(handler=cmd_check)

    pin = subparsers.add_parser("pin", help="persist the supervisor's voice choice")
    pin.add_argument("--voice", required=True, help="voice to remember")
    pin.add_argument(
        "--lang",
        default=None,
        help="pin this voice for one language only, leaving the others alone",
    )
    pin.add_argument(
        "--accept-licence",
        action="store_true",
        help="record that the supervisor accepted this voice's terms",
    )
    pin.add_argument(
        "--match",
        action="append",
        default=None,
        help="glob scoping the pin to a project; repeatable. Omit for a global default.",
    )
    pin.set_defaults(handler=cmd_pin)

    batch = subparsers.add_parser("batch", help="synthesize every segment in one process")
    add_voice_options(batch)
    batch.add_argument("--segments-file", default=None, help="JSON file; omit to read stdin")
    batch.add_argument("--out-dir", required=True, help="directory to write seg-NNN.wav into")
    batch.add_argument(
        "--length-scale",
        type=float,
        default=None,
        help="<1 faster, >1 slower; kokoro receives its reciprocal as --speed",
    )
    batch.add_argument(
        "--sentence-silence", type=float, default=None, help="seconds between; piper only"
    )
    batch.add_argument(
        "--speaker", type=int, default=None, help="speaker id, multi-speaker piper voices only"
    )
    batch.set_defaults(handler=cmd_batch)

    track = subparsers.add_parser("track", help="lay rendered segments onto one timeline")
    track.add_argument("--segments-file", default=None, help="JSON file; omit to read stdin")
    track.add_argument("--out", required=True, help="output WAV path")
    track.set_defaults(handler=cmd_track)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = args.handler(args)
    except SynthesisError as error:
        _fail(str(error))
    except subprocess.TimeoutExpired:
        _fail(f"synthesis/ffmpeg exceeded {_SUBPROCESS_TIMEOUT_SECONDS}s — treating as wedged")
    except Exception as error:  # noqa: BLE001 — the stdout contract outranks the traceback
        # Callers parse stdout only. An escaping traceback would leave them
        # with empty stdout and a generic "wrapper failed", discarding the
        # one piece of information that makes the failure actionable.
        _fail(f"unexpected {type(error).__name__}: {error}")
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
