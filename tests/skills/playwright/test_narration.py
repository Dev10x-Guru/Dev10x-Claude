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
import sys
from pathlib import Path

import pytest

_repo_root = Path(__file__).resolve().parent.parent.parent.parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        name, _repo_root / "skills" / "playwright" / "lib" / f"{name}.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Registered before exec because `@dataclass` resolves annotations
    # through `sys.modules[cls.__module__]`, which is how a generated
    # script importing this off `DEV10X_PLAYWRIGHT_LIB` loads it anyway.
    sys.modules[name] = module
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
    langs: list[str | None] = []

    def run(payload: dict, out_dir: Path, voice: str | None, lang: str | None = None) -> dict:
        calls.append(payload)
        langs.append(lang)
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
    run.langs = langs  # type: ignore[attr-defined]
    return run


def caching_runner(durations: dict[str, int], *, voice: str = "test-voice"):
    """A runner that actually writes its wav files.

    ``fake_runner`` returns paths without creating them, which is fine for
    every test that only reads durations — but the clip cache copies the
    wav, so a runner whose files do not exist exercises the cache's
    best-effort failure path instead of its success path.
    """
    calls: list[dict] = []

    def run(payload: dict, out_dir: Path, requested: str | None, lang: str | None = None) -> dict:
        calls.append(payload)
        out_dir.mkdir(parents=True, exist_ok=True)
        segments = []
        for index, segment in enumerate(payload["segments"]):
            wav = out_dir / f"seg-{index:03d}.wav"
            wav.write_bytes(b"RIFF-fake")
            segments.append(
                {
                    "index": index,
                    "id": segment["id"],
                    "text": segment["text"],
                    "wav": str(wav),
                    "duration_ms": durations[segment["text"]],
                }
            )
        return {"voice": requested or voice, "warning": None, "segments": segments}

    run.calls = calls  # type: ignore[attr-defined]
    return run


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path_factory, monkeypatch):
    """Keep the clip cache out of the real shared /tmp root.

    ``NARRATION_CACHE_ROOT`` deliberately lives outside RUN_DIR so it can
    survive a re-take — which also means an un-patched test would read and
    write a path shared with every other run on the machine, and could be
    handed a "cached" clip it never synthesized.
    """
    root = tmp_path_factory.mktemp("narration-cache")
    monkeypatch.setattr(_narration, "NARRATION_CACHE_ROOT", root)
    return root


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(_annotate.time, "sleep", lambda seconds: None)


class TestCollapseLine:
    def test_collapses_newlines_so_one_caption_stays_one_clip(self):
        assert _narration.collapse_line("one\ntwo   three\t") == "one two three"

    def test_matches_the_synthesizer_side_key(self):
        # Both sides key clips on this exact transformation; if they drift,
        # every pre-rendered clip misses and narration silently vanishes.
        # tests/skills/test_narration_tts_agreement.py pins the two against
        # a shared corpus — this case is the readable summary of it.
        messy = "  Pick a customer.\n One click assigns them.  "
        assert _narration.collapse_line(messy) == "Pick a customer. One click assigns them."


class TestScriptValidation:
    @pytest.mark.parametrize("blank", ["", "   ", "\n\t "])
    def test_an_empty_declared_line_is_refused_at_construction(self, tmp_path, blank):
        # Left to the synthesizer, this surfaces as "narration segment is
        # empty after whitespace collapse" from inside a subprocess, naming
        # neither the line nor the script it came from.
        runner = fake_runner({})
        with pytest.raises(_narration.NarrationError) as caught:
            _narration.Narration(tmp_path, script=["alpha", blank], runner=runner)
        assert runner.calls == [], "synthesis must not start with a bad script"
        assert "line 1" in str(caught.value)

    def test_the_refusal_quotes_the_original_text(self, tmp_path):
        with pytest.raises(_narration.NarrationError, match=r"'\\n\\t '"):
            _narration.Narration(tmp_path, script=["\n\t "], runner=fake_runner({}))


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

    def test_a_second_call_does_not_re_synthesize(self, tmp_path):
        # The corrected capture ordering calls prerender() and then
        # install(), which calls it again — under Kokoro that second pass
        # is a model load per line, not tidiness (GH-1205).
        runner = fake_runner({"alpha": 1000, "beta": 2000})
        narration = _narration.Narration(tmp_path, script=["alpha", "beta"], runner=runner)
        narration.prerender()
        narration.prerender()

        assert len(runner.calls) == 1
        assert narration.duration_ms("alpha") == 1000

    def test_a_second_call_renders_only_lines_added_since(self, tmp_path):
        runner = fake_runner({"alpha": 1000, "beta": 2000})
        narration = _narration.Narration(tmp_path, script=["alpha"], runner=runner)
        narration.prerender()
        narration.script.append("beta")
        narration.prerender()

        assert len(runner.calls) == 2
        assert [segment["text"] for segment in runner.calls[1]["segments"]] == ["beta"]

    def test_a_guarded_second_call_keeps_the_licence_warning(self, tmp_path):
        runner = fake_runner({"alpha": 1000}, warning="voice is CC BY-NC-SA 4.0")
        narration = _narration.Narration(tmp_path, script=["alpha"], runner=runner)
        narration.prerender()
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


