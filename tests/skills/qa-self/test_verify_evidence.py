"""Tests for the QA evidence verifier (GH-1086).

Loads the uv-script via importlib and exercises the pure helpers —
stddev normalisation, frame sampling, kind classification and report
aggregation — without invoking ImageMagick or ffmpeg.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_repo_root = Path(__file__).resolve().parent.parent.parent.parent
_spec = importlib.util.spec_from_file_location(
    "verify_evidence",
    _repo_root / "skills" / "qa-self" / "scripts" / "verify-evidence.py",
)
assert _spec is not None and _spec.loader is not None
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)


class TestParseStddev:
    def test_normalised_value_passes_through(self):
        assert _mod.parse_stddev("0.1834\n") == pytest.approx(0.1834)

    def test_quantum_scaled_value_is_rescaled(self):
        assert _mod.parse_stddev("6553.5") == pytest.approx(0.1)

    def test_uniform_image_reads_as_zero(self):
        assert _mod.parse_stddev("0") == 0.0

    def test_trailing_tokens_are_ignored(self):
        assert _mod.parse_stddev("0.42 (0.42)") == pytest.approx(0.42)


class TestFrameTimestamps:
    def test_samples_three_points_through_the_recording(self):
        assert _mod.frame_timestamps(40.0) == [10.0, 20.0, 30.0]

    def test_zero_duration_yields_no_samples(self):
        assert _mod.frame_timestamps(0.0) == []

    def test_negative_duration_yields_no_samples(self):
        assert _mod.frame_timestamps(-1.0) == []


class TestClassify:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("shot.png", "screenshot"),
            ("shot.PNG", "screenshot"),
            ("shot.jpg", "screenshot"),
            ("shot.jpeg", "screenshot"),
            ("clip.webm", "video"),
            ("clip.mp4", "video"),
        ],
    )
    def test_infers_kind_from_extension(self, name, expected):
        assert _mod.classify("auto", Path(name)) == expected

    def test_explicit_kind_overrides_extension(self):
        assert _mod.classify("video", Path("frame.png")) == "video"

    def test_unknown_extension_raises(self):
        with pytest.raises(_mod.ToolingError):
            _mod.classify("auto", Path("evidence.txt"))


class TestVerifyMissingFile:
    def test_absent_file_fails_without_invoking_tooling(self, tmp_path):
        result = _mod.verify(tmp_path / "nope.png", kind="auto", min_stddev=0.02)
        assert result["ok"] is False
        assert result["failures"] == ["file does not exist"]


class TestBuildReport:
    def test_all_passing_reports_ok(self):
        report = _mod.build_report([{"ok": True}, {"ok": True}])
        assert report == {"ok": True, "checked": 2, "failed": 0, "artifacts": [{"ok": True}] * 2}

    def test_one_failure_fails_the_whole_report(self):
        report = _mod.build_report([{"ok": True}, {"ok": False}])
        assert report["ok"] is False
        assert report["failed"] == 1

    def test_empty_input_reports_ok(self):
        assert _mod.build_report([])["ok"] is True


class TestVerifyScreenshot:
    def _write(self, tmp_path: Path, *, size: int) -> Path:
        path = tmp_path / "shot.png"
        path.write_bytes(b"\x00" * size)
        return path

    def test_flags_a_file_below_the_size_floor(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_mod, "image_stddev", lambda path: 0.5)
        result = _mod.verify_screenshot(
            self._write(tmp_path, size=200), min_bytes=10_000, min_stddev=0.02
        )
        assert result["ok"] is False
        assert "below the 10000-byte floor" in result["failures"][0]

    def test_flags_a_uniform_frame(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_mod, "image_stddev", lambda path: 0.0)
        result = _mod.verify_screenshot(
            self._write(tmp_path, size=50_000), min_bytes=10_000, min_stddev=0.02
        )
        assert result["ok"] is False
        assert "uniform" in result["failures"][0]

    def test_passes_a_real_looking_screenshot(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_mod, "image_stddev", lambda path: 0.21)
        result = _mod.verify_screenshot(
            self._write(tmp_path, size=120_000), min_bytes=10_000, min_stddev=0.02
        )
        assert result["ok"] is True
        assert result["failures"] == []


class TestSizeFloorFailures:
    def test_a_file_at_the_floor_passes(self):
        assert _mod.size_floor_failures(10_000, 10_000) == []

    def test_a_file_below_the_floor_reports_both_numbers(self):
        (failure,) = _mod.size_floor_failures(200, 10_000)
        assert "200 bytes" in failure
        assert "10000-byte floor" in failure


class TestVerifyVideo:
    def _write(self, tmp_path: Path, *, size: int) -> Path:
        path = tmp_path / "clip.webm"
        path.write_bytes(b"\x00" * size)
        return path

    def test_flags_a_recording_with_no_duration(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_mod, "video_duration", lambda path: 0.0)
        result = _mod.verify_video(
            self._write(tmp_path, size=500_000), min_bytes=50_000, min_stddev=0.02
        )
        assert result["ok"] is False
        assert "never flushed" in result["failures"][0]

    def test_flags_a_recording_whose_every_frame_is_uniform(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_mod, "video_duration", lambda path: 30.0)
        monkeypatch.setattr(_mod, "extract_frame", lambda path, *, offset, dest: None)
        monkeypatch.setattr(_mod, "image_stddev", lambda path: 0.001)
        result = _mod.verify_video(
            self._write(tmp_path, size=500_000), min_bytes=50_000, min_stddev=0.02
        )
        assert result["ok"] is False
        assert "every sampled frame is uniform" in result["failures"][0]

    def test_one_non_uniform_frame_is_enough_to_pass(self, tmp_path, monkeypatch):
        stddevs = iter([0.0, 0.3, 0.0])
        monkeypatch.setattr(_mod, "video_duration", lambda path: 30.0)
        monkeypatch.setattr(_mod, "extract_frame", lambda path, *, offset, dest: None)
        monkeypatch.setattr(_mod, "image_stddev", lambda path: next(stddevs))
        result = _mod.verify_video(
            self._write(tmp_path, size=500_000), min_bytes=50_000, min_stddev=0.02
        )
        assert result["ok"] is True
        assert [frame["at"] for frame in result["frames"]] == [7.5, 15.0, 22.5]

    def test_saved_frames_survive_and_are_reported(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_mod, "video_duration", lambda path: 30.0)
        monkeypatch.setattr(
            _mod, "extract_frame", lambda path, *, offset, dest: dest.write_bytes(b"png")
        )
        monkeypatch.setattr(_mod, "image_stddev", lambda path: 0.3)
        frames_dir = tmp_path / "review-frames"

        result = _mod.verify_video(
            self._write(tmp_path, size=500_000),
            min_bytes=50_000,
            min_stddev=0.02,
            save_frames=frames_dir,
        )

        saved = [Path(frame["path"]) for frame in result["frames"]]
        assert len(saved) == 3
        assert all(path.exists() for path in saved)

    def test_frames_are_discarded_when_no_destination_is_given(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_mod, "video_duration", lambda path: 30.0)
        monkeypatch.setattr(
            _mod, "extract_frame", lambda path, *, offset, dest: dest.write_bytes(b"png")
        )
        monkeypatch.setattr(_mod, "image_stddev", lambda path: 0.3)

        result = _mod.verify_video(
            self._write(tmp_path, size=500_000), min_bytes=50_000, min_stddev=0.02
        )

        assert all("path" not in frame for frame in result["frames"])

    def test_size_floor_still_applies_to_a_watchable_recording(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_mod, "video_duration", lambda path: 30.0)
        monkeypatch.setattr(_mod, "extract_frame", lambda path, *, offset, dest: None)
        monkeypatch.setattr(_mod, "image_stddev", lambda path: 0.3)
        result = _mod.verify_video(
            self._write(tmp_path, size=1_000), min_bytes=50_000, min_stddev=0.02
        )
        assert result["ok"] is False


class TestMain:
    def test_reports_tooling_error_as_json_on_stdout(self, tmp_path, capsys):
        target = tmp_path / "evidence.txt"
        target.write_text("not an artifact")
        assert _mod.main([str(target)]) == 2
        assert "error" in capsys.readouterr().out

    def test_failing_artifact_exits_one(self, tmp_path, capsys):
        assert _mod.main([str(tmp_path / "missing.png")]) == 1
        assert '"ok": false' in capsys.readouterr().out
