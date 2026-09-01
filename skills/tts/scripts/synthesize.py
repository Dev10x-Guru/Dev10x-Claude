#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6.0,<7"]
# ///
"""Synthesize narration audio with Piper, and lay it out on a timeline.

Subcommands, each printing JSON to stdout:

``check``   preflight — is ``piper`` on PATH, is the voice installed, what
            is the voice licensed for, has the supervisor accepted it.
``pin``     persist the supervisor's voice choice to
            ``~/.config/Dev10x/tts.yaml`` so it is asked once, not per run.
``batch``   segments in, WAVs out. Every segment is synthesized by a
            SINGLE piper process (see below).
``track``   timed segments in, one mixed voice-over WAV out.

Three properties are load-bearing:

1. **One piper process per batch.** Model load dominates a short run —
   measured 1.0s for three lines together against ~0.7s each when run
   separately. Piper emits one WAV per *line* of its input, so a batch is
   one N-line file, not N files.
2. **Output is mapped by position, never by parsing piper's log.**
   ``--output-dir-naming timestamp`` writes monotonically-named files in
   line order, so sorting a *freshly created empty* directory recovers the
   input order. The count is asserted against the input length, so a
   surprise in piper's output shape fails loud instead of silently pairing
   the wrong audio with the wrong caption.
3. **A voice licence is reported, never enforced.** Most good English
   piper voices are CC BY-NC-SA, and whether a given recording is
   commercial use is the supervisor's call, not this script's. An
   unaccepted non-commercial voice yields a ``warning`` in the payload and
   ``licence_accepted: false`` — the caller decides whether to gate on it.

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

# Piper is CPU-bound and roughly 9x realtime; a minute of narration is a
# few seconds of work. A batch that has not finished in five minutes is
# wedged, not slow.
_SUBPROCESS_TIMEOUT_SECONDS = 300

DEFAULT_VOICES_DIR = Path.home() / ".local" / "share" / "piper" / "voices"

# The built-in default is chosen for its LICENCE, not its timbre: it is the
# only English voice in the table below that permits commercial use. A
# supervisor who prefers a different one pins it (see `pin`), which is also
# where they accept that voice's terms.
DEFAULT_VOICE = "en_US-libritts_r-medium"

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


def resolve_preference(explicit_voice: str | None, cwd: Path | None = None) -> dict:
    """Resolve the effective voice and whether its licence was accepted.

    Order, highest first: explicit flag, ``DEV10X_PIPER_VOICE``, a matching
    ``projects[]`` entry, ``defaults``, the built-in.
    """
    config = load_config()
    here = cwd or Path.cwd()
    entry = project_entry(config, here) or {}
    defaults = config.get("defaults") or {}

    for source, voice in (
        ("flag", explicit_voice),
        ("env", os.environ.get("DEV10X_PIPER_VOICE")),
        ("project", entry.get("voice")),
        ("defaults", defaults.get("voice")),
    ):
        if voice:
            scope = entry if source == "project" else defaults
            return {
                "voice": voice,
                "source": source,
                # A licence is accepted for a specific voice. An acceptance
                # recorded against a different voice must not carry over.
                "licence_accepted": bool(scope.get("licence_accepted"))
                and scope.get("voice") == voice,
            }
    return {"voice": DEFAULT_VOICE, "source": "built-in", "licence_accepted": False}


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
    """(licence name, commercial-use-allowed) for a voice; (None, None) if unknown."""
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
        return (
            f"voice {voice!r} has no licence on record — check its MODEL_CARD at"
            " huggingface.co/rhasspy/piper-voices before publishing this audio."
            f" Accept it with: synthesize.py pin --voice {voice} --accept-licence"
        )
    return (
        f"voice {voice!r} is {licence} — it does not permit commercial use."
        " QA evidence recorded for client work is commercial use."
        f" Accept the risk with: synthesize.py pin --voice {voice} --accept-licence"
    )


def voice_context(explicit_voice: str | None, voices_dir_arg: str | None) -> dict:
    """Everything the subcommands need about the chosen voice."""
    preference = resolve_preference(explicit_voice)
    voice = preference["voice"]
    licence, commercial_ok = licence_for(voice)
    return {
        "voice": voice,
        "voice_source": preference["source"],
        "voices_dir": resolve_voices_dir(voices_dir_arg),
        "licence": licence,
        "commercial_use_allowed": commercial_ok,
        "licence_accepted": preference["licence_accepted"],
        "warning": licence_warning(voice, preference["licence_accepted"]),
    }


def wav_duration_ms(path: Path) -> int:
    """Exact duration of a WAV, from its own header.

    Piper writes WAV, so this needs no ffprobe — which keeps this script's
    dependency surface to a single YAML parser.
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


