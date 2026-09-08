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

import hashlib
import inspect
import json
import os
import re
import shutil
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

# Language used when a caller names none (GH-1221). Forwarding ``--lang``
# was only half the fix: both documented call sites construct ``Narration``
# without one, so an unresolved language left the wrapper resolving the
# language-agnostic ``voice:`` key and skipping the ``languages:`` pin on
# the one path whose output reaches a client. Defaulting here makes
# ``--lang`` mean the same thing on every path instead of two things
# depending on the caller.
DEFAULT_LANG = "en"

# Clip cache root (GH-1237). Deliberately NOT under RUN_DIR: the whole
# point is to survive a re-take, and RUN_DIR is per-run, so a cache
# rooted there is unreachable by exactly the process that needs it.
NARRATION_CACHE_ROOT = Path(
    os.environ.get("DEV10X_NARRATION_CACHE", "/tmp/Dev10x/self-qa/narration-cache")
)

# Cache entries older than this are swept on write. A clip is cheap to
# re-render once and the cache has no invalidation signal from the voice
# model, so age is the only honest bound.
CACHE_MAX_AGE_SECONDS = 14 * 24 * 60 * 60

# How often the sweep above is worth paying for. Without this the sweep
# stats every entry on every capture run, so its cost tracks the cache's
# total history rather than the current script's ~10-30 lines — a walk
# that grows without bound while the thing it is protecting does not.
CACHE_SWEEP_INTERVAL_SECONDS = 24 * 60 * 60


def voice_pin_fingerprint(path: Path | None = None) -> str:
    """Fingerprint the durable voice pin that decides an unnamed voice.

    Both documented call sites construct ``Narration`` with no ``voice``,
    so the requested voice is ``None`` and the *resolved* one comes from
    ``~/.config/Dev10x/tts.yaml``. A key built from the requested voice
    alone would therefore keep serving the old voice after a re-pin —
    which is GH-1221's silent-divergence failure wearing a cache, and for
    a CC BY-NC-SA voice past its licence gate that is a licence breach
    rather than a wrong timbre. Folding the pin's content into the key
    makes a re-pin miss automatically instead of relying on anyone
    remembering to clear the cache.
    """
    pin = (
        path
        or Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "Dev10x" / "tts.yaml"
    )
    try:
        return hashlib.sha256(pin.read_bytes()).hexdigest()[:16]
    except OSError:
        # No pin file is itself a stable state to key on — it resolves to
        # the wrapper's built-in default until someone pins one.
        return "unpinned"