class TestLanguage:
    def test_the_requested_language_reaches_the_runner(self, tmp_path):
        # GH-1221: a `tts pin --lang en` nests under languages.en, so a
        # runner never told the language resolves the language-agnostic
        # voice instead and the pin silently misses this path.
        runner = fake_runner({"alpha": 1000})
        narration = _narration.Narration(tmp_path, script=["alpha"], lang="en", runner=runner)
        narration.prerender()

        assert runner.langs == ["en"]

    def test_no_language_still_resolves_one(self, tmp_path, monkeypatch):
        # GH-1221's residual half. Forwarding --lang was necessary but not
        # sufficient: both documented call sites construct Narration with
        # neither lang= nor voice=, so leaving the flag off meant the
        # language-scoped pin was still never consulted on the one path
        # that produces client-facing artifacts.
        monkeypatch.delenv("DEV10X_TTS_LANG", raising=False)
        runner = fake_runner({"alpha": 1000})
        _narration.Narration(tmp_path, script=["alpha"], runner=runner).prerender()

        assert runner.langs == [_narration.DEFAULT_LANG]

    def test_the_environment_language_is_honoured_when_none_is_passed(self, tmp_path, monkeypatch):
        # The default must not shadow a supervisor who exported the
        # variable: synthesize.py reads DEV10X_TTS_LANG itself, so a
        # Narration that always sent "en" would narrate Polish text in
        # an English voice — the same divergence pointed the other way.
        monkeypatch.setenv("DEV10X_TTS_LANG", "pl")
        runner = fake_runner({"alpha": 1000})
        _narration.Narration(tmp_path, script=["alpha"], runner=runner).prerender()

        assert runner.langs == ["pl"]

    def test_an_explicit_language_outranks_the_environment(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DEV10X_TTS_LANG", "pl")
        runner = fake_runner({"alpha": 1000})
        _narration.Narration(tmp_path, script=["alpha"], lang="en", runner=runner).prerender()

        assert runner.langs == ["en"]

    def test_the_resolved_language_is_what_the_manifest_records(self, tmp_path, monkeypatch):
        # The manifest is the disclosure surface, so it must report the
        # language actually synthesized in — not the None that was passed.
        monkeypatch.delenv("DEV10X_TTS_LANG", raising=False)
        narration = _narration.Narration(
            tmp_path, script=["alpha"], runner=fake_runner({"alpha": 1000})
        )
        narration.prerender()

        assert narration.manifest()["lang"] == _narration.DEFAULT_LANG

    def test_the_language_is_recorded_in_the_manifest(self, tmp_path):
        narration = _narration.Narration(
            tmp_path, script=["alpha"], lang="pl", runner=fake_runner({"alpha": 1000})
        )
        narration.prerender()

        assert narration.manifest()["lang"] == "pl"

    def _record_argv(self, monkeypatch) -> dict[str, list[str]]:
        """Capture the argv `default_runner` builds, using the file's stub."""
        monkeypatch.setenv("DEV10X_TTS_SCRIPT", "/bin/true")
        seen: dict[str, list[str]] = {}

        def fake_subprocess_run(command, **kwargs):
            seen["command"] = command
            return _Completed(0, json.dumps({"segments": []}), "")

        monkeypatch.setattr(_narration.subprocess, "run", fake_subprocess_run)
        return seen

    def test_default_runner_passes_lang_to_the_wrapper(self, tmp_path, monkeypatch):
        # Pins the argv itself: the bug was not in the plumbing above but
        # in this command being built without --lang at all.
        seen = self._record_argv(monkeypatch)

        _narration.default_runner({"segments": []}, tmp_path, "af_heart", "en")

        assert "--lang" in seen["command"]
        assert seen["command"][seen["command"].index("--lang") + 1] == "en"

    def test_a_pre_existing_three_argument_runner_still_works(self, tmp_path):
        # `runner` is a caller-supplied seam, so widening it must not
        # break a runner written against the old three-argument shape.
        calls: list[str | None] = []

        def legacy_runner(payload: dict, out_dir: Path, voice: str | None) -> dict:
            calls.append(voice)
            return {"voice": voice, "segments": []}

        _narration.Narration(tmp_path, script=["alpha"], runner=legacy_runner).prerender()

        assert calls == [None]

    def test_a_three_argument_runner_refuses_a_language(self, tmp_path):
        # Silently dropping the language is exactly the GH-1221 defect.
        def legacy_runner(payload: dict, out_dir: Path, voice: str | None) -> dict:
            return {"voice": voice, "segments": []}

        narration = _narration.Narration(
            tmp_path, script=["alpha"], lang="en", runner=legacy_runner
        )

        with pytest.raises(_narration.NarrationError, match="no language argument"):
            narration.prerender()

    def test_default_runner_omits_lang_when_unset(self, tmp_path, monkeypatch):
        seen = self._record_argv(monkeypatch)

        _narration.default_runner({"segments": []}, tmp_path, "af_heart")

        assert "--lang" not in seen["command"]


class TestLicenceDisclosure:
    """The manifest discloses the licence; it never enforces it.

    Whether a recording is commercial use, and whether a non-commercial
    voice is acceptable in it, is the supervisor's call. So the run
    records what it narrated in and leaves the decision alone — there is
    deliberately no refusal here to assert.
    """

    @staticmethod
    def _runner(**extra):
        def run(payload, out_dir, voice, lang=None):
            return {
                "voice": voice or "test-voice",
                "segments": [
                    {
                        "index": index,
                        "id": segment["id"],
                        "text": segment["text"],
                        "wav": str(out_dir / f"seg-{index:03d}.wav"),
                        "duration_ms": 1000,
                    }
                    for index, segment in enumerate(payload["segments"])
                ],
                **extra,
            }

        return run

    def test_the_licence_standing_of_the_voice_is_carried_through(self, tmp_path):
        # `batch` already computes this for `check`; it was simply never
        # read on the walkthrough path, so the one artifact that reaches a
        # client carried no record of what narrated it.
        narration = _narration.Narration(
            tmp_path, script=["alpha"], runner=self._runner(commercial_use_allowed=False)
        )
        narration.prerender()

        assert narration.manifest()["commercial_use_allowed"] is False

    def test_a_commercially_licensed_voice_is_recorded_as_such(self, tmp_path):
        narration = _narration.Narration(
            tmp_path, script=["alpha"], runner=self._runner(commercial_use_allowed=True)
        )
        narration.prerender()

        assert narration.manifest()["commercial_use_allowed"] is True

    def test_a_wrapper_that_reports_nothing_is_unknown_not_permitted(self, tmp_path):
        # Absent is not the same as allowed. Defaulting to True would let a
        # silent wrapper read as a clean licence, which is the direction
        # this whole issue was about.
        narration = _narration.Narration(tmp_path, script=["alpha"], runner=self._runner())
        narration.prerender()

        assert narration.manifest()["commercial_use_allowed"] is None

    def test_a_later_batch_cannot_downgrade_a_known_answer(self, tmp_path):
        # The second batch renders a newly added line but reports no
        # licence standing. Letting that reset a reported False to None
        # would turn "not permitted" back into "unknown" — the same
        # silent-wrong-direction failure, smaller.
        standings = [False, None]

        def run(payload, out_dir, voice, lang=None):
            standing = standings.pop(0)
            rendered = self._runner()(payload, out_dir, voice, lang)
            if standing is not None:
                rendered["commercial_use_allowed"] = standing
            return rendered

        narration = _narration.Narration(tmp_path, script=["alpha"], runner=run)
        narration.prerender()
        narration.script.append("beta")
        narration.prerender()

        assert narration.manifest()["commercial_use_allowed"] is False

    def test_disclosure_does_not_block_the_run(self, tmp_path):
        # Licence compliance is the supervisor's call: a non-commercial
        # voice must still produce a usable narration.
        narration = _narration.Narration(
            tmp_path, script=["alpha"], runner=self._runner(commercial_use_allowed=False)
        )
        narration.prerender()
        narration.record("alpha", dwell_ms=1700)

        assert narration.manifest()["segments"]


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

    def test_a_declared_line_that_never_played_is_reported(self, tmp_path):
        # GH-1218: the regression. `unrendered` is derived from what
        # played, so it structurally cannot report a line that did not —
        # it stayed [] while a whole declared beat went missing.
        narration = _narration.Narration(
            tmp_path,
            script=["alpha", "beta"],
            runner=fake_runner({"alpha": 1000, "beta": 900}),
        )
        narration.prerender()
        narration.record("alpha", dwell_ms=1700)

        manifest = narration.manifest()
        assert manifest["unrendered"] == []
        assert manifest["never_played"] == ["beta"]
        assert manifest["declared"] == ["alpha", "beta"]

    def test_a_fully_played_script_reports_nothing_missing(self, tmp_path):
        narration = _narration.Narration(
            tmp_path,
            script=["alpha", "beta"],
            runner=fake_runner({"alpha": 1000, "beta": 900}),
        )
        narration.prerender()
        narration.record("alpha", dwell_ms=1700)
        narration.record("beta", dwell_ms=1600)

        manifest = narration.manifest()
        assert manifest["never_played"] == []
        assert manifest["unrendered"] == []

    def test_never_played_and_unrendered_answer_different_questions(self, tmp_path):
        # One line declared and skipped, one line played without audio.
        # Collapsing these into a single list loses one of the two.
        narration = _narration.Narration(
            tmp_path,
            script=["alpha", "beta"],
            runner=fake_runner({"alpha": 1000, "beta": 900}),
        )
        narration.prerender()
        narration.record("alpha", dwell_ms=1700)
        narration.record("improvised", dwell_ms=2000)

        manifest = narration.manifest()
        assert manifest["never_played"] == ["beta"]
        assert manifest["unrendered"] == ["improvised"]

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
        assert argument == ["alpha", 2400 + _narration.CAPTION_TAIL_MS, None, "claim"]

    def test_say_without_narration_keeps_the_length_derived_dwell(self):
        page = FakePage()
        anno = _annotate.Annotator(page)
        anno.install()
        anno.say("alpha")

        _, argument = page.evaluated[-1]
        assert argument == ["alpha", _annotate.caption_dwell_ms("alpha"), None, "claim"]

    def test_undeclared_line_falls_back_rather_than_failing(self, tmp_path):
        narration = _narration.Narration(
            tmp_path, script=["alpha"], runner=fake_runner({"alpha": 2400})
        )
        page = FakePage()
        anno = _annotate.Annotator(page, narration=narration)
        anno.install()
        anno.say("undeclared line")

        _, argument = page.evaluated[-1]
        assert argument == [
            "undeclared line",
            _annotate.caption_dwell_ms("undeclared line"),
            None,
            "claim",
        ]
        assert narration.unrendered == ["undeclared line"]

    def test_say_refuses_a_caption_whose_claim_does_not_hold(self, tmp_path):
        # GH-1240: the caption is cued from the script, so without this the
        # beat narrates success over a step that failed — and the evidence
        # verifier checks the artifact, not the claim, so it passes.
        narration = _narration.Narration(
            tmp_path, script=["alpha"], runner=fake_runner({"alpha": 2400})
        )
        page = FakePage()
        anno = _annotate.Annotator(page, narration=narration)
        anno.install()
        before = len(page.evaluated)

        with pytest.raises(_narration.CaptionClaimError):
            anno.say("alpha", assert_state=lambda: False)

        assert len(page.evaluated) == before, "no caption may reach the page"
        assert narration.spoken == []

    def test_say_records_whether_the_beat_was_asserted(self, tmp_path):
        narration = _narration.Narration(
            tmp_path, script=["alpha", "beta"], runner=fake_runner({"alpha": 100, "beta": 100})
        )
        page = FakePage()
        anno = _annotate.Annotator(page, narration=narration)
        anno.install()
        anno.say("alpha", assert_state=lambda: True)
        anno.say("beta")

        assert [entry["asserted"] for entry in narration.spoken] == [True, False]
        assert narration.unasserted == ["beta"]

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


class TestClipCache:
    """Cross-take reuse of synthesized audio (GH-1237)."""

    def test_a_second_process_reuses_the_first_ones_audio(self, tmp_path):
        first = caching_runner({"alpha": 1000})
        _narration.Narration(tmp_path / "one", script=["alpha"], runner=first).prerender()
        assert len(first.calls) == 1

        # A re-take is a NEW Narration with an empty _clips and a fresh
        # RUN_DIR — exactly the case the in-process GH-1205 guard misses.
        second = caching_runner({"alpha": 1000})
        retake = _narration.Narration(tmp_path / "two", script=["alpha"], runner=second)
        retake.prerender()

        assert second.calls == [], "a re-take must not re-synthesize a cached line"
        assert retake.duration_ms("alpha") == 1000
        assert retake.cache_hits == 1

    def test_only_the_uncached_lines_are_synthesized(self, tmp_path):
        first = caching_runner({"alpha": 1000})
        _narration.Narration(tmp_path / "one", script=["alpha"], runner=first).prerender()

        second = caching_runner({"alpha": 1000, "beta": 2000})
        retake = _narration.Narration(tmp_path / "two", script=["alpha", "beta"], runner=second)
        retake.prerender()

        rendered = [segment["text"] for segment in second.calls[0]["segments"]]
        assert rendered == ["beta"]
        assert retake.duration_ms("alpha") == 1000

    def test_a_different_language_is_a_different_clip(self, tmp_path):
        # GH-1221 made the same text in the same voice resolve differently
        # per language, so a key without lang returns confidently wrong audio.
        first = caching_runner({"alpha": 1000})
        _narration.Narration(
            tmp_path / "one", script=["alpha"], lang="en", runner=first
        ).prerender()

        second = caching_runner({"alpha": 1000})
        _narration.Narration(
            tmp_path / "two", script=["alpha"], lang="pl", runner=second
        ).prerender()

        assert len(second.calls) == 1, "a language change must miss the cache"

    def test_a_cache_entry_whose_wav_vanished_is_a_miss(self, tmp_path, isolated_cache):
        first = caching_runner({"alpha": 1000})
        _narration.Narration(tmp_path / "one", script=["alpha"], runner=first).prerender()
        for wav in isolated_cache.rglob("clip.wav"):
            wav.unlink()

        second = caching_runner({"alpha": 1000})
        retake = _narration.Narration(tmp_path / "two", script=["alpha"], runner=second)
        retake.prerender()

        # Handing back metadata pointing at a deleted file would produce a
        # manifest entry with no audio behind it — worse than a miss.
        assert len(second.calls) == 1
        assert retake.cache_hits == 0

    def test_an_unwritable_cache_does_not_fail_the_capture(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            _narration.shutil,
            "copyfile",
            lambda *args, **kwargs: (_ for _ in ()).throw(OSError("read-only")),
        )
        runner = caching_runner({"alpha": 1000})
        narration = _narration.Narration(tmp_path, script=["alpha"], runner=runner)
        narration.prerender()

        assert narration.duration_ms("alpha") == 1000

    def test_entries_past_the_age_bound_are_swept(self, tmp_path, isolated_cache):
        stale = isolated_cache / "stale-entry"
        stale.mkdir(parents=True)
        (stale / "clip.wav").write_bytes(b"old")
        import os as _os

        ancient = 1.0
        _os.utime(stale, (ancient, ancient))

        runner = caching_runner({"alpha": 1000})
        _narration.Narration(tmp_path, script=["alpha"], runner=runner).prerender()

        assert not stale.exists(), "the cache has no invalidation signal but age"

    def test_sweeping_an_absent_root_is_survivable(self, tmp_path):
        _narration._sweep_cache(tmp_path / "never-created")

    def test_a_recent_sweep_skips_the_directory_walk(self, tmp_path, isolated_cache):
        # Unthrottled, the sweep stats every entry on every capture run, so
        # its cost tracks the cache's whole history rather than this
        # script's handful of lines.
        stale = isolated_cache / "stale-entry"
        stale.mkdir(parents=True)
        (stale / "clip.wav").write_bytes(b"old")
        import os as _os

        _os.utime(stale, (1.0, 1.0))
        (isolated_cache / ".last-swept").touch()

        _narration._sweep_cache(isolated_cache)

        assert stale.exists(), "a sweep inside the interval must not walk"

    def test_the_walk_resumes_once_the_interval_has_passed(self, tmp_path, isolated_cache):
        stale = isolated_cache / "stale-entry"
        stale.mkdir(parents=True)
        (stale / "clip.wav").write_bytes(b"old")
        import os as _os

        _os.utime(stale, (1.0, 1.0))
        sentinel = isolated_cache / ".last-swept"
        sentinel.touch()
        _os.utime(sentinel, (1.0, 1.0))

        _narration._sweep_cache(isolated_cache)

        assert not stale.exists()

    def test_a_cache_hit_reports_the_voice_that_narrated_it(self, tmp_path):
        first = caching_runner({"alpha": 1000}, voice="af_heart")
        _narration.Narration(tmp_path / "one", script=["alpha"], runner=first).prerender()

        retake = _narration.Narration(
            tmp_path / "two", script=["alpha"], runner=caching_runner({"alpha": 1000})
        )
        retake.prerender()

        # The manifest must name what is in the audio, not what was asked
        # for — the artifact's licence disclosure depends on it.
        assert retake.manifest()["voice"] == "af_heart"

    def test_re_pinning_the_voice_invalidates_the_cache(self, tmp_path, monkeypatch):
        # Without this the cache keeps serving the previously-pinned voice:
        # GH-1221's silent divergence wearing a cache, and for a
        # CC BY-NC-SA voice past its licence gate that is a licence breach.
        monkeypatch.setattr(_narration, "voice_pin_fingerprint", lambda *a, **k: "pin-one")
        first = caching_runner({"alpha": 1000})
        _narration.Narration(tmp_path / "one", script=["alpha"], runner=first).prerender()

        monkeypatch.setattr(_narration, "voice_pin_fingerprint", lambda *a, **k: "pin-two")
        second = caching_runner({"alpha": 1000})
        _narration.Narration(tmp_path / "two", script=["alpha"], runner=second).prerender()

        assert len(second.calls) == 1, "a re-pin must miss rather than serve stale audio"


class TestVoicePinFingerprint:
    def test_the_same_pin_yields_a_stable_fingerprint(self, tmp_path):
        pin = tmp_path / "tts.yaml"
        pin.write_text("voice: af_heart\n")
        assert _narration.voice_pin_fingerprint(pin) == _narration.voice_pin_fingerprint(pin)

    def test_editing_the_pin_changes_the_fingerprint(self, tmp_path):
        pin = tmp_path / "tts.yaml"
        pin.write_text("voice: af_heart\n")
        before = _narration.voice_pin_fingerprint(pin)
        pin.write_text("voice: en_US-ryan-medium\n")
        assert _narration.voice_pin_fingerprint(pin) != before

    def test_an_absent_pin_is_its_own_stable_state(self, tmp_path):
        assert _narration.voice_pin_fingerprint(tmp_path / "absent.yaml") == "unpinned"


class TestFixtureProbeGate:
    """Synthesis is refused until the fixture probe passes (GH-1238)."""

    def test_a_failing_probe_prevents_any_model_load(self, tmp_path):
        runner = caching_runner({"alpha": 1000})
        narration = _narration.Narration(
            tmp_path,
            script=["alpha"],
            runner=runner,
            fixture_probe=lambda: (_ for _ in ()).throw(RuntimeError("owner select is empty")),
        )

        with pytest.raises(_narration.FixtureProbeError) as caught:
            narration.prerender()

        assert runner.calls == [], "a failed fixture must cost fixture time only"
        assert "owner select is empty" in str(caught.value)

    def test_a_probe_returning_false_also_refuses(self, tmp_path):
        runner = caching_runner({"alpha": 1000})
        narration = _narration.Narration(
            tmp_path, script=["alpha"], runner=runner, fixture_probe=lambda: False
        )

        with pytest.raises(_narration.FixtureProbeError):
            narration.prerender()
        assert runner.calls == []

    def test_a_passing_probe_lets_synthesis_run(self, tmp_path):
        runner = caching_runner({"alpha": 1000})
        narration = _narration.Narration(
            tmp_path, script=["alpha"], runner=runner, fixture_probe=lambda: True
        )
        narration.prerender()

        assert len(runner.calls) == 1

    def test_no_probe_keeps_the_previous_behaviour(self, tmp_path):
        runner = caching_runner({"alpha": 1000})
        _narration.Narration(tmp_path, script=["alpha"], runner=runner).prerender()
        assert len(runner.calls) == 1

    def test_the_probe_error_is_a_narration_error(self, tmp_path):
        # Callers that already catch NarrationError keep working.
        assert issubclass(_narration.FixtureProbeError, _narration.NarrationError)


class TestCaptionClaims:
    """A caption must not out-run the state it claims (GH-1240)."""

    def test_a_failing_assertion_aborts_the_beat(self, tmp_path):
        narration = _narration.Narration(tmp_path, script=[], runner=caching_runner({}))

        with pytest.raises(_narration.CaptionClaimError) as caught:
            narration.assert_claim("Assigned instantly", assert_state=lambda: False)

        assert "Assigned instantly" in str(caught.value)
        assert narration.spoken == [], "the beat must not reach the manifest"

    def test_an_assertion_that_raises_is_reported_not_swallowed(self, tmp_path):
        narration = _narration.Narration(tmp_path, script=[], runner=caching_runner({}))

        with pytest.raises(_narration.CaptionClaimError, match="locator timed out"):
            narration.assert_claim(
                "Assigned",
                assert_state=lambda: (_ for _ in ()).throw(RuntimeError("locator timed out")),
            )

    def test_a_holding_assertion_lets_the_caption_cue(self, tmp_path):
        narration = _narration.Narration(tmp_path, script=[], runner=caching_runner({}))
        narration.assert_claim("Assigned", assert_state=lambda: True)
        assert narration.unasserted == []

    def test_a_beat_without_an_assertion_is_recorded_as_unasserted(self, tmp_path):
        narration = _narration.Narration(tmp_path, script=[], runner=caching_runner({}))
        narration.assert_claim("Assigned", assert_state=None)

        # Not a failure — requiring an assertion everywhere would make
        # narration all-or-nothing; a visible gap beats a blocked capture.
        assert narration.unasserted == ["Assigned"]

    def test_unasserted_is_deduplicated(self, tmp_path):
        narration = _narration.Narration(tmp_path, script=[], runner=caching_runner({}))
        narration.assert_claim("Assigned", assert_state=None)
        narration.assert_claim("Assigned", assert_state=None)
        assert narration.unasserted == ["Assigned"]

    def test_the_manifest_reports_which_claims_were_checked(self, tmp_path):
        narration = _narration.Narration(tmp_path, script=[], runner=caching_runner({}))
        narration.assert_claim("Checked", assert_state=lambda: True)
        narration.record("Checked", 900, asserted=True)
        narration.assert_claim("Unchecked", assert_state=None)
        narration.record("Unchecked", 900, asserted=False)

        manifest = narration.manifest()
        assert manifest["unasserted"] == ["Unchecked"]
        assert [entry["asserted"] for entry in manifest["all_captions"]] == [True, False]

    def test_a_legacy_record_call_reports_asserted_as_unknown(self, tmp_path):
        # None (predates assert_state) is a different answer from False
        # (opted out for this beat); collapsing them would report an old
        # script as deliberately unchecked.
        narration = _narration.Narration(tmp_path, script=[], runner=caching_runner({}))
        entry = narration.record("Legacy", 900)
        assert entry["asserted"] is None

    def test_the_claim_error_is_a_narration_error(self):
        assert issubclass(_narration.CaptionClaimError, _narration.NarrationError)
