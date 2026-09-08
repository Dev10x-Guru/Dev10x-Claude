"""The recorder and the synthesizer must collapse a caption identically.

``collapse_line`` is the clip lookup key on both sides of a subprocess
boundary: the synthesizer keys each rendered WAV by it, and the recorder
looks the WAV up by it. They cannot share an import — ``synthesize.py`` is
a standalone PEP 723 uv-script that runs in its own environment and cannot
see ``dev10x`` or the playwright lib — so nothing but this test stops the
two copies from drifting.

Drift is silent in the worst way: every lookup misses, every clip falls
back to the character-derived dwell, and the run produces a video with
captions and no voice-over rather than an error.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_repo_root = Path(__file__).resolve().parent.parent.parent


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_narration = _load("narration", _repo_root / "skills" / "playwright" / "lib" / "narration.py")
_synthesize = _load("synthesize", _repo_root / "skills" / "tts" / "scripts" / "synthesize.py")


# Every shape a narration line has actually arrived in: copy pasted out of
# a Gherkin DocString (leading indent, hard-wrapped), a caption written
# across two source lines, and the non-breaking space a word processor
# leaves behind.
CORPUS = [
    "One click assigns them.",
    "  leading and trailing  ",
    "hard\nwrapped across lines",
    "tabs\tand\tmore\ttabs",
    "    indented\n    like a docstring\n",
    "collapsed   run   of   spaces",
    "trailing newline\n",
    "\n\nleading blank lines",
    "unicode — em dash and ellipsis…",
    "non breaking space",
    "Zapisz zmiany w zleceniu.",
    "one",
]


@pytest.mark.parametrize("text", CORPUS)
def test_both_sides_collapse_a_caption_to_the_same_key(text):
    assert _narration.collapse_line(text) == _synthesize.collapse_line(text)


@pytest.mark.parametrize("text", ["", "   ", "\n\t \n"])
def test_only_the_synthesizer_refuses_an_empty_line(text):
    # The asymmetry is deliberate, not drift: the synthesizer cannot emit a
    # clip for a line that says nothing (piper would return one WAV fewer
    # and shift every later caption onto the wrong audio), while the
    # recorder validates captions once at Narration construction and must
    # not raise from a lookup.
    assert _narration.collapse_line(text) == ""
    assert _synthesize.collapse_line(text) == ""
    with pytest.raises(_synthesize.SynthesisError, match="empty"):
        _synthesize.normalize_line(text)


def test_the_recorder_exposes_no_normalize_line():
    # Two functions under one name, doing different things, is what made
    # the drift hard to see. The strict wrapper belongs to the synthesizer
    # alone; the recorder offers only the shared contract.
    assert not hasattr(_narration, "normalize_line")