def cache_key(*, voice: str | None, lang: str | None, text: str, pin: str | None = None) -> str:
    """Content address for one synthesized clip.

    ``lang`` is part of the key, not an afterthought: GH-1221 made the
    same text in the same voice resolve to different audio per language,
    so a key without it returns a clip that is confidently wrong rather
    than merely stale. ``pin`` covers the same hazard for the voice —
    see ``voice_pin_fingerprint``.
    """
    material = "\x1f".join(
        [
            voice or "",
            lang or "",
            pin if pin is not None else voice_pin_fingerprint(),
            collapse_line(text),
        ]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


def _sweep_cache(root: Path, *, now: float | None = None) -> None:
    """Drop cache entries past ``CACHE_MAX_AGE_SECONDS``.

    Best-effort: a cache that cannot be swept is still a usable cache,
    so every failure here is survivable and none of them should abort a
    capture that was otherwise ready to run.
    """
    moment = now if now is not None else time.time()
    # A sentinel keeps the full walk to roughly once a day. Touched before
    # the walk, not after, so two runs starting together do not both decide
    # they are the one that has to sweep.
    sentinel = root / ".last-swept"
    try:
        if moment - sentinel.stat().st_mtime < CACHE_SWEEP_INTERVAL_SECONDS:
            return
    except OSError:
        pass
    cutoff = moment - CACHE_MAX_AGE_SECONDS
    try:
        root.mkdir(parents=True, exist_ok=True)
        sentinel.touch()
        entries = list(root.iterdir())
    except OSError:
        return
    for entry in entries:
        try:
            if entry.stat().st_mtime >= cutoff:
                continue
            shutil.rmtree(entry) if entry.is_dir() else entry.unlink()
        except OSError:
            continue


def collapse_line(text: str) -> str:
    """Collapse a caption to one line.

    Must match ``skills/tts/scripts/synthesize.py::collapse_line`` — this
    is the lookup key on both sides of the subprocess boundary, so the two
    have to agree or every pre-rendered clip misses. They cannot share an
    import (the synthesizer is a standalone uv-script), so
    ``tests/skills/test_narration_tts_agreement.py`` pins them against a
    shared corpus.

    The synthesizer wraps this in a ``normalize_line`` that rejects an
    empty result; the recorder does not, because a caption is validated
    once at ``Narration`` construction rather than on every lookup.
    """
    return re.sub(r"\s+", " ", text).strip()


def default_runner(
    payload: dict,
    out_dir: Path,
    voice: str | None,
    lang: str | None = None,
) -> dict:
    """Invoke the bundled Dev10x:tts wrapper and return its JSON payload.

    ``lang`` is forwarded as ``--lang`` (GH-1221). Without it the wrapper
    resolves the language-agnostic ``voice:`` key, so a pin made with
    ``tts pin --lang en --voice af_heart`` — which nests under
    ``languages.en`` — is never consulted on this path. ``tts check --lang
    en`` reads the pin and reports the commercial voice, so the pin looks
    correct while the walkthrough narrates in a different one; for a
    CC BY-NC-SA voice already past its one-time licence gate, that
    divergence is a silent licence breach rather than a wrong timbre.
    """
    script = os.environ.get("DEV10X_TTS_SCRIPT")
    if not script:
        raise NarrationError(
            "DEV10X_TTS_SCRIPT is not set — run the capture through"
            " skills/playwright/scripts/run-playwright.sh, which exports it."
        )
    command = [script, "batch", "--out-dir", str(out_dir)]
    if voice:
        command += ["--voice", voice]
    if lang:
        command += ["--lang", lang]
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


class FixtureProbeError(NarrationError):
    """The fixture probe failed, so synthesis was refused (GH-1238).

    A subclass rather than a bare ``NarrationError`` because the caller's
    response differs: a synthesis failure is a narration problem, this is
    the run telling you the fixture is not there yet — and it is raised
    *before* any model load, which is the whole point.
    """


class CaptionClaimError(NarrationError):
    """A caption's asserted state did not hold, so the beat was aborted (GH-1240).

    Distinct from a synthesis failure: the audio is fine, the claim is
    not. Narrating over it would put a falsehood in the artifact.
    """


def _accepts_lang(runner: Callable[..., dict]) -> bool:
    """Whether ``runner`` can receive the fourth, language argument.

    ``runner`` is a caller-supplied seam, so widening it is a breaking
    change for anyone who wrote one against the pre-GH-1221 three-
    argument shape. A callable whose signature cannot be read (a C
    builtin, a mock) is assumed to accept it — guessing "no" there
    would silently drop the language on a runner that wanted it.
    """
    try:
        signature = inspect.signature(runner)
    except (TypeError, ValueError):
        return True
    parameters = list(signature.parameters.values())
    if any(p.kind is inspect.Parameter.VAR_POSITIONAL for p in parameters):
        return True
    positional = [
        p
        for p in parameters
        if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    return len(positional) >= 4


def _validated_script(script: Iterable[str]) -> list[str]:
    """Collapse every declared line, refusing one that says nothing.

    An empty line reaches the synthesizer as a segment piper cannot voice.
    The wrapper does reject it — but by then the message is
    ``narration segment is empty after whitespace collapse``, raised
    inside a subprocess, naming neither which line nor where it came
    from. On a thirty-line script that is a hunt; here the index and the
    original text are still in hand, so say them.
    """
    collapsed = []
    for index, line in enumerate(script):
        text = collapse_line(line)
        if not text:
            raise NarrationError(
                f"narration script line {index} is empty (was {line!r}) — every"
                " declared line becomes one synthesized clip, so an empty one"
                " has no audio to pair a caption with. Drop it from the"
                " script, or give it the words the caption will show."
            )
        collapsed.append(text)
    return collapsed


class Narration:
    """Pre-rendered voice-over bound to one recording."""

    def __init__(
        self,
        out_dir: str | Path,
        *,
        script: Iterable[str] = (),
        voice: str | None = None,
        lang: str | None = None,
        tail_ms: int = CAPTION_TAIL_MS,
        runner: Callable[..., dict] = default_runner,
        fixture_probe: Callable[[], Any] | None = None,
        cache_root: str | Path | None = None,
    ) -> None:
        self.out_dir = Path(out_dir)
        self.script = _validated_script(script)
        self.voice = voice
        # `self.voice` is overwritten with whatever the wrapper resolved, so
        # the cache needs the pre-synthesis value: it is the only key the
        # NEXT process can reconstruct before synthesizing anything.
        self._requested_voice = voice
        # The environment sits between the argument and the default rather
        # than below it: `synthesize.py` reads DEV10X_TTS_LANG itself, so a
        # Narration that always sent DEFAULT_LANG would override a
        # supervisor who exported one — narrating Polish text in an English
        # voice, the same divergence pointed the other way.
        requested = lang or os.environ.get("DEV10X_TTS_LANG")
        self.lang = requested or DEFAULT_LANG
        # Only an explicit ask justifies refusing a runner that cannot take
        # a language; a defaulted one must still degrade to the legacy
        # three-argument shape (see `prerender`).
        self._lang_was_requested = bool(requested)
        self.tail_ms = tail_ms
        self._runner = runner
        self._fixture_probe = fixture_probe
        self._cache_root = Path(cache_root) if cache_root is not None else NARRATION_CACHE_ROOT
        # Read once: the pin cannot meaningfully change mid-capture, and
        # re-reading per line would make the key depend on timing.
        self._voice_pin = voice_pin_fingerprint()
        self._clips: dict[str, dict[str, Any]] = {}
        self._cache_hits = 0
        self._spoken: list[dict[str, Any]] = []
        self._unasserted: list[str] = []
        self._t0: float | None = None
        self._anchor = "install"
        self.warning: str | None = None
        # None until synthesis reports it, and None if it never does —
        # "unknown" is a distinct answer from "permitted".
        self.commercial_use_allowed: bool | None = None

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

    def _cached_clip(self, text: str) -> dict[str, Any] | None:
        """Return a previously-synthesized clip for ``text``, if one survives.

        A cache entry is only usable while its ``.wav`` is still on disk —
        the metadata alone would hand back a manifest entry pointing at
        nothing, which is worse than a miss.
        """
        entry = self._cache_root / cache_key(
            voice=self._requested_voice, lang=self.lang, text=text, pin=self._voice_pin
        )
        try:
            payload = json.loads((entry / "clip.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        wav = entry / "clip.wav"
        if not wav.exists():
            return None
        payload["wav"] = str(wav)
        return payload

    def _store_clip(self, segment: dict[str, Any]) -> None:
        """Copy a freshly-synthesized clip into the cross-run cache.

        Best-effort by design: a cache that cannot be written must not
        fail a capture that already has its audio in hand.
        """
        source = segment.get("wav")
        if not source:
            return
        entry = self._cache_root / cache_key(
            voice=self._requested_voice,
            lang=self.lang,
            text=segment["text"],
            pin=self._voice_pin,
        )
        try:
            entry.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, entry / "clip.wav")
            payload = {key: value for key, value in segment.items() if key != "wav"}
            # What actually narrated it, so a later hit can disclose the
            # voice in the audio rather than the voice that was asked for.
            payload["resolved_voice"] = self.voice
            (entry / "clip.json").write_text(json.dumps(payload), encoding="utf-8")
        except OSError:
            return

    def _run_fixture_probe(self) -> None:
        """Refuse synthesis until the fixture probe passes (GH-1238).

        Synthesis is front-loaded and fixture setup runs later, so without
        this gate a run pays the full model-load cost and only then finds
        out the fixture cannot be built. Sessions paid that repeatedly for
        runs that never produced a frame.
        """
        if self._fixture_probe is None:
            return
        try:
            result = self._fixture_probe()
        except Exception as exc:
            raise FixtureProbeError(
                f"fixture probe failed, so narration was not synthesized: {exc}."
                " Fix the named setup step and re-run — no model was loaded,"
                " so this cost fixture time only."
            ) from exc
        if result is False or result is None:
            raise FixtureProbeError(
                "fixture probe returned no confirmation, so narration was not"
                " synthesized. Return a truthy value (or raise naming the unmet"
                " setup step) once the fixture holds."
            )

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
        self._run_fixture_probe()
        # Cross-process reuse (GH-1237). The in-process guard above only
        # helps within one run; a re-take is a fresh process with an empty
        # `_clips`, so every line was re-synthesized on every attempt.
        still_missing = []
        for text in unique:
            cached = self._cached_clip(text)
            if cached is None:
                still_missing.append(text)
                continue
            # Adopt the voice recorded with the clip: the manifest must name
            # what is in the audio, not what was asked for.
            resolved = cached.pop("resolved_voice", None)
            if resolved is not None:
                self.voice = resolved
            self._clips[collapse_line(text)] = cached
            self._cache_hits += 1
        unique = still_missing
        if not unique:
            return
        payload = {
            "segments": [
                {"id": f"line-{index:03d}", "text": text} for index, text in enumerate(unique)
            ]
        }
        self.out_dir.mkdir(parents=True, exist_ok=True)
        if _accepts_lang(self._runner):
            rendered = self._runner(payload, self.out_dir, self.voice, self.lang)
        elif self._lang_was_requested:
            # Refusing beats narrating in the wrong voice: a language that
            # silently fails to reach synthesis is the whole of GH-1221.
            raise NarrationError(
                f"lang={self.lang!r} was requested, but the supplied runner takes"
                " no language argument — give it a `lang: str | None = None`"
                " parameter, or drop the lang."
            )
        else:
            # A legacy runner never received the defaulted language, so the
            # manifest must not claim one was applied. Overclaiming here is
            # the failure this issue is about.
            self.lang = None
            rendered = self._runner(payload, self.out_dir, self.voice)
        self.warning = rendered.get("warning")
        self.voice = rendered.get("voice", self.voice)
        # `batch` already computes this for `check`; nothing read it on this
        # path, so the artifact that reaches a client carried no record of
        # what narrated it. Absent stays None — defaulting to True would let
        # a silent wrapper read as a clean licence. A later batch that omits
        # the field must not downgrade a known answer to "unknown" either:
        # losing a reported `False` is the same silent-wrong-direction
        # failure in miniature.
        reported = rendered.get("commercial_use_allowed")
        if reported is not None:
            self.commercial_use_allowed = reported
        for segment in rendered.get("segments", []):
            self._clips[collapse_line(segment["text"])] = segment
            self._store_clip(segment)
        _sweep_cache(self._cache_root)

    def clip_for(self, text: str) -> dict[str, Any] | None:
        return self._clips.get(collapse_line(text))

    def duration_ms(self, text: str) -> int | None:
        """Spoken length of a pre-rendered line, or None if it was not declared."""
        clip = self.clip_for(text)
        return clip["duration_ms"] if clip else None

    def dwell_ms(self, text: str) -> int | None:
        """Caption dwell for a spoken line: its audio plus a trailing hold."""
        duration = self.duration_ms(text)
        return None if duration is None else duration + self.tail_ms

    # -- recording ------------------------------------------------------

    def assert_claim(self, text: str, assert_state: Callable[[], Any] | None) -> None:
        """Require the state a caption claims, before the caption cues (GH-1240).

        Captions are cued from the script and the timeline, so one fires on
        schedule even when the step meant to produce its claimed outcome
        failed — and ``verify-evidence.py`` validates the artifact, not the
        claim, so such a take passes silently. Aborting here is the only
        point at which the falsehood can still be kept out of the video.

        A beat with no assertion is recorded as unasserted rather than
        rejected: requiring one everywhere would make narration
        all-or-nothing, and a visible gap beats a blocked capture.
        """
        collapsed = collapse_line(text)
        if assert_state is None:
            self._unasserted.append(collapsed)
            return
        try:
            held = assert_state()
        except Exception as exc:
            raise CaptionClaimError(
                f"caption {collapsed!r} asserts a state that raised on check:"
                f" {exc}. The beat was aborted rather than narrated over."
            ) from exc
        if held is False or held is None:
            raise CaptionClaimError(
                f"caption {collapsed!r} claims a state that does not hold —"
                " the beat was aborted rather than narrated over. Fix the step"
                " that should have produced it, or correct the caption."
            )

    def record(
        self,
        text: str,
        dwell_ms: int,
        *,
        asserted: bool | None = None,
    ) -> dict[str, Any]:
        """Note that ``text`` was shown now, and return its manifest entry."""
        clip = self.clip_for(text)
        collapsed = collapse_line(text)
        entry = {
            "index": len(self._spoken),
            "text": collapsed,
            "offset_ms": self.offset_ms(),
            "dwell_ms": dwell_ms,
            "wav": clip["wav"] if clip else None,
            "duration_ms": clip["duration_ms"] if clip else None,
            # None means the caller predates `assert_state` entirely; False
            # means it opted out for this beat. Collapsing the two would
            # report an old script as deliberately unchecked.
            "asserted": asserted,
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

    @property
    def declared(self) -> list[str]:
        """Every line the script registered, first-seen order, deduplicated."""
        return list(dict.fromkeys(self.script))

    @property
    def played(self) -> list[str]:
        """Every line that actually reached the screen, deduplicated."""
        return list(dict.fromkeys(entry["text"] for entry in self._spoken))

    @property
    def unasserted(self) -> list[str]:
        """Captions that cued without checking the state they claim (GH-1240).

        Not a failure — a reviewable gap. A long list means the take's
        claims rest on the script's word rather than the application's.
        """
        return list(dict.fromkeys(self._unasserted))

    @property
    def cache_hits(self) -> int:
        """Clips served from the cross-run cache instead of re-synthesized."""
        return self._cache_hits

    @property
    def never_played(self) -> list[str]:
        """Declared lines that never played (GH-1218).

        ``unrendered`` is computed from ``_spoken`` and so can only ever
        report lines that DID play — a declared line whose ``say()`` never
        ran is absent from that list by construction, and the manifest
        reported ``unrendered: []`` for a run that silently dropped a whole
        beat. The two lists answer different questions and both are needed:
        ``unrendered`` is "played, but mute", this is "never spoke at all".
        """
        played = set(self.played)
        return [text for text in self.declared if text not in played]

    # -- output ---------------------------------------------------------

    def manifest(self) -> dict[str, Any]:
        return {
            "voice": self.voice,
            "lang": self.lang,
            "anchor": self._anchor,
            "tail_ms": self.tail_ms,
            "warning": self.warning,
            # Disclosure, never enforcement: whether this recording is
            # commercial use, and whether a non-commercial voice is
            # acceptable in it, is the supervisor's call. The run records
            # what it narrated in and leaves the decision alone.
            "commercial_use_allowed": self.commercial_use_allowed,
            "unrendered": self.unrendered,
            "declared": self.declared,
            "never_played": self.never_played,
            # Which claims the run actually checked (GH-1240). The verifier
            # cannot tell a true caption from a false one, so this is the
            # only record of how much of the narration was grounded.
            "unasserted": self.unasserted,
            "cache_hits": self._cache_hits,
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
