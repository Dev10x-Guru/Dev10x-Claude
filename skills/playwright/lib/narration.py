"""Spoken narration for Playwright recordings, locked to the captions.

``Dev10x:qa-self`` already writes narration copy — ``Annotator.say()``
captions describe the user benefit ("One click assigns them, no Save
needed"), which is exactly what a voice-over would say. This module turns
that copy into audio and records WHEN each line was spoken, so the two
tracks cannot drift apart.

Three decisions are load-bearing:

1. **Lines are pre-rendered, not synthesized mid-recording.** The script
   declares every narration line up front and they are all synthesized
   before the run starts. Synthesizing inside ``say()`` would freeze the
   frame for the model load at every caption — which is the whole cost on
   a piper voice, where one process renders the entire script.
2. **Caption dwell comes from the audio, not the character count.**
   ``caption_dwell_ms`` estimates reading time; once a line is spoken, the
   only correct dwell is how long the speech actually takes. Estimating
   both independently is how a caption and its voice drift apart.
3. **The video-start anchor is explicit, and its absence is recorded.**
   Playwright starts recording when the *context* is created, not when the
   annotator installs. If nothing calls ``mark_video_start()`` the offsets
   are relative to install instead, and the manifest says so — a visibly
   approximate anchor beats a silently wrong one.

A line that was never pre-rendered still works: it falls back to the
character-derived dwell and is recorded in the manifest with no audio, so
the gap is visible rather than silent.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

# Trailing hold after the speech ends. Without it the caption vanishes on
# the last syllable, which reads as a cut rather than a beat.
CAPTION_TAIL_MS = 700

# Synthesis is ~9x realtime, so a few minutes of narration is a few seconds
# of work. Anything past this is wedged, not slow.
SYNTHESIS_TIMEOUT_SECONDS = 300


def normalize_line(text: str) -> str:
    """Collapse a caption to one line.

    Must match ``skills/tts/scripts/synthesize.py::normalize_line`` — this
    is the lookup key on both sides of the subprocess boundary, so the two
    have to agree or every pre-rendered clip misses.
    """
    return re.sub(r"\s+", " ", text).strip()


def default_runner(payload: dict, out_dir: Path, voice: str | None) -> dict:
    """Invoke the bundled Dev10x:tts wrapper and return its JSON payload."""
    script = os.environ.get("DEV10X_TTS_SCRIPT")
    if not script:
        raise NarrationError(
            "DEV10X_TTS_SCRIPT is not set — run the capture through"
            " skills/playwright/scripts/run-playwright.sh, which exports it."
        )
    command = [script, "batch", "--out-dir", str(out_dir)]
    if voice:
        command += ["--voice", voice]
    try:
        result = subprocess.run(
            command,
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=SYNTHESIS_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        # Surface as NarrationError like every other failure here, so the
        # caller has one exception type to decide on rather than two.
        raise NarrationError(
            f"synthesis exceeded {SYNTHESIS_TIMEOUT_SECONDS}s — treating as wedged"
        ) from None
    # The wrapper prints {"error": ...} on stdout and exits non-zero, so the
    # message is in stdout even on failure.
    try:
        parsed = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        raise NarrationError(
            f"tts wrapper returned unparseable output ({result.returncode}):"
            f" {result.stdout[:400]}{result.stderr[:400]}"
        ) from None
    if result.returncode != 0 or "error" in parsed:
        raise NarrationError(parsed.get("error", f"tts wrapper failed ({result.returncode})"))
    return parsed


class NarrationError(Exception):
    """Narration could not be produced; the caller decides whether to abort."""


class Narration:
    """Pre-rendered voice-over bound to one recording."""

    def __init__(
        self,
        out_dir: str | Path,
        *,
        script: Iterable[str] = (),
        voice: str | None = None,
        tail_ms: int = CAPTION_TAIL_MS,
        runner: Callable[[dict, Path, str | None], dict] = default_runner,
    ) -> None:
        self.out_dir = Path(out_dir)
        self.script = [normalize_line(line) for line in script]
        self.voice = voice
        self.tail_ms = tail_ms
        self._runner = runner
        self._clips: dict[str, dict[str, Any]] = {}
        self._spoken: list[dict[str, Any]] = []
        self._t0: float | None = None
        self._anchor = "install"
        self.warning: str | None = None

    # -- timeline -------------------------------------------------------

    def mark_video_start(self) -> None:
        """Anchor offsets to now. Call right after the recorded context opens."""
        self._t0 = time.monotonic()
        self._anchor = "video-start"

    def _ensure_anchor(self) -> None:
        if self._t0 is None:
            self._t0 = time.monotonic()

    def offset_ms(self) -> int:
        """Milliseconds since the anchor."""
        self._ensure_anchor()
        return max(0, round((time.monotonic() - self._t0) * 1000))

    # -- synthesis ------------------------------------------------------

    def prerender(self) -> None:
        """Synthesize every declared line through the Dev10x:tts wrapper.

        Idempotent (GH-1205): lines already synthesized are skipped, so
        calling this and then ``Annotator.install()`` — which the corrected
        ordering requires — does not render the script twice. The guard
        lives here rather than in a runner because ``runner`` is a
        caller-supplied hook and the default one has no existence check;
        resting a library invariant on a replaceable hook makes the stock
        path the unguarded one. Under Kokoro the cost is a model load per
        line, so a second pass is ~100s of dead setup, not untidiness.
        """
        if not self.script:
            return
        # dict.fromkeys keeps first-seen order while dropping duplicates —
        # a line repeated across steps is one clip, reused.
        unique = [text for text in dict.fromkeys(self.script) if text not in self._clips]
        if not unique:
            return
        payload = {
            "segments": [
                {"id": f"line-{index:03d}", "text": text} for index, text in enumerate(unique)
            ]
        }
        self.out_dir.mkdir(parents=True, exist_ok=True)
        rendered = self._runner(payload, self.out_dir, self.voice)
        self.warning = rendered.get("warning")
        self.voice = rendered.get("voice", self.voice)
        for segment in rendered.get("segments", []):
            self._clips[normalize_line(segment["text"])] = segment

    def clip_for(self, text: str) -> dict[str, Any] | None:
        return self._clips.get(normalize_line(text))

    def duration_ms(self, text: str) -> int | None:
        """Spoken length of a pre-rendered line, or None if it was not declared."""
        clip = self.clip_for(text)
        return clip["duration_ms"] if clip else None

    def dwell_ms(self, text: str) -> int | None:
        """Caption dwell for a spoken line: its audio plus a trailing hold."""
        duration = self.duration_ms(text)
        return None if duration is None else duration + self.tail_ms

    # -- recording ------------------------------------------------------

    def record(self, text: str, dwell_ms: int) -> dict[str, Any]:
        """Note that ``text`` was shown now, and return its manifest entry."""
        clip = self.clip_for(text)
        entry = {
            "index": len(self._spoken),
            "text": normalize_line(text),
            "offset_ms": self.offset_ms(),
            "dwell_ms": dwell_ms,
            "wav": clip["wav"] if clip else None,
            "duration_ms": clip["duration_ms"] if clip else None,
        }
        self._spoken.append(entry)
        return entry

    @property
    def spoken(self) -> list[dict[str, Any]]:
        return list(self._spoken)

    @property
    def unrendered(self) -> list[str]:
        """Lines that played without audio — undeclared in ``script``."""
        return [entry["text"] for entry in self._spoken if entry["wav"] is None]

    # -- output ---------------------------------------------------------

    def manifest(self) -> dict[str, Any]:
        return {
            "voice": self.voice,
            "anchor": self._anchor,
            "tail_ms": self.tail_ms,
            "warning": self.warning,
            "unrendered": self.unrendered,
            # Only spoken lines that produced audio can be laid on the
            # timeline; `segments` is what `synthesize.py track` consumes.
            "segments": [entry for entry in self._spoken if entry["wav"]],
            "all_captions": self._spoken,
        }

    def write_manifest(self, path: str | Path | None = None) -> Path:
        """Persist the timed transcript beside the audio."""
        target = Path(path) if path else self.out_dir / "narration.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.manifest(), indent=2), encoding="utf-8")
        return target
