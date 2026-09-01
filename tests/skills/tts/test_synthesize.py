"""Tests for the Piper narration wrapper (GH-1112).

Piper is not invoked here. What is pinned is the logic that would silently
corrupt a narration track or leak a licence breach: the positional mapping
between input lines and output clips, the licence gate, preference
resolution, and the actionable-failure contract.
"""

from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path

import pytest

_repo_root = Path(__file__).resolve().parent.parent.parent.parent
_spec = importlib.util.spec_from_file_location(
    "synthesize", _repo_root / "skills" / "tts" / "scripts" / "synthesize.py"
)
assert _spec is not None and _spec.loader is not None
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """Never read or write the developer's real ~/.config/Dev10x/tts.yaml."""
    monkeypatch.setenv("DEV10X_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.delenv("DEV10X_PIPER_VOICE", raising=False)
    return tmp_path / "config" / "tts.yaml"


class TestNormalizeLine:
    def test_collapses_whitespace(self):
        assert _mod.normalize_line("  a\n b\tc ") == "a b c"

    def test_empty_segment_is_rejected(self):
        # An empty line would make piper emit one clip fewer than expected,
        # shifting every later caption onto the wrong audio.
        with pytest.raises(_mod.SynthesisError, match="empty"):
            _mod.normalize_line("   \n  ")


class TestLicence:
    def test_known_permissive_voice_needs_no_warning(self):
        assert _mod.licence_warning("en_US-libritts_r-medium", accepted=False) is None

    def test_non_commercial_voice_warns_and_names_the_licence(self):
        warning = _mod.licence_warning("en_US-ryan-medium", accepted=False)
        assert "CC BY-NC-SA 4.0" in warning
        assert "--accept-licence" in warning

    def test_unknown_voice_is_not_assumed_permissive(self):
        warning = _mod.licence_warning("xx_XX-nobody-medium", accepted=False)
        assert "no licence on record" in warning

    def test_acceptance_silences_the_warning(self):
        assert _mod.licence_warning("en_US-ryan-medium", accepted=True) is None

    def test_default_voice_permits_commercial_use(self):
        # The built-in default is chosen for its licence; a change that makes
        # the default non-commercial should fail here.
        _, commercial_ok = _mod.licence_for(_mod.DEFAULT_VOICE)
        assert commercial_ok is True


class TestPreferenceResolution:
    def test_falls_back_to_the_builtin_when_unconfigured(self):
        assert _mod.resolve_preference(None)["voice"] == _mod.DEFAULT_VOICE

    def test_flag_wins_over_everything(self, monkeypatch):
        monkeypatch.setenv("DEV10X_PIPER_VOICE", "env-voice")
        assert _mod.resolve_preference("flag-voice")["voice"] == "flag-voice"

    def test_env_wins_over_config(self, monkeypatch):
        _mod.write_config({"defaults": {"voice": "config-voice"}})
        monkeypatch.setenv("DEV10X_PIPER_VOICE", "env-voice")
        assert _mod.resolve_preference(None)["voice"] == "env-voice"

    def test_pinned_default_is_used(self):
        _mod.write_config({"defaults": {"voice": "config-voice"}})
        resolved = _mod.resolve_preference(None)
        assert resolved["voice"] == "config-voice"
        assert resolved["source"] == "defaults"

    def test_project_entry_wins_over_defaults(self, tmp_path):
        _mod.write_config(
            {
                "defaults": {"voice": "global-voice"},
                "projects": [{"match": [tmp_path.name], "voice": "project-voice"}],
            }
        )
        assert _mod.resolve_preference(None, cwd=tmp_path)["voice"] == "project-voice"

    def test_acceptance_does_not_carry_over_to_another_voice(self):
        # Consent is given for a specific voice's terms. Switching voices
        # must re-arm the gate rather than inherit the old acceptance.
        _mod.write_config({"defaults": {"voice": "voice-a", "licence_accepted": True}})
        assert _mod.resolve_preference("voice-b")["licence_accepted"] is False

    def test_acceptance_applies_to_the_voice_it_was_given_for(self):
        _mod.write_config({"defaults": {"voice": "voice-a", "licence_accepted": True}})
        assert _mod.resolve_preference(None)["licence_accepted"] is True

    def test_malformed_config_fails_loud(self, isolated_config):
        isolated_config.parent.mkdir(parents=True, exist_ok=True)
        isolated_config.write_text("defaults: [unclosed\n", encoding="utf-8")
        with pytest.raises(_mod.SynthesisError, match="not valid YAML"):
            _mod.resolve_preference(None)

    def test_absent_config_is_not_an_error(self):
        assert _mod.load_config() == {}


class TestPin:
    def test_pin_persists_the_choice(self):
        args = _make_args(voice="en_US-ryan-medium", accept_licence=True, match=None)
        result = _mod.cmd_pin(args)

        assert result["pinned"] is True
        assert _mod.load_config()["defaults"] == {
            "voice": "en_US-ryan-medium",
            "licence_accepted": True,
        }

    def test_pin_is_idempotent_for_the_same_scope(self, tmp_path):
        match = ["*/some-repo"]
        _mod.cmd_pin(_make_args(voice="voice-a", accept_licence=False, match=match))
        _mod.cmd_pin(_make_args(voice="voice-b", accept_licence=False, match=match))

        projects = _mod.load_config()["projects"]
        assert len(projects) == 1, "re-pinning must replace, never duplicate"
        assert projects[0]["voice"] == "voice-b"

    def test_pin_without_acceptance_does_not_record_consent(self):
        _mod.cmd_pin(_make_args(voice="en_US-ryan-medium", accept_licence=False, match=None))
        assert _mod.resolve_preference(None)["licence_accepted"] is False


class TestResolution:
    def test_missing_voice_names_the_download_command(self, tmp_path):
        with pytest.raises(_mod.SynthesisError) as error:
            _mod.voice_model(tmp_path, "en_US-nope-medium")
        message = str(error.value)
        assert "download_voices" in message
        assert str(tmp_path) in message

    def test_missing_piper_names_the_install_command(self, monkeypatch):
        monkeypatch.delenv("DEV10X_PIPER_BIN", raising=False)
        monkeypatch.setattr(_mod.shutil, "which", lambda name: None)
        with pytest.raises(_mod.SynthesisError, match="uv tool install piper-tts"):
            _mod.resolve_piper()

    def test_voices_dir_is_never_left_to_pipers_cwd_default(self, monkeypatch):
        monkeypatch.delenv("DEV10X_PIPER_VOICES", raising=False)
        assert _mod.resolve_voices_dir(None) == _mod.DEFAULT_VOICES_DIR


class TestBatchMapping:
    def test_clip_count_mismatch_refuses_to_guess(self, tmp_path, monkeypatch):
        # Pairing the wrong audio with the wrong caption is worse than
        # failing: the recording plays, narrating the wrong steps.
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        (raw_dir / "1.wav").write_bytes(b"")

        monkeypatch.setattr(
            _mod.subprocess,
            "run",
            lambda *a, **k: _CompletedProcess(returncode=0, stdout="", stderr=""),
        )
        with pytest.raises(_mod.SynthesisError, match="refusing to guess"):
            _mod.run_piper(
                piper="piper",
                model=tmp_path / "m.onnx",
                voices_dir=tmp_path,
                lines=["one", "two"],
                raw_dir=raw_dir,
                length_scale=None,
                sentence_silence=None,
                speaker=None,
            )

    def test_piper_failure_surfaces_its_stderr(self, tmp_path, monkeypatch):
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        monkeypatch.setattr(
            _mod.subprocess,
            "run",
            lambda *a, **k: _CompletedProcess(returncode=2, stdout="", stderr="bad model"),
        )
        with pytest.raises(_mod.SynthesisError, match="bad model"):
            _mod.run_piper(
                piper="piper",
                model=tmp_path / "m.onnx",
                voices_dir=tmp_path,
                lines=["one"],
                raw_dir=raw_dir,
                length_scale=None,
                sentence_silence=None,
                speaker=None,
            )

    def test_batch_runs_piper_once_for_every_segment(self, tmp_path, monkeypatch):
        calls: list[list[str]] = []

        def fake_run(command, **kwargs):
            calls.append(command)
            raw_dir = Path(command[command.index("--output-dir") + 1])
            for index in range(2):
                _write_wav(raw_dir / f"{index}.wav")
            return _CompletedProcess(returncode=0, stdout="", stderr="")

        voices = tmp_path / "voices"
        voices.mkdir()
        (voices / "test-voice.onnx").write_bytes(b"model")

        # resolve_piper() insists the binary exists on disk, so point it at a
        # real file rather than a which() stub returning a phantom path.
        stub_piper = tmp_path / "piper"
        stub_piper.write_text("#!/bin/sh\n", encoding="utf-8")
        monkeypatch.setenv("DEV10X_PIPER_BIN", str(stub_piper))
        monkeypatch.setattr(_mod.subprocess, "run", fake_run)

        segments = {"segments": [{"id": "a", "text": "one"}, {"id": "b", "text": "two"}]}
        payload_file = tmp_path / "segments.json"
        payload_file.write_text(json.dumps(segments), encoding="utf-8")

        result = _mod.cmd_batch(
            _make_args(
                voice="test-voice",
                voices_dir=str(voices),
                segments_file=str(payload_file),
                out_dir=str(tmp_path / "out"),
                length_scale=None,
                sentence_silence=None,
                speaker=None,
            )
        )

        assert len(calls) == 1, "model load must be paid once per batch, not per line"
        assert [segment["id"] for segment in result["segments"]] == ["a", "b"]
        assert all(segment["duration_ms"] > 0 for segment in result["segments"])


class TestTrackCommand:
    def test_each_clip_is_delayed_to_its_own_cue(self, tmp_path):
        segments = [
            {"wav": "a.wav", "offset_ms": 0},
            {"wav": "b.wav", "offset_ms": 4200},
        ]
        command = _mod.build_track_command(segments, tmp_path / "vo.wav")
        graph = command[command.index("-filter_complex") + 1]

        assert "adelay=0|0" in graph
        assert "adelay=4200|4200" in graph

    def test_mix_does_not_attenuate_non_overlapping_clips(self, tmp_path):
        # amix divides by input count by default, so a 6-line narration
        # would render at a sixth of its volume.
        command = _mod.build_track_command([{"wav": "a.wav", "offset_ms": 0}], tmp_path / "vo.wav")
        assert "normalize=0" in command[command.index("-filter_complex") + 1]

    def test_track_is_resampled_for_delivery(self, tmp_path):
        command = _mod.build_track_command([{"wav": "a.wav", "offset_ms": 0}], tmp_path / "vo.wav")
        assert command[command.index("-ar") + 1] == str(_mod.TRACK_SAMPLE_RATE)

    def test_negative_offsets_are_clamped(self, tmp_path):
        command = _mod.build_track_command(
            [{"wav": "a.wav", "offset_ms": -500}], tmp_path / "vo.wav"
        )
        assert "adelay=0|0" in command[command.index("-filter_complex") + 1]


class TestSegmentValidation:
    def test_segment_without_text_is_rejected_by_index(self, tmp_path, monkeypatch):
        voices = _stub_voice(tmp_path, monkeypatch)
        payload = tmp_path / "segments.json"
        payload.write_text(
            json.dumps({"segments": [{"id": "a", "text": "one"}, {"id": "b"}]}), encoding="utf-8"
        )
        with pytest.raises(_mod.SynthesisError, match=r"index \[1\]"):
            _mod.cmd_batch(
                _make_args(
                    voice="test-voice",
                    voices_dir=str(voices),
                    segments_file=str(payload),
                    out_dir=str(tmp_path / "out"),
                )
            )

    def test_empty_segment_list_is_rejected(self, tmp_path):
        payload = tmp_path / "segments.json"
        payload.write_text(json.dumps({"segments": []}), encoding="utf-8")
        with pytest.raises(_mod.SynthesisError, match="no segments supplied"):
            _mod.cmd_batch(_make_args(segments_file=str(payload), out_dir=str(tmp_path / "out")))

    def test_id_defaults_when_a_segment_omits_one(self, tmp_path, monkeypatch):
        voices = _stub_voice(tmp_path, monkeypatch)
        _fake_piper(monkeypatch, clips=1)
        payload = tmp_path / "segments.json"
        payload.write_text(json.dumps({"segments": [{"text": "one"}]}), encoding="utf-8")

        result = _mod.cmd_batch(
            _make_args(
                voice="test-voice",
                voices_dir=str(voices),
                segments_file=str(payload),
                out_dir=str(tmp_path / "out"),
            )
        )
        assert result["segments"][0]["id"] == "seg-000"


class TestPacingFlags:
    def test_optional_flags_reach_piper_only_when_set(self, tmp_path, monkeypatch):
        captured: dict[str, list] = {}

        def capture(command, **kwargs):
            captured["command"] = command
            raw_dir = Path(command[command.index("--output-dir") + 1])
            _write_wav(raw_dir / "0.wav")
            return _CompletedProcess(returncode=0, stdout="", stderr="")

        voices = _stub_voice(tmp_path, monkeypatch)
        monkeypatch.setattr(_mod.subprocess, "run", capture)
        payload = tmp_path / "segments.json"
        payload.write_text(json.dumps({"segments": [{"text": "one"}]}), encoding="utf-8")

        _mod.cmd_batch(
            _make_args(
                voice="test-voice",
                voices_dir=str(voices),
                segments_file=str(payload),
                out_dir=str(tmp_path / "out"),
                length_scale=1.2,
                sentence_silence=0.4,
                speaker=3,
            )
        )
        command = captured["command"]
        assert command[command.index("--length-scale") + 1] == "1.2"
        assert command[command.index("--sentence-silence") + 1] == "0.4"
        assert command[command.index("--speaker") + 1] == "3"

    def test_unset_flags_are_omitted_so_the_model_defaults_apply(self, tmp_path, monkeypatch):
        captured: dict[str, list] = {}

        def capture(command, **kwargs):
            captured["command"] = command
            raw_dir = Path(command[command.index("--output-dir") + 1])
            _write_wav(raw_dir / "0.wav")
            return _CompletedProcess(returncode=0, stdout="", stderr="")

        voices = _stub_voice(tmp_path, monkeypatch)
        monkeypatch.setattr(_mod.subprocess, "run", capture)
        payload = tmp_path / "segments.json"
        payload.write_text(json.dumps({"segments": [{"text": "one"}]}), encoding="utf-8")

        _mod.cmd_batch(
            _make_args(
                voice="test-voice",
                voices_dir=str(voices),
                segments_file=str(payload),
                out_dir=str(tmp_path / "out"),
            )
        )
        assert "--length-scale" not in captured["command"]
        assert "--speaker" not in captured["command"]


class TestConfigWriteSafety:
    def test_a_failed_write_leaves_no_temp_file_behind(self, tmp_path, monkeypatch):
        # The atomic-write contract: a crash mid-dump must not leave a
        # half-written sibling next to the real config.
        monkeypatch.setattr(
            _mod.yaml, "safe_dump", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full"))
        )
        with pytest.raises(OSError, match="disk full"):
            _mod.write_config({"defaults": {"voice": "v"}})

        assert list(_mod.config_path().parent.glob("*.tmp")) == []


class TestCmdCheck:
    def test_reports_the_resolved_toolchain(self, tmp_path, monkeypatch):
        voices = _stub_voice(tmp_path, monkeypatch)
        result = _mod.cmd_check(_make_args(voice="test-voice", voices_dir=str(voices)))

        assert result["voice"] == "test-voice"
        assert result["model"].endswith("test-voice.onnx")
        assert result["config"].endswith("tts.yaml")
        assert "warning" in result


class TestCmdTrack:
    def test_missing_wav_points_back_at_batch(self, tmp_path):
        payload = tmp_path / "timed.json"
        payload.write_text(
            json.dumps({"segments": [{"wav": str(tmp_path / "gone.wav"), "offset_ms": 0}]}),
            encoding="utf-8",
        )
        with pytest.raises(_mod.SynthesisError, match="batch"):
            _mod.cmd_track(_make_args(segments_file=str(payload), out=str(tmp_path / "vo.wav")))

    def test_absent_ffmpeg_is_named(self, tmp_path, monkeypatch):
        clip = tmp_path / "a.wav"
        _write_wav(clip)
        payload = tmp_path / "timed.json"
        payload.write_text(
            json.dumps({"segments": [{"wav": str(clip), "offset_ms": 0}]}), encoding="utf-8"
        )
        monkeypatch.setattr(_mod.shutil, "which", lambda name: None)

        with pytest.raises(_mod.SynthesisError, match="ffmpeg not found"):
            _mod.cmd_track(_make_args(segments_file=str(payload), out=str(tmp_path / "vo.wav")))

    def test_ffmpeg_failure_surfaces_stderr(self, tmp_path, monkeypatch):
        clip = tmp_path / "a.wav"
        _write_wav(clip)
        payload = tmp_path / "timed.json"
        payload.write_text(
            json.dumps({"segments": [{"wav": str(clip), "offset_ms": 0}]}), encoding="utf-8"
        )
        monkeypatch.setattr(_mod.shutil, "which", lambda name: "/usr/bin/ffmpeg")
        monkeypatch.setattr(
            _mod.subprocess,
            "run",
            lambda *a, **k: _CompletedProcess(returncode=1, stdout="", stderr="filter broke"),
        )
        with pytest.raises(_mod.SynthesisError, match="filter broke"):
            _mod.cmd_track(_make_args(segments_file=str(payload), out=str(tmp_path / "vo.wav")))

    def test_success_reports_the_track_duration(self, tmp_path, monkeypatch):
        clip = tmp_path / "a.wav"
        _write_wav(clip)
        output = tmp_path / "vo.wav"
        payload = tmp_path / "timed.json"
        payload.write_text(
            json.dumps({"segments": [{"wav": str(clip), "offset_ms": 0}]}), encoding="utf-8"
        )
        monkeypatch.setattr(_mod.shutil, "which", lambda name: "/usr/bin/ffmpeg")

        def fake_ffmpeg(command, **kwargs):
            _write_wav(output)
            return _CompletedProcess(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(_mod.subprocess, "run", fake_ffmpeg)
        result = _mod.cmd_track(_make_args(segments_file=str(payload), out=str(output)))

        assert result["segments"] == 1
        assert result["duration_ms"] == 1000
        assert result["sample_rate"] == _mod.TRACK_SAMPLE_RATE

    def test_empty_segment_list_is_rejected(self, tmp_path):
        payload = tmp_path / "timed.json"
        payload.write_text(json.dumps({"segments": []}), encoding="utf-8")
        with pytest.raises(_mod.SynthesisError, match="no segments supplied"):
            _mod.cmd_track(_make_args(segments_file=str(payload), out=str(tmp_path / "vo.wav")))


class TestReadPayload:
    def test_reads_stdin_when_no_file_is_given(self, monkeypatch):
        monkeypatch.setattr(_mod.sys, "stdin", io.StringIO('{"segments": [{"text": "x"}]}'))
        assert _mod._read_payload(None) == {"segments": [{"text": "x"}]}

    def test_invalid_json_is_actionable(self, tmp_path):
        payload = tmp_path / "bad.json"
        payload.write_text("{not json", encoding="utf-8")
        with pytest.raises(_mod.SynthesisError, match="not valid JSON"):
            _mod._read_payload(str(payload))


class TestConfigEdgeCases:
    def test_yaml_that_is_not_a_mapping_is_ignored(self, isolated_config):
        isolated_config.parent.mkdir(parents=True, exist_ok=True)
        isolated_config.write_text("- a\n- b\n", encoding="utf-8")
        assert _mod.load_config() == {}

    def test_full_path_glob_matches(self, tmp_path):
        _mod.write_config({"projects": [{"match": ["*/tts-*"], "voice": "path-voice"}]})
        here = tmp_path / "tts-worktree"
        assert _mod.resolve_preference(None, cwd=here)["voice"] == "path-voice"

    def test_non_dict_project_entry_is_skipped(self, tmp_path):
        _mod.write_config(
            {
                "defaults": {"voice": "fallback"},
                "projects": ["not-a-mapping", {"match": [tmp_path.name], "voice": "real"}],
            }
        )
        assert _mod.resolve_preference(None, cwd=tmp_path)["voice"] == "real"

    def test_first_matching_entry_wins(self, tmp_path):
        _mod.write_config(
            {
                "projects": [
                    {"match": [tmp_path.name], "voice": "first"},
                    {"match": [tmp_path.name], "voice": "second"},
                ]
            }
        )
        assert _mod.resolve_preference(None, cwd=tmp_path)["voice"] == "first"


class TestWavDuration:
    def test_zero_sample_rate_is_rejected(self, tmp_path, monkeypatch):
        clip = tmp_path / "a.wav"
        _write_wav(clip)
        monkeypatch.setattr(_mod.wave, "open", lambda *a, **k: _FakeWave(frames=10, rate=0))
        with pytest.raises(_mod.SynthesisError, match="zero sample rate"):
            _mod.wav_duration_ms(clip)


class TestMainIntegration:
    def test_domain_failure_exits_nonzero_with_json_on_stdout(self, tmp_path, monkeypatch, capsys):
        monkeypatch.delenv("DEV10X_PIPER_BIN", raising=False)
        monkeypatch.setattr(_mod.shutil, "which", lambda name: None)

        with pytest.raises(SystemExit) as exit_info:
            _mod.main(["check"])

        assert exit_info.value.code == 1
        assert "piper-tts" in json.loads(capsys.readouterr().out)["error"]

    def test_timeout_is_reported_on_the_same_channel(self, tmp_path, monkeypatch, capsys):
        voices = _stub_voice(tmp_path, monkeypatch)

        def wedge(*args, **kwargs):
            raise _mod.subprocess.TimeoutExpired(cmd="piper", timeout=1)

        monkeypatch.setattr(_mod.subprocess, "run", wedge)
        payload = tmp_path / "segments.json"
        payload.write_text(json.dumps({"segments": [{"text": "one"}]}), encoding="utf-8")

        with pytest.raises(SystemExit):
            _mod.main(
                [
                    "batch",
                    "--voice",
                    "test-voice",
                    "--voices-dir",
                    str(voices),
                    "--segments-file",
                    str(payload),
                    "--out-dir",
                    str(tmp_path / "out"),
                ]
            )
        assert "wedged" in json.loads(capsys.readouterr().out)["error"]

    def test_unexpected_error_still_lands_on_stdout(self, monkeypatch, capsys):
        # An escaping traceback would leave the caller with empty stdout and
        # a generic "wrapper failed", discarding the actionable detail.
        monkeypatch.setattr(
            _mod, "cmd_check", lambda args: (_ for _ in ()).throw(RuntimeError("boom"))
        )
        with pytest.raises(SystemExit):
            _mod.main(["check"])
        assert "boom" in json.loads(capsys.readouterr().out)["error"]

    def test_pin_round_trips_through_the_parser(self, capsys):
        _mod.main(["pin", "--voice", "en_US-ryan-medium", "--accept-licence"])
        capsys.readouterr()
        assert _mod.resolve_preference(None)["licence_accepted"] is True


class TestErrorContract:
    def test_errors_are_json_on_stdout_with_a_nonzero_exit(self, capsys):
        # Callers parse stdout; an error on stderr alone leaves them with
        # empty stdout and no explanation.
        with pytest.raises(SystemExit) as exit_info:
            _mod._fail("something actionable")

        assert exit_info.value.code == 1
        assert json.loads(capsys.readouterr().out) == {"error": "something actionable"}


class _FakeWave:
    def __init__(self, frames: int, rate: int) -> None:
        self._frames = frames
        self._rate = rate

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        return None

    def getnframes(self) -> int:
        return self._frames

    def getframerate(self) -> int:
        return self._rate


def _stub_voice(tmp_path: Path, monkeypatch) -> Path:
    """A voices dir plus an on-disk stub binary resolve_piper() will accept."""
    voices = tmp_path / "voices"
    voices.mkdir(exist_ok=True)
    (voices / "test-voice.onnx").write_bytes(b"model")
    stub = tmp_path / "piper"
    stub.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setenv("DEV10X_PIPER_BIN", str(stub))
    return voices


def _fake_piper(monkeypatch, *, clips: int) -> None:
    """Stand in for piper, writing `clips` WAVs into its --output-dir."""

    def run(command, **kwargs):
        raw_dir = Path(command[command.index("--output-dir") + 1])
        for index in range(clips):
            _write_wav(raw_dir / f"{index}.wav")
        return _CompletedProcess(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(_mod.subprocess, "run", run)


class _CompletedProcess:
    def __init__(self, returncode: int, stdout: str, stderr: str) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _write_wav(path: Path) -> None:
    """A real, minimal WAV so duration reading exercises the same code path."""
    import wave

    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(22050)
        handle.writeframes(b"\x00\x00" * 22050)


def _make_args(**overrides):
    import argparse

    defaults = {
        "voice": None,
        "voices_dir": None,
        "accept_licence": False,
        "match": None,
        "segments_file": None,
        "out_dir": None,
        "length_scale": None,
        "sentence_silence": None,
        "speaker": None,
        "out": None,
    }
    return argparse.Namespace(**{**defaults, **overrides})