# --------------------------------------------------------------------------
# Subcommands
# --------------------------------------------------------------------------


def cmd_check(args: argparse.Namespace) -> dict:
    context = voice_context(args.voice, args.voices_dir)
    piper = resolve_piper()
    model = voice_model(context["voices_dir"], context["voice"])
    return {
        "piper": piper,
        "voice": context["voice"],
        "voice_source": context["voice_source"],
        "voices_dir": str(context["voices_dir"]),
        "model": str(model),
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
        projects.append({"match": list(args.match), **record})
        config["projects"] = projects
        scope = "project"
    else:
        config["defaults"] = {**(config.get("defaults") or {}), **record}
        scope = "defaults"

    path = write_config(config)
    licence, commercial_ok = licence_for(args.voice)
    return {
        "pinned": True,
        "scope": scope,
        "match": list(args.match) if args.match else None,
        "voice": args.voice,
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

    context = voice_context(args.voice, args.voices_dir)
    piper = resolve_piper()
    model = voice_model(context["voices_dir"], context["voice"])

    out_dir = Path(args.out_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    # A fresh, guaranteed-empty directory is what makes position-based
    # mapping sound: a stale WAV left over from an earlier run would shift
    # every segment onto the wrong caption.
    #
    # rmtree first (no exists() check — that is a TOCTOU window), then mkdir
    # WITHOUT exist_ok: if the directory somehow survives the removal, the
    # mkdir must fail loudly rather than let stale clips through.
    raw_dir = out_dir / ".piper-raw"
    shutil.rmtree(raw_dir, ignore_errors=True)
    raw_dir.mkdir(parents=True)

    missing_text = [index for index, segment in enumerate(segments) if not segment.get("text")]
    if missing_text:
        raise SynthesisError(
            f"segment(s) at index {missing_text} have no 'text' field — each segment"
            ' must be {"id": ..., "text": ...}'
        )
    lines = [normalize_line(str(segment["text"])) for segment in segments]
    produced = run_piper(
        piper=piper,
        model=model,
        voices_dir=context["voices_dir"],
        lines=lines,
        raw_dir=raw_dir,
        length_scale=args.length_scale,
        sentence_silence=args.sentence_silence,
        speaker=args.speaker,
    )

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
    parser = argparse.ArgumentParser(description="Piper narration synthesis for Dev10x.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_voice_options(target: argparse.ArgumentParser) -> None:
        target.add_argument("--voice", default=None, help=f"piper voice (default {DEFAULT_VOICE})")
        target.add_argument("--voices-dir", default=None, help="directory holding .onnx models")

    check = subparsers.add_parser("check", help="verify piper, the voice, and its licence")
    add_voice_options(check)
    check.set_defaults(handler=cmd_check)

    pin = subparsers.add_parser("pin", help="persist the supervisor's voice choice")
    pin.add_argument("--voice", required=True, help="voice to remember")
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
    batch.add_argument("--length-scale", type=float, default=None, help="<1 faster, >1 slower")
    batch.add_argument("--sentence-silence", type=float, default=None, help="seconds between")
    batch.add_argument("--speaker", type=int, default=None, help="speaker id, multi-speaker only")
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
        _fail(f"piper/ffmpeg exceeded {_SUBPROCESS_TIMEOUT_SECONDS}s — treating as wedged")
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
