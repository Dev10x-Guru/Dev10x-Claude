"""Tests for the narration module (GH-1112).

The module's whole job is keeping a caption and its voice-over on the same
beat, so these tests pin the properties that would silently desynchronize
them: audio-derived dwell, an offset captured before the caption is shown,
an explicit video-start anchor, and a declared-vs-spoken mismatch that
stays visible instead of playing silently.

Piper is not invoked here — the runner is injected, which is the seam the
module exposes for exactly this reason.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_repo_root = Path(__file__).resolve().parent.parent.parent.parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        name, _repo_root / "skills" / "playwright" / "lib" / f"{name}.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_narration = _load("narration")
_annotate = _load("annotate")


class FakeContext:
    def __init__(self) -> None:
        self.init_scripts: list[str] = []

    def add_init_script(self, script: str) -> None:
        self.init_scripts.append(script)


class FakePage:
    def __init__(self) -> None:
        self.context = FakeContext()
        self.evaluated: list[tuple[str, object]] = []

    def evaluate(self, script: str, arg: object = None) -> None:
        self.evaluated.append((script, arg))


def fake_runner(durations: dict[str, int], *, warning: str | None = None):
    """A runner returning fixed durations, recording how often it ran."""
    calls: list[dict] = []

    def run(payload: dict, out_dir: Path, voice: str | None) -> dict:
        calls.append(payload)
        return {
            "voice": voice or "test-voice",
            "warning": warning,
            "segments": [
                {
                    "index": index,
                    "id": segment["id"],
                    "text": segment["text"],
                    "wav": str(out_dir / f"seg-{index:03d}.wav"),
                    "duration_ms": durations[segment["text"]],
                }
                for index, segment in enumerate(payload["segments"])
            ],
        }

    run.calls = calls  # type: ignore[attr-defined]
    return run


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(_annotate.time, "sleep", lambda seconds: None)


class TestNormalizeLine:
    def test_collapses_newlines_so_one_caption_stays_one_clip(self):
        assert _narration.normalize_line("one\ntwo   three\t") == "one two three"

    def test_matches_the_synthesizer_side_key(self):
        # Both sides key clips on this exact transformation; if they drift,
        # every pre-rendered clip misses and narration silently vanishes.
        messy = "  Pick a customer.\n One click assigns them.  "
        assert _narration.normalize_line(messy) == "Pick a customer. One click assigns them."


class TestPrerender:
    def test_synthesizes_every_line_in_one_batch(self, tmp_path):
        runner = fake_runner({"alpha": 1000, "beta": 2000})
        narration = _narration.Narration(tmp_path, script=["alpha", "beta"], runner=runner)
        narration.prerender()

        assert len(runner.calls) == 1, "narration must not pay a model load per line"
        assert len(runner.calls[0]["segments"]) == 2

    def test_duplicate_lines_render_once_and_are_reused(self, tmp_path):
        runner = fake_runner({"alpha": 1000})
        narration = _narration.Narration(tmp_path, script=["alpha", "alpha"], runner=runner)
        narration.prerender()

        assert len(runner.calls[0]["segments"]) == 1
        assert narration.duration_ms("alpha") == 1000

    def test_empty_script_does_not_invoke_the_synthesizer(self, tmp_path):
        runner = fake_runner({})
        _narration.Narration(tmp_path, script=[], runner=runner).prerender()
        assert runner.calls == []

    def test_warning_from_the_wrapper_is_carried_through(self, tmp_path):
        runner = fake_runner({"alpha": 1000}, warning="voice is CC BY-NC-SA 4.0")
        narration = _narration.Narration(tmp_path, script=["alpha"], runner=runner)
        narration.prerender()
        assert narration.warning == "voice is CC BY-NC-SA 4.0"


class TestDwell:
    def test_dwell_is_the_audio_plus_a_tail(self, tmp_path):
        narration = _narration.Narration(
            tmp_path, script=["alpha"], runner=fake_runner({"alpha": 2400})
        )
        narration.prerender()
        assert narration.dwell_ms("alpha") == 2400 + _narration.CAPTION_TAIL_MS

    def test_undeclared_line_has_no_audio_dwell(self, tmp_path):
        narration = _narration.Narration(
            tmp_path, script=["alpha"], runner=fake_runner({"alpha": 2400})
        )
        narration.prerender()
        assert narration.dwell_ms("never declared") is None


class TestTimeline:
    def test_offsets_are_relative_to_the_marked_video_start(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_narration.time, "monotonic", _stub_clock(start=100.0, step=3.5))

        narration = _narration.Narration(tmp_path, runner=fake_runner({}))
        narration.mark_video_start()
        entry = narration.record("spoken later", dwell_ms=1000)

        assert entry["offset_ms"] == 3500

    def test_missing_anchor_is_recorded_rather_than_assumed(self, tmp_path):
        narration = _narration.Narration(tmp_path, runner=fake_runner({}))
        narration.record("no anchor was marked", dwell_ms=1000)
        assert narration.manifest()["anchor"] == "install"

    def test_marked_anchor_is_recorded(self, tmp_path):
        narration = _narration.Narration(tmp_path, runner=fake_runner({}))
        narration.mark_video_start()
        assert narration.manifest()["anchor"] == "video-start"


class TestManifest:
    def test_only_lines_with_audio_reach_the_timeline(self, tmp_path):
        narration = _narration.Narration(
            tmp_path, script=["alpha"], runner=fake_runner({"alpha": 1000})
        )
        narration.prerender()
        narration.record("alpha", dwell_ms=1700)
        narration.record("undeclared", dwell_ms=2000)

        manifest = narration.manifest()
        assert [segment["text"] for segment in manifest["segments"]] == ["alpha"]
        assert manifest["unrendered"] == ["undeclared"]
        assert len(manifest["all_captions"]) == 2

    def test_manifest_is_written_as_json(self, tmp_path):
        narration = _narration.Narration(
            tmp_path, script=["alpha"], runner=fake_runner({"alpha": 1000})
        )
        narration.prerender()
        narration.record("alpha", dwell_ms=1700)

        written = narration.write_manifest()
        assert json.loads(written.read_text())["segments"][0]["duration_ms"] == 1000


class TestAnnotatorIntegration:
    def test_say_uses_the_audio_duration_for_dwell(self, tmp_path):
        narration = _narration.Narration(
            tmp_path, script=["alpha"], runner=fake_runner({"alpha": 2400})
        )
        page = FakePage()
        anno = _annotate.Annotator(page, narration=narration)
        anno.install()
        anno.say("alpha")

        _, argument = page.evaluated[-1]
        assert argument == ["alpha", 2400 + _narration.CAPTION_TAIL_MS]

    def test_say_without_narration_keeps_the_length_derived_dwell(self):
        page = FakePage()
        anno = _annotate.Annotator(page)
        anno.install()
        anno.say("alpha")

        _, argument = page.evaluated[-1]
        assert argument == ["alpha", _annotate.caption_dwell_ms("alpha")]

    def test_undeclared_line_falls_back_rather_than_failing(self, tmp_path):
        narration = _narration.Narration(
            tmp_path, script=["alpha"], runner=fake_runner({"alpha": 2400})
        )
        page = FakePage()
        anno = _annotate.Annotator(page, narration=narration)
        anno.install()
        anno.say("undeclared line")

        _, argument = page.evaluated[-1]
        assert argument == ["undeclared line", _annotate.caption_dwell_ms("undeclared line")]
        assert narration.unrendered == ["undeclared line"]

    def test_install_prerenders_before_the_first_caption(self, tmp_path):
        runner = fake_runner({"alpha": 1000})
        narration = _narration.Narration(tmp_path, script=["alpha"], runner=runner)
        anno = _annotate.Annotator(FakePage(), narration=narration)
        anno.install()
        assert len(runner.calls) == 1

    def test_cue_is_recorded_before_the_settle_sleep(self, tmp_path, monkeypatch):
        # The offset must mark when the viewer first SEES the line. Recording
        # it after say()'s sleep would cue every clip one full dwell late.
        #
        # settle MUST stay True here: with settle=False the sleep branch never
        # runs, so an assertion hung off the sleep can never fire and a
        # record-after-sleep regression would pass unnoticed.
        monkeypatch.setattr(_narration.time, "monotonic", _stub_clock(start=0.0, step=5.0))

        observed: dict[str, list] = {}

        def capture_state_at_sleep(seconds: float) -> None:
            observed["spoken"] = list(narration.spoken)

        monkeypatch.setattr(_annotate.time, "sleep", capture_state_at_sleep)

        narration = _narration.Narration(
            tmp_path, script=["alpha"], runner=fake_runner({"alpha": 1000})
        )
        narration.mark_video_start()
        anno = _annotate.Annotator(FakePage(), narration=narration)
        anno.install()
        anno.say("alpha")

        assert observed["spoken"], "the cue must already be recorded when say() sleeps"
        assert narration.spoken[0]["offset_ms"] == 5000


class TestDefaultRunner:
    """The production glue that actually shells out to the tts wrapper."""

    def test_missing_env_var_names_the_runner_that_sets_it(self, tmp_path, monkeypatch):
        monkeypatch.delenv("DEV10X_TTS_SCRIPT", raising=False)
        with pytest.raises(_narration.NarrationError, match="run-playwright.sh"):
            _narration.default_runner({"segments": []}, tmp_path, None)

    def test_wrapper_error_payload_is_surfaced(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DEV10X_TTS_SCRIPT", "/bin/true")
        monkeypatch.setattr(
            _narration.subprocess,
            "run",
            lambda *a, **k: _Completed(1, json.dumps({"error": "voice not installed"}), ""),
        )
        with pytest.raises(_narration.NarrationError, match="voice not installed"):
            _narration.default_runner({"segments": []}, tmp_path, None)

    def test_unparseable_output_is_reported_not_swallowed(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DEV10X_TTS_SCRIPT", "/bin/true")
        monkeypatch.setattr(
            _narration.subprocess, "run", lambda *a, **k: _Completed(1, "not json", "boom")
        )
        with pytest.raises(_narration.NarrationError, match="unparseable"):
            _narration.default_runner({"segments": []}, tmp_path, None)

    def test_timeout_becomes_a_narration_error(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DEV10X_TTS_SCRIPT", "/bin/true")

        def wedge(*args, **kwargs):
            raise _narration.subprocess.TimeoutExpired(cmd="piper", timeout=1)

        monkeypatch.setattr(_narration.subprocess, "run", wedge)
        with pytest.raises(_narration.NarrationError, match="wedged"):
            _narration.default_runner({"segments": []}, tmp_path, None)

    def test_voice_is_forwarded_to_the_wrapper(self, tmp_path, monkeypatch):
        captured: dict[str, list] = {}
        monkeypatch.setenv("DEV10X_TTS_SCRIPT", "/bin/true")

        def record_command(command, **kwargs):
            captured["command"] = command
            return _Completed(0, json.dumps({"voice": "v", "segments": []}), "")

        monkeypatch.setattr(_narration.subprocess, "run", record_command)
        result = _narration.default_runner({"segments": []}, tmp_path, "en_US-ryan-medium")

        assert "--voice" in captured["command"]
        assert "en_US-ryan-medium" in captured["command"]
        assert result["voice"] == "v"


class _Completed:
    def __init__(self, returncode: int, stdout: str, stderr: str) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _stub_clock(*, start: float, step: float):
    """An unbounded monotonic stub.

    A fixed iter([...]) raises StopIteration when the call count shifts,
    which reports as an error rather than as the offset mismatch the test
    is actually about.
    """
    state = {"now": start - step}

    def now() -> float:
        state["now"] += step
        return state["now"]

    return now
